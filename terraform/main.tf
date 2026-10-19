terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }

    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }

    helm = {
      source  = "hashicorp/helm"
      version = "~>2.0"

    }

    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

resource "aws_s3_bucket" "lecture_audio" {
  bucket        = var.bucket_name
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "lecture_audio" {
  bucket = aws_s3_bucket.lecture_audio.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_cors_configuration" "lecture_audio" {
  bucket = aws_s3_bucket.lecture_audio.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["PUT", "GET"]
    allowed_origins = ["http://localhost:5173", "https://web-pi-flax-71.vercel.app"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

resource "aws_sqs_queue" "lectures_dlq" {
  name = "studymate-lectures-dlq"
}

resource "aws_sqs_queue" "lectures" {
  name                       = "studymate-lectures"
  visibility_timeout_seconds = 900
  message_retention_seconds  = 86400

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.lectures_dlq.arn
    maxReceiveCount     = 3
  })
}

# --- Container image repositories (EKS services) ---

resource "aws_ecr_repository" "auth_service" {
  name                 = "studymate-auth-service"
  image_tag_mutability = "MUTABLE"

  force_delete = true
}

resource "aws_ecr_repository" "core_api" {
  name                 = "studymate-core-api"
  image_tag_mutability = "MUTABLE"

  force_delete = true
}

resource "aws_ecr_repository" "worker" {
  name                 = "studymate-worker"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
}
