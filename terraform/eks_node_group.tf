# --- IAM role EC2 instances assume when they join the cluster as nodes ---

resource "aws_iam_role" "eks_node" {
  name = "studymate-eks-node"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eks_node_worker" {
  role       = aws_iam_role.eks_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}

resource "aws_iam_role_policy_attachment" "eks_node_cni" {
  role       = aws_iam_role.eks_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
}

resource "aws_iam_role_policy_attachment" "eks_node_ecr" {
  role       = aws_iam_role.eks_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# EKS and Karpenter both discover subnets/security-groups by this tag - not
# optional metadata, Karpenter's EC2NodeClass selector in eks_addons.tf reads it.
resource "aws_ec2_tag" "subnet_cluster" {
  for_each    = toset(data.aws_subnets.default.ids)
  resource_id = each.value
  key         = "kubernetes.io/cluster/studymate"
  value       = "shared"
}

# Without this, aws_eks_node_group falls back to an EKS-auto-created
# security group (named "eks-cluster-sg-studymate-<hash>") instead of the
# one we manage in eks.tf - a completely separate SG from what Karpenter's
# EC2NodeClass explicitly selects for its own nodes. That split caused a
# real bug across two debugging sessions: cross-node pod traffic (including
# DNS to CoreDNS, and ALB health checks) worked fine to/from Karpenter nodes
# but was flaky/broken to/from this node group's nodes, because our
# self-referencing ingress rule (eks.tf) only ever applied to one of the
# two security groups actually in use. This launch template pins the node
# group to the exact same SG Karpenter nodes use.
resource "aws_launch_template" "eks_node_system" {
  name_prefix = "studymate-eks-node-system-"

  vpc_security_group_ids = [aws_security_group.eks_cluster.id]

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "studymate-eks-node-system" }
  }
}

resource "aws_eks_node_group" "system" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "studymate-system"
  node_role_arn   = aws_iam_role.eks_node.arn
  subnet_ids      = data.aws_subnets.default.ids

  launch_template {
    id      = aws_launch_template.eks_node_system.id
    version = aws_launch_template.eks_node_system.latest_version
  }

  # instance_types is set on the launch template's implicit defaults here
  # instead of this block, since specifying both a launch template AND
  # instance_types here is only valid if the launch template doesn't set
  # instance_type itself - simplest to keep it here, unset there.
  instance_types = ["t3.small"]
  capacity_type  = "ON_DEMAND"

  # This node group only ever runs CoreDNS, the ALB controller, Karpenter
  # itself, and KEDA's operator. Karpenter provisions everything else
  # on demand, so this never needs to scale beyond 2.
  scaling_config {
    min_size     = 1
    max_size     = 2
    desired_size = 1
  }

  labels = { role = "system" }

  depends_on = [
    aws_iam_role_policy_attachment.eks_node_worker,
    aws_iam_role_policy_attachment.eks_node_cni,
    aws_iam_role_policy_attachment.eks_node_ecr,
  ]
}
