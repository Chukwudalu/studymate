from dotenv import load_dotenv
load_dotenv()

import os
import json
import boto3

from apps.worker.jobs import run_transcription_job, run_flashcards_job, run_quiz_job
# from apps.api.queue import redis_conn, queue


sqs = boto3.client("sqs", region_name="us-west-2")
QUEUE_URL = os.environ["SQS_QUEUE_URL"]

JOB_HANDLERS = {
    "transcription": run_transcription_job,
    "flashcards": run_flashcards_job,
    "quiz": run_quiz_job
}

def poll():
    while True:
        response = sqs.receive_message(
            QueueUrl=QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20
        )
        messages = response.get("Messages", [])
        if not messages:
            continue

        for message in messages:
            body = json.loads(message["Body"])
            handler = JOB_HANDLERS.get(body["job_type"])
            if handler is None:
                print(f"Unknown job_type: {body['job_type']}")
                continue

            try:
                handler(body["lecture_id"])
            except Exception as e:
                print(f"Job failed, will retry: {e}")
                continue

            sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=message["ReceiptHandle"])


if __name__=="__main__":
    poll()

