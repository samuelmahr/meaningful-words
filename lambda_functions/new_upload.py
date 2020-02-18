"""Start transcribe job triggered from S3"""
import json
import logging.config
import os
import time

import boto3

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)
MEDIA_FILE_URI = 'https://s3.us-east-1.amazonaws.com/{bucket}/{key}'
MILLIS_PER_SECOND = 1000
S3_CLIENT = boto3.client('s3')
TRANSCRIBE_CLIENT = boto3.client('transcribe')
TRANSCRIPT_HISTORY_TABLE = boto3.resource('dynamodb').Table(os.environ['TRANSCRIPT_HISTORY_TABLE'])


def handler(event, context):
    LOGGER.info(json.dumps(event))
    for record in event['Records']:
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key'].replace('+', ' ')
        metadata = get_metadata(bucket, key)
        LOGGER.info(json.dumps({'metadata': metadata}))
        if not metadata.get('customer'):
            LOGGER.error('Customer missing in metadata!')
            continue

        if metadata.get('media_format', '') not in ('mp3', 'mp4', 'wav', 'flac'):
            LOGGER.error(f'Unsupported media format! {metadata["media_format"]}')
            continue

        dynamo_record = build_dynamo_record(bucket, key, metadata)
        if not has_all_required_keys(dynamo_record):
            dynamo_record.update({'flagged': True})

        is_started = start_transcribe_job(bucket, key, dynamo_record['job_name'], metadata['media_format'])
        if not is_started:
            LOGGER.error('Error starting Transcribe Job!')
            dynamo_record.update({'status': 'FAILED'})
            put_dynamo_record(dynamo_record)
            continue

        dynamo_record.update({'status': 'Transcribing'})
        put_dynamo_record(dynamo_record)

    return event


def get_metadata(bucket, key):
    return S3_CLIENT.get_object(
        Bucket=bucket,
        Key=key,
    )['Metadata']


def build_dynamo_record(bucket, key, metadata):
    approximate_timestamp = int(time.time() * MILLIS_PER_SECOND)
    dynamo_record = {
        'approximate_timestamp': approximate_timestamp,
        'job_name': f'{metadata["customer"]}-{approximate_timestamp}'.replace(' ', ''),
        'upload_bucket': bucket,
        'upload_key': key,
        **metadata
    }

    return dynamo_record


def has_all_required_keys(dynamo_record):
    return 'customer' in dynamo_record and 'media_format' in dynamo_record


def put_dynamo_record(record):
    TRANSCRIPT_HISTORY_TABLE.put_item(Item=record)


def start_transcribe_job(bucket, key, job_name, media_format):

    response = TRANSCRIBE_CLIENT.start_transcription_job(
        TranscriptionJobName=job_name,
        LanguageCode='en-US',
        MediaFormat=media_format,
        Media={
            'MediaFileUri': MEDIA_FILE_URI.format(bucket=bucket, key=key)
        }
    )
    LOGGER.info(response)
    return True
