import os

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("SQS_QUEUE_URL", "https://sqs.us-west-2.amazonaws.com/123456789012/test-queue")
os.environ.setdefault("AUTH_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
