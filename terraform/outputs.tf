output "bucket_name" {
  value = aws_s3_bucket.lecture_audio.bucket
}

output "sqs_queue_url" {
  value = aws_sqs_queue.lectures.id
}

output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "api_url" {
  value = aws_apigatewayv2_api.api.api_endpoint
}

output "worker_ecr_repository_url" {
  value = aws_ecr_repository.worker.repository_url
}

output "worker_ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "worker_ecs_service" {
  value = aws_ecs_service.worker.name
}