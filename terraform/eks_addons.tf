# --- helm/kubernetes providers, pointed at the cluster we just created ---
#
# `exec` calls `aws eks get-token` at apply-time instead of a static
# credential - same OIDC-assumed-role pattern used everywhere else in this
# repo, just reused for cluster auth instead of AWS API auth.

provider "kubernetes" {
  host                   = aws_eks_cluster.main.endpoint
  cluster_ca_certificate = base64decode(aws_eks_cluster.main.certificate_authority[0].data)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", aws_eks_cluster.main.name]
  }
}

provider "helm" {
  kubernetes {
    host                   = aws_eks_cluster.main.endpoint
    cluster_ca_certificate = base64decode(aws_eks_cluster.main.certificate_authority[0].data)
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", aws_eks_cluster.main.name]
    }
  }
}

# Namespace is managed here (admin/Terraform access), not by the app's own
# Helm chart or by CI - Namespace is a cluster-scoped resource kind, and
# the CI role's access policy (github_oidc.tf) is deliberately scoped to
# edit permissions *within* the studymate namespace only. A namespace-scoped
# RBAC binding can never grant permission on a cluster-scoped resource kind,
# regardless of policy content - so CI creating/managing its own namespace
# is a contradiction. This resource is the one-time, infra-level exception.
resource "kubernetes_namespace" "studymate" {
  metadata {
    name = "studymate"
    annotations = {
      # Belt-and-suspenders alongside this resource simply not being in the
      # Helm chart at all: if a release's stored history ever still
      # remembers a namespace.yaml from an older revision, this stops Helm's
      # prune-on-upgrade from deleting the namespace (and cascading through
      # everything in it) on the next `helm upgrade`.
      "helm.sh/resource-policy" = "keep"
    }
  }

  # aws_eks_access_entry.terraform_admin: same reasoning as the helm_release
  # resources below - without this, a `terraform destroy` can revoke
  # Terraform's own cluster access (by destroying the access entry) before
  # getting to this resource, which then fails with "Unauthorized." Learned
  # the hard way: this resource was added after the helm_release fix below
  # and didn't get the same protection the first time.
  depends_on = [aws_eks_node_group.system, aws_eks_access_entry.terraform_admin]
}

# Pre-created so the node security group can reference its ID deterministically
# (the Ingress annotation `alb.ingress.kubernetes.io/security-groups` points
# at this, in Phase 2's Helm chart - not used yet).
resource "aws_security_group" "alb" {
  name        = "studymate-alb"
  description = "Studymate ALB - internet-facing ingress"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Lets the ALB actually reach pods on the node - without this, the ALB
# controller can create the load balancer but every health check fails.
resource "aws_security_group_rule" "nodes_from_alb" {
  type                     = "ingress"
  from_port                = 0
  to_port                  = 65535
  protocol                 = "tcp"
  security_group_id        = aws_security_group.eks_cluster.id
  source_security_group_id = aws_security_group.alb.id
}

resource "helm_release" "aws_load_balancer_controller" {
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  namespace  = "kube-system"

  set {
    name  = "clusterName"
    value = aws_eks_cluster.main.name
  }

  set {
    name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
    value = aws_iam_role.alb_controller_irsa.arn
  }

  # Without this, the controller falls back to discovering its VPC ID via
  # EC2 instance metadata (IMDS) from inside the pod - which times out here
  # because pod network sits one hop further from the host than IMDS's
  # default hop-limit allows. Setting it directly skips that lookup entirely.
  set {
    name  = "vpcId"
    value = data.aws_vpc.default.id
  }

  # aws_eks_access_entry.terraform_admin: not a functional dependency, but
  # Terraform can't see that this resource needs the cluster to still be
  # reachable during *destroy* too - without this, a `terraform destroy` can
  # revoke Terraform's own cluster access (by destroying the access entry)
  # before getting to this resource, which then fails with "the server has
  # asked for the client to provide credentials." This forces correct
  # ordering in both directions.
  depends_on = [aws_eks_node_group.system, aws_eks_access_entry.terraform_admin]
}

resource "helm_release" "karpenter" {
  name             = "karpenter"
  repository       = "oci://public.ecr.aws/karpenter"
  chart            = "karpenter"
  namespace        = "karpenter"
  create_namespace = true

  set {
    name  = "settings.clusterName"
    value = aws_eks_cluster.main.name
  }

  set {
    name  = "settings.interruptionQueue"
    value = aws_sqs_queue.karpenter_interruption.name
  }

  set {
    name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
    value = aws_iam_role.karpenter_controller_irsa.arn
  }

  depends_on = [aws_eks_node_group.system, aws_eks_access_entry.terraform_admin]
}

resource "helm_release" "keda" {
  name             = "keda"
  repository       = "https://kedacore.github.io/charts"
  chart            = "keda"
  namespace        = "keda"
  create_namespace = true

  set {
    name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
    value = aws_iam_role.keda_irsa.arn
  }

  # aws_eks_node_group.system: needs somewhere to schedule onto.
  # helm_release.aws_load_balancer_controller: not because KEDA needs it
  # functionally, but because KEDA's own Service object creation gets
  # intercepted by the ALB controller's cluster-wide admission webhook,
  # which returns "no endpoints available" if that controller isn't
  # actually serving yet. This forces KEDA's install to wait until the
  # controller is confirmed Running, not just "helm_release resource created."
  depends_on = [
    aws_eks_node_group.system,
    helm_release.aws_load_balancer_controller,
    aws_eks_access_entry.terraform_admin,
  ]
}

# Karpenter's own CRDs (EC2NodeClass/NodePool) live in eks_karpenter_crds.tf,
# applied in a second `terraform apply` pass once the cluster actually exists -
# see the migration notes for why they can't be in this file's first apply.
