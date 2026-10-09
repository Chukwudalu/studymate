# --- EKS's own OIDC provider - this is what makes IRSA work ---
#
# Same pattern as github_oidc.tf's provider for GitHub Actions: a Kubernetes
# ServiceAccount can "federate" into an AWS IAM role via OIDC, instead of
# every pod on the cluster sharing one node-wide IAM identity.

data "tls_certificate" "eks_oidc" {
  url = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "eks" {
  url             = aws_eks_cluster.main.identity[0].oidc[0].issuer
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.eks_oidc.certificates[0].sha1_fingerprint]
}

locals {
  eks_oidc_sub_prefix = replace(aws_iam_openid_connect_provider.eks.url, "https://", "")
}

# --- core-api: same S3 + SQS permissions api_lambda_permissions grants today ---

resource "aws_iam_role" "core_api_irsa" {
  name = "studymate-core-api-irsa"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.eks.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.eks_oidc_sub_prefix}:sub" = "system:serviceaccount:studymate:core-api"
          "${local.eks_oidc_sub_prefix}:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "core_api_irsa" {
  name = "studymate-core-api-irsa"
  role = aws_iam_role.core_api_irsa.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = [aws_sqs_queue.lectures.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]
        Resource = ["${aws_s3_bucket.lecture_audio.arn}/*"]
      },
    ]
  })
}

# --- worker: same permissions worker_task_permissions grants today ---

resource "aws_iam_role" "worker_irsa" {
  name = "studymate-worker-irsa"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.eks.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.eks_oidc_sub_prefix}:sub" = "system:serviceaccount:studymate:worker"
          "${local.eks_oidc_sub_prefix}:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "worker_irsa" {
  name = "studymate-worker-irsa"
  role = aws_iam_role.worker_irsa.id

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

# auth-service gets NO IAM role here at all - it only talks to Supabase
# Postgres over the internet via DATABASE_URL, no AWS API calls, so its
# ServiceAccount (in the Helm chart, later) has no IRSA annotation.

# --- KEDA operator: reads SQS depth to scale the worker Deployment ---

resource "aws_iam_role" "keda_irsa" {
  name = "studymate-keda-irsa"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.eks.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.eks_oidc_sub_prefix}:sub" = "system:serviceaccount:keda:keda-operator"
          "${local.eks_oidc_sub_prefix}:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "keda_irsa" {
  name = "studymate-keda-irsa"
  role = aws_iam_role.keda_irsa.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:GetQueueAttributes"]
      Resource = [aws_sqs_queue.lectures.arn]
    }]
  })
}

# --- AWS Load Balancer Controller: provisions/manages the ALB behind Ingress ---

resource "aws_iam_role" "alb_controller_irsa" {
  name = "studymate-alb-controller-irsa"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.eks.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.eks_oidc_sub_prefix}:sub" = "system:serviceaccount:kube-system:aws-load-balancer-controller"
          "${local.eks_oidc_sub_prefix}:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })
}

# Official AWS-maintained policy, downloaded verbatim from
# kubernetes-sigs/aws-load-balancer-controller - see terraform/policies/.
resource "aws_iam_role_policy" "alb_controller_irsa" {
  name   = "studymate-alb-controller-irsa"
  role   = aws_iam_role.alb_controller_irsa.id
  policy = file("${path.module}/policies/alb_controller_policy.json")
}

# --- Karpenter: provisions/terminates EC2 nodes on demand ---
#
# There's no clean standalone JSON for this one upstream - it ships baked
# into Karpenter's getting-started CloudFormation template. Translated to
# HCL below with Terraform interpolations in place of CFN's ${...} syntax.
# Source: aws/karpenter-provider-aws getting-started-with-karpenter/cloudformation.yaml

resource "aws_iam_role" "karpenter_controller_irsa" {
  name = "studymate-karpenter-controller-irsa"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.eks.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.eks_oidc_sub_prefix}:sub" = "system:serviceaccount:karpenter:karpenter"
          "${local.eks_oidc_sub_prefix}:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })
}

# Karpenter needs an SQS queue + EventBridge rules to hear about spot
# interruptions / scheduled maintenance / rebalance recommendations from AWS,
# so it can drain a node gracefully before it disappears. Even running
# on-demand only (as our NodePool does), scheduled-maintenance events still
# apply, so this stays wired up.
resource "aws_sqs_queue" "karpenter_interruption" {
  name                      = "studymate"
  message_retention_seconds = 300
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue_policy" "karpenter_interruption" {
  queue_url = aws_sqs_queue.karpenter_interruption.id

  policy = jsonencode({
    Version = "2012-10-17"
    Id      = "EC2InterruptionPolicy"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = ["events.amazonaws.com", "sqs.amazonaws.com"] }
        Action    = "sqs:SendMessage"
        Resource  = aws_sqs_queue.karpenter_interruption.arn
      },
      {
        Sid       = "DenyHTTP"
        Effect    = "Deny"
        Principal = "*"
        Action    = "sqs:*"
        Resource  = aws_sqs_queue.karpenter_interruption.arn
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      },
    ]
  })
}

resource "aws_cloudwatch_event_rule" "karpenter_scheduled_change" {
  name = "studymate-karpenter-scheduled-change"
  event_pattern = jsonencode({
    source      = ["aws.health"]
    detail-type = ["AWS Health Event"]
  })
}

resource "aws_cloudwatch_event_rule" "karpenter_spot_interruption" {
  name = "studymate-karpenter-spot-interruption"
  event_pattern = jsonencode({
    source      = ["aws.ec2"]
    detail-type = ["EC2 Spot Instance Interruption Warning"]
  })
}

resource "aws_cloudwatch_event_rule" "karpenter_rebalance" {
  name = "studymate-karpenter-rebalance"
  event_pattern = jsonencode({
    source      = ["aws.ec2"]
    detail-type = ["EC2 Instance Rebalance Recommendation"]
  })
}

resource "aws_cloudwatch_event_rule" "karpenter_instance_state_change" {
  name = "studymate-karpenter-instance-state-change"
  event_pattern = jsonencode({
    source      = ["aws.ec2"]
    detail-type = ["EC2 Instance State-change Notification"]
  })
}

resource "aws_cloudwatch_event_target" "karpenter_scheduled_change" {
  rule = aws_cloudwatch_event_rule.karpenter_scheduled_change.name
  arn  = aws_sqs_queue.karpenter_interruption.arn
}

resource "aws_cloudwatch_event_target" "karpenter_spot_interruption" {
  rule = aws_cloudwatch_event_rule.karpenter_spot_interruption.name
  arn  = aws_sqs_queue.karpenter_interruption.arn
}

resource "aws_cloudwatch_event_target" "karpenter_rebalance" {
  rule = aws_cloudwatch_event_rule.karpenter_rebalance.name
  arn  = aws_sqs_queue.karpenter_interruption.arn
}

resource "aws_cloudwatch_event_target" "karpenter_instance_state_change" {
  rule = aws_cloudwatch_event_rule.karpenter_instance_state_change.name
  arn  = aws_sqs_queue.karpenter_interruption.arn
}

resource "aws_iam_role_policy" "karpenter_controller_irsa" {
  name = "studymate-karpenter-controller-irsa"
  role = aws_iam_role.karpenter_controller_irsa.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowScopedEC2InstanceAccessActions"
        Effect = "Allow"
        Resource = [
          "arn:aws:ec2:${data.aws_region.current.name}::image/*",
          "arn:aws:ec2:${data.aws_region.current.name}::snapshot/*",
          "arn:aws:ec2:${data.aws_region.current.name}:*:security-group/*",
          "arn:aws:ec2:${data.aws_region.current.name}:*:subnet/*",
        ]
        Action = ["ec2:RunInstances", "ec2:CreateFleet"]
      },
      {
        Sid      = "AllowScopedEC2LaunchTemplateAccessActions"
        Effect   = "Allow"
        Resource = "arn:aws:ec2:${data.aws_region.current.name}:*:launch-template/*"
        Action   = ["ec2:RunInstances", "ec2:CreateFleet"]
        Condition = {
          StringEquals = { "aws:ResourceTag/kubernetes.io/cluster/studymate" = "owned" }
          StringLike   = { "aws:ResourceTag/karpenter.sh/nodepool" = "*" }
        }
      },
      {
        Sid    = "AllowScopedEC2InstanceActionsWithTags"
        Effect = "Allow"
        Resource = [
          "arn:aws:ec2:${data.aws_region.current.name}:*:fleet/*",
          "arn:aws:ec2:${data.aws_region.current.name}:*:instance/*",
          "arn:aws:ec2:${data.aws_region.current.name}:*:volume/*",
          "arn:aws:ec2:${data.aws_region.current.name}:*:network-interface/*",
          "arn:aws:ec2:${data.aws_region.current.name}:*:launch-template/*",
          "arn:aws:ec2:${data.aws_region.current.name}:*:spot-instances-request/*",
        ]
        Action = ["ec2:RunInstances", "ec2:CreateFleet", "ec2:CreateLaunchTemplate"]
        Condition = {
          StringEquals = {
            "aws:RequestTag/kubernetes.io/cluster/studymate" = "owned"
            "aws:RequestTag/eks:eks-cluster-name"             = "studymate"
          }
          StringLike = { "aws:RequestTag/karpenter.sh/nodepool" = "*" }
        }
      },
      {
        Sid    = "AllowScopedResourceCreationTagging"
        Effect = "Allow"
        Resource = [
          "arn:aws:ec2:${data.aws_region.current.name}:*:fleet/*",
          "arn:aws:ec2:${data.aws_region.current.name}:*:instance/*",
          "arn:aws:ec2:${data.aws_region.current.name}:*:volume/*",
          "arn:aws:ec2:${data.aws_region.current.name}:*:network-interface/*",
          "arn:aws:ec2:${data.aws_region.current.name}:*:launch-template/*",
          "arn:aws:ec2:${data.aws_region.current.name}:*:spot-instances-request/*",
        ]
        Action = "ec2:CreateTags"
        Condition = {
          StringEquals = {
            "aws:RequestTag/kubernetes.io/cluster/studymate" = "owned"
            "aws:RequestTag/eks:eks-cluster-name"             = "studymate"
            "ec2:CreateAction"                                = ["RunInstances", "CreateFleet", "CreateLaunchTemplate"]
          }
          StringLike = { "aws:RequestTag/karpenter.sh/nodepool" = "*" }
        }
      },
      {
        Sid      = "AllowScopedResourceTagging"
        Effect   = "Allow"
        Resource = "arn:aws:ec2:${data.aws_region.current.name}:*:instance/*"
        Action   = "ec2:CreateTags"
        Condition = {
          StringEquals              = { "aws:ResourceTag/kubernetes.io/cluster/studymate" = "owned" }
          StringLike                = { "aws:ResourceTag/karpenter.sh/nodepool" = "*" }
          StringEqualsIfExists      = { "aws:RequestTag/eks:eks-cluster-name" = "studymate" }
          "ForAllValues:StringEquals" = {
            "aws:TagKeys" = ["eks:eks-cluster-name", "karpenter.sh/nodeclaim", "Name"]
          }
        }
      },
      {
        Sid    = "AllowScopedDeletion"
        Effect = "Allow"
        Resource = [
          "arn:aws:ec2:${data.aws_region.current.name}:*:instance/*",
          "arn:aws:ec2:${data.aws_region.current.name}:*:launch-template/*",
        ]
        Action = ["ec2:TerminateInstances", "ec2:DeleteLaunchTemplate"]
        Condition = {
          StringEquals = { "aws:ResourceTag/kubernetes.io/cluster/studymate" = "owned" }
          StringLike   = { "aws:ResourceTag/karpenter.sh/nodepool" = "*" }
        }
      },
      {
        Sid      = "AllowRegionalReadActions"
        Effect   = "Allow"
        Resource = "*"
        Action = [
          "ec2:DescribeAvailabilityZones",
          "ec2:DescribeImages",
          "ec2:DescribeInstances",
          "ec2:DescribeInstanceTypeOfferings",
          "ec2:DescribeInstanceTypes",
          "ec2:DescribeLaunchTemplates",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSpotPriceHistory",
          "ec2:DescribeSubnets",
        ]
        Condition = {
          StringEquals = { "aws:RequestedRegion" = data.aws_region.current.name }
        }
      },
      {
        Sid      = "AllowSSMReadActions"
        Effect   = "Allow"
        Resource = "arn:aws:ssm:${data.aws_region.current.name}::parameter/aws/service/*"
        Action   = "ssm:GetParameter"
      },
      {
        Sid      = "AllowPricingReadActions"
        Effect   = "Allow"
        Resource = "*"
        Action   = "pricing:GetProducts"
      },
      {
        Sid      = "AllowInterruptionQueueActions"
        Effect   = "Allow"
        Resource = aws_sqs_queue.karpenter_interruption.arn
        Action   = ["sqs:DeleteMessage", "sqs:GetQueueUrl", "sqs:ReceiveMessage"]
      },
      {
        Sid      = "AllowPassingInstanceRole"
        Effect   = "Allow"
        Resource = aws_iam_role.eks_node.arn
        Action   = "iam:PassRole"
        Condition = {
          StringEquals = { "iam:PassedToService" = "ec2.amazonaws.com" }
        }
      },
      {
        Sid      = "AllowScopedInstanceProfileCreationActions"
        Effect   = "Allow"
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/*"
        Action   = "iam:CreateInstanceProfile"
        Condition = {
          StringEquals = {
            "aws:RequestTag/kubernetes.io/cluster/studymate" = "owned"
            "aws:RequestTag/eks:eks-cluster-name"             = "studymate"
            "aws:RequestTag/topology.kubernetes.io/region"    = data.aws_region.current.name
          }
          StringLike = { "aws:RequestTag/karpenter.k8s.aws/ec2nodeclass" = "*" }
        }
      },
      {
        Sid      = "AllowScopedInstanceProfileTagActions"
        Effect   = "Allow"
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/*"
        Action   = "iam:TagInstanceProfile"
        Condition = {
          StringEquals = {
            "aws:ResourceTag/kubernetes.io/cluster/studymate" = "owned"
            "aws:ResourceTag/topology.kubernetes.io/region"   = data.aws_region.current.name
            "aws:RequestTag/kubernetes.io/cluster/studymate"  = "owned"
            "aws:RequestTag/eks:eks-cluster-name"              = "studymate"
            "aws:RequestTag/topology.kubernetes.io/region"     = data.aws_region.current.name
          }
          StringLike = {
            "aws:ResourceTag/karpenter.k8s.aws/ec2nodeclass" = "*"
            "aws:RequestTag/karpenter.k8s.aws/ec2nodeclass"  = "*"
          }
        }
      },
      {
        Sid      = "AllowScopedInstanceProfileActions"
        Effect   = "Allow"
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/*"
        Action   = ["iam:AddRoleToInstanceProfile", "iam:RemoveRoleFromInstanceProfile", "iam:DeleteInstanceProfile"]
        Condition = {
          StringEquals = {
            "aws:ResourceTag/kubernetes.io/cluster/studymate" = "owned"
            "aws:ResourceTag/topology.kubernetes.io/region"   = data.aws_region.current.name
          }
          StringLike = { "aws:ResourceTag/karpenter.k8s.aws/ec2nodeclass" = "*" }
        }
      },
      {
        Sid      = "AllowInstanceProfileReadActions"
        Effect   = "Allow"
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/*"
        Action   = "iam:GetInstanceProfile"
      },
      {
        Sid      = "AllowAPIServerEndpointDiscovery"
        Effect   = "Allow"
        Resource = aws_eks_cluster.main.arn
        Action   = "eks:DescribeCluster"
      },
    ]
  })
}
