output "bucket_name" {
  value = aws_s3_bucket.lecture_audio.bucket
}

output "sqs_queue_url" {
  value = aws_sqs_queue.lectures.id
}

output "worker_ecr_repository_url" {
  value = aws_ecr_repository.worker.repository_url
}
