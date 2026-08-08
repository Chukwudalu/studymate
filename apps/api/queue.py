import os
import json
import boto3

sqs = boto3.client("sqs", region_name="us-west-2")
QUEUE_URL = os.environ["SQS_QUEUE_URL"]


def enqueue_job(job_type: str, lecture_id: str) -> None:
    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps({"job_type": job_type, "lecture_id": lecture_id}),
    )
