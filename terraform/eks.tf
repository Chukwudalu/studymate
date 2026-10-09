data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# --- EKS control plane ---

resource "aws_iam_role" "eks_cluster" {
  name = "studymate-eks-cluster"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eks_cluster_policy" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_security_group" "eks_cluster" {
  name        = "studymate-eks-cluster"
  description = "EKS control plane to node communication"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Both the control plane's own ENIs and every node share this one security
# group. Without a self-referencing ingress rule, the control plane can't
# reach kubelet on the nodes (port 10250 - needed for `kubectl logs`/`exec`,
# metrics, webhooks) and nodes can't reach each other for cluster networking -
# this is what caused the VPC CNI to fail to come up on a Karpenter-launched
# node during Phase 0 verification.
# protocol = "-1" (all protocols), not just "tcp" - the original TCP-only
# version of this rule caused a real bug during Phase 2 verification: DNS
# (UDP/53) between pods on different nodes failed cluster-wide, because
# CoreDNS's UDP traffic wasn't covered by the TCP-only rule. Discovered by
# every pod on one node being unable to resolve any DNS name, cluster-internal
# or external, while same-node/local traffic worked fine.
resource "aws_security_group_rule" "eks_cluster_self_ingress" {
  type                     = "ingress"
  from_port                = 0
  to_port                  = 65535
  protocol                 = "-1"
  security_group_id        = aws_security_group.eks_cluster.id
  source_security_group_id = aws_security_group.eks_cluster.id
}

resource "aws_eks_cluster" "main" {
  name     = "studymate"
  role_arn = aws_iam_role.eks_cluster.arn
  version  = "1.31"

  vpc_config {
    subnet_ids               = data.aws_subnets.default.ids
    security_group_ids       = [aws_security_group.eks_cluster.id]
    endpoint_public_access    = true
    # No NAT gateway in this VPC, so there's nowhere for a private-only
    # endpoint to route from - public access is a deliberate trade-off here,
    # not an oversight. See the migration plan's VPC section.
    endpoint_private_access  = false
  }

  access_config {
    # "API" = EKS Access Entries, the modern replacement for hand-editing the
    # aws-auth ConfigMap. Every IAM principal that needs kubectl/helm access
    # gets an explicit access entry below instead.
    authentication_mode = "API"
  }

  depends_on = [aws_iam_role_policy_attachment.eks_cluster_policy]
}

# Whoever runs `terraform apply` needs cluster-admin to bootstrap everything
# else in eks_addons.tf (helm releases, Karpenter CRDs). CI gets a much
# narrower access entry later, in github_oidc.tf.
resource "aws_eks_access_entry" "terraform_admin" {
  cluster_name  = aws_eks_cluster.main.name
  principal_arn = data.aws_caller_identity.current.arn
}

resource "aws_eks_access_policy_association" "terraform_admin" {
  cluster_name  = aws_eks_cluster.main.name
  principal_arn = data.aws_caller_identity.current.arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }
}
