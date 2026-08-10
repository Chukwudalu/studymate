terraform {
    required_providers {
        aws = {
            source = "hashicorp/aws"
            version = "~> 5.0"
        }

        tls = {
            source  = "hashicorp/tls"
            version = "~> 4.0"
        }
    }
}

provider "aws" {
    region = var.aws_region
}

resource "aws_s3_bucket" "lecture_audio" {
    bucket = var.bucket_name
}

resource "aws_s3_bucket_public_access_block" "lecture_audio" {
    bucket = aws_s3_bucket.lecture_audio.id

    block_public_acls = true
    block_public_policy = true
    ignore_public_acls = true
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
        maxReceiveCount      = 3
    })
}

# --- apps/api on Lambda (container image) + API Gateway HTTP API ---

resource "aws_ecr_repository" "api" {
    name                 = "studymate-api"
    image_tag_mutability = "MUTABLE"

    force_delete = true
}

resource "aws_iam_role" "api_lambda" {
    name = "studymate-api-lambda"

    assume_role_policy = jsonencode({
        Version = "2012-10-17"
        Statement = [{
            Action = "sts:AssumeRole"
            Effect = "Allow"
            Principal = {
                Service = "lambda.amazonaws.com"
            }
        }]
    })
}

resource "aws_iam_role_policy_attachment" "api_lambda_basic_execution" {
    role       = aws_iam_role.api_lambda.name
    policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "api_lambda_permissions" {
    name = "studymate-api-lambda-permissions"
    role = aws_iam_role.api_lambda.id

    policy = jsonencode({
        Version = "2012-10-17"
        Statement = [
            {
                Effect   = "Allow"
                Action   = ["sqs:SendMessage"]
                Resource = [aws_sqs_queue.lectures.arn]
            },
            {
                Effect = "Allow"
                Action = [
                    "s3:PutObject",
                    "s3:GetObject",
                    "s3:DeleteObject",
                ]
                Resource = ["${aws_s3_bucket.lecture_audio.arn}/*"]
            },
        ]
    })
}

resource "aws_lambda_function" "api" {
    function_name = "studymate-api"
    role          = aws_iam_role.api_lambda.arn
    package_type  = "Image"
    image_uri     = "${aws_ecr_repository.api.repository_url}:${var.api_image_tag}"
    timeout       = 30
    memory_size   = 512

    environment {
        variables = {
            DATABASE_URL   = var.database_url
            S3_BUCKET      = var.bucket_name
            SQS_QUEUE_URL  = aws_sqs_queue.lectures.id
            AUTH_JWT_SECRET = var.auth_jwt_secret
        }
    }
}

resource "aws_apigatewayv2_api" "api" {
    name          = "studymate-api"
    protocol_type = "HTTP"

    cors_configuration {
        allow_origins     = ["http://localhost:5173", "https://web-pi-flax-71.vercel.app"]
        allow_methods     = ["*"]
        # Wildcard "*" is rejected by browsers here once allow_credentials is true -
        # has to be the actual header name(s) the frontend sends.
        allow_headers     = ["content-type"]
        allow_credentials = true
    }
}

resource "aws_apigatewayv2_integration" "api" {
    api_id                 = aws_apigatewayv2_api.api.id
    integration_type       = "AWS_PROXY"
    integration_uri        = aws_lambda_function.api.invoke_arn
    payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "api" {
    api_id    = aws_apigatewayv2_api.api.id
    route_key = "ANY /{proxy+}"
    target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_route" "api_root" {
    api_id    = aws_apigatewayv2_api.api.id
    route_key = "ANY /"
    target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "api" {
    api_id      = aws_apigatewayv2_api.api.id
    name        = "$default"
    auto_deploy = true

    default_route_settings {
        throttling_rate_limit  = 10
        throttling_burst_limit = 20
    }
}

resource "aws_lambda_permission" "api_gateway" {
    statement_id  = "AllowAPIGatewayInvoke"
    action        = "lambda:InvokeFunction"
    function_name = aws_lambda_function.api.function_name
    principal     = "apigateway.amazonaws.com"
    source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}

