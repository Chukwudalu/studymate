variable "aws_region" {
    description = "AWS region to deploy resources into"
    type = string
    default = "us-west-2"
}


variable "bucket_name" {
    description = "Name of the S3 bucket for lecture audio storage"
    type = string
}

variable "database_url" {
    description = "Supabase Postgres connection string used by the API Lambda"
    type        = string
    sensitive   = true
}

variable "api_image_tag" {
    description = "Tag of the apps/api image in ECR to deploy to Lambda"
    type        = string
    default     = "latest"
}

variable "auth_jwt_secret" {
    description = "JWT signing secret, used by the API Lambda to issue and verify per-user auth tokens"
    type        = string
    sensitive   = true
}

variable "openai_api_key" {
    description = "OpenAI API key, used by the worker for Whisper transcription"
    type        = string
    sensitive   = true
}

variable "anthropic_api_key" {
    description = "Anthropic API key, used by the worker for the LangGraph pipeline nodes"
    type        = string
    sensitive   = true
}

variable "worker_image_tag" {
    description = "Tag of the apps/worker image in ECR to deploy to the ECS service"
    type        = string
    default     = "latest"
}
