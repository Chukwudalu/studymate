# --- apps/worker on ECS Fargate, scaled to zero via SQS queue depth ---

data "aws_vpc" "default" {
    default = true
}

data "aws_subnets" "default" {
    filter {
        name   = "vpc-id"
        values = [data.aws_vpc.default.id]
    }
}

resource "aws_security_group" "worker" {
    name        = "studymate-worker"
    description = "Outbound-only SG for the studymate worker Fargate task"
    vpc_id      = data.aws_vpc.default.id

    egress {
        from_port   = 0
        to_port     = 0
        protocol    = "-1"
        cidr_blocks = ["0.0.0.0/0"]
    }
}

resource "aws_ecr_repository" "worker" {
    name                 = "studymate-worker"
    image_tag_mutability = "MUTABLE"
    force_delete         = true
}

resource "aws_iam_role" "worker_execution" {
    name = "studymate-worker-execution"

    assume_role_policy = jsonencode({
        Version = "2012-10-17"
        Statement = [{
            Action    = "sts:AssumeRole"
            Effect    = "Allow"
            Principal = { Service = "ecs-tasks.amazonaws.com" }
        }]
    })
}

resource "aws_iam_role_policy_attachment" "worker_execution" {
    role       = aws_iam_role.worker_execution.name
    policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "worker_task" {
    name = "studymate-worker-task"

    assume_role_policy = jsonencode({
        Version = "2012-10-17"
        Statement = [{
            Action    = "sts:AssumeRole"
            Effect    = "Allow"
            Principal = { Service = "ecs-tasks.amazonaws.com" }
        }]
    })
}

resource "aws_iam_role_policy" "worker_task_permissions" {
    name = "studymate-worker-task-permissions"
    role = aws_iam_role.worker_task.id

    policy = jsonencode({
        Version = "2012-10-17"
        Statement = [
            {
                Effect = "Allow"
                Action = [
                    "sqs:ReceiveMessage",
                    "sqs:DeleteMessage",
                    "sqs:ChangeMessageVisibility",
                    "sqs:GetQueueAttributes",
                ]
                Resource = [aws_sqs_queue.lectures.arn]
            },
            {
                Effect   = "Allow"
                Action   = ["s3:GetObject"]
                Resource = ["${aws_s3_bucket.lecture_audio.arn}/*"]
            },
        ]
    })
}

resource "aws_cloudwatch_log_group" "worker" {
    name              = "/ecs/studymate-worker"
    retention_in_days = 14
}

resource "aws_ecs_cluster" "main" {
    name = "studymate"
}

resource "aws_ecs_task_definition" "worker" {
    family                   = "studymate-worker"
    requires_compatibilities = ["FARGATE"]
    network_mode             = "awsvpc"
    cpu                      = "512"
    memory                   = "1024"
    execution_role_arn       = aws_iam_role.worker_execution.arn
    task_role_arn             = aws_iam_role.worker_task.arn

    container_definitions = jsonencode([
        {
            name  = "worker"
            image = "${aws_ecr_repository.worker.repository_url}:${var.worker_image_tag}"
            environment = [
                { name = "DATABASE_URL", value = var.database_url },
                { name = "S3_BUCKET", value = var.bucket_name },
                { name = "SQS_QUEUE_URL", value = aws_sqs_queue.lectures.id },
                { name = "OPENAI_API_KEY", value = var.openai_api_key },
                { name = "ANTHROPIC_API_KEY", value = var.anthropic_api_key },
            ]
            logConfiguration = {
                logDriver = "awslogs"
                options = {
                    "awslogs-group"         = aws_cloudwatch_log_group.worker.name
                    "awslogs-region"        = var.aws_region
                    "awslogs-stream-prefix" = "worker"
                }
            }
        }
    ])
}

resource "aws_ecs_service" "worker" {
    name            = "studymate-worker"
    cluster         = aws_ecs_cluster.main.id
    task_definition = aws_ecs_task_definition.worker.arn
    desired_count   = 0
    launch_type     = "FARGATE"

    network_configuration {
        subnets          = data.aws_subnets.default.ids
        security_groups  = [aws_security_group.worker.id]
        assign_public_ip = true
    }

    # desired_count is driven by Application Auto Scaling (see below), not Terraform
    lifecycle {
        ignore_changes = [desired_count]
    }
}

# --- scale-to-zero: 0 <-> 1 tasks based on SQS queue depth ---

resource "aws_appautoscaling_target" "worker" {
    min_capacity       = 0
    max_capacity       = 1
    resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.worker.name}"
    scalable_dimension = "ecs:service:DesiredCount"
    service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "worker_scale_out" {
    name               = "studymate-worker-scale-out"
    policy_type        = "StepScaling"
    resource_id        = aws_appautoscaling_target.worker.resource_id
    scalable_dimension = aws_appautoscaling_target.worker.scalable_dimension
    service_namespace  = aws_appautoscaling_target.worker.service_namespace

    step_scaling_policy_configuration {
        adjustment_type         = "ExactCapacity"
        cooldown                = 60
        metric_aggregation_type = "Maximum"

        step_adjustment {
            metric_interval_lower_bound = 0
            scaling_adjustment          = 1
        }
    }
}

resource "aws_appautoscaling_policy" "worker_scale_in" {
    name               = "studymate-worker-scale-in"
    policy_type        = "StepScaling"
    resource_id        = aws_appautoscaling_target.worker.resource_id
    scalable_dimension = aws_appautoscaling_target.worker.scalable_dimension
    service_namespace  = aws_appautoscaling_target.worker.service_namespace

    step_scaling_policy_configuration {
        adjustment_type         = "ExactCapacity"
        cooldown                = 60
        metric_aggregation_type = "Maximum"

        step_adjustment {
            metric_interval_upper_bound = 0
            scaling_adjustment          = 0
        }
    }
}

resource "aws_cloudwatch_metric_alarm" "worker_scale_out" {
    alarm_name          = "studymate-worker-scale-out"
    comparison_operator = "GreaterThanThreshold"
    evaluation_periods  = 1
    threshold           = 0
    alarm_actions       = [aws_appautoscaling_policy.worker_scale_out.arn]

    metric_name = "ApproximateNumberOfMessagesVisible"
    namespace   = "AWS/SQS"
    period      = 60
    statistic   = "Maximum"

    dimensions = {
        QueueName = aws_sqs_queue.lectures.name
    }
}

# Scale-in only fires when the queue has nothing visible AND nothing currently
# in flight (being processed) - guards against killing a task mid-job, since
# a message being worked on is "not visible" but the queue can still look
# empty from the visible-count alone.
resource "aws_cloudwatch_metric_alarm" "worker_scale_in" {
    alarm_name          = "studymate-worker-scale-in"
    comparison_operator = "LessThanOrEqualToThreshold"
    threshold            = 0
    evaluation_periods   = 3
    datapoints_to_alarm  = 3
    alarm_actions        = [aws_appautoscaling_policy.worker_scale_in.arn]

    metric_query {
        id          = "total_messages"
        expression  = "visible + not_visible"
        label       = "TotalMessages"
        return_data = true
    }

    metric_query {
        id = "visible"
        metric {
            metric_name = "ApproximateNumberOfMessagesVisible"
            namespace   = "AWS/SQS"
            period      = 60
            stat        = "Maximum"
            dimensions = {
                QueueName = aws_sqs_queue.lectures.name
            }
        }
    }

    metric_query {
        id = "not_visible"
        metric {
            metric_name = "ApproximateNumberOfMessagesNotVisible"
            namespace   = "AWS/SQS"
            period      = 60
            stat        = "Maximum"
            dimensions = {
                QueueName = aws_sqs_queue.lectures.name
            }
        }
    }
}
