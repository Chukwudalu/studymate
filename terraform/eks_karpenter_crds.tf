# --- Karpenter's own CRDs: the actual node-provisioning policy ---
#
# Split into its own file with a .disabled extension deliberately: the
# `kubernetes_manifest` resource type needs a working REST client to the
# cluster even at plan time, which doesn't exist yet on the same apply that
# creates the cluster itself. Rename this file to eks_karpenter_crds.tf
# (dropping .disabled) AFTER the first `terraform apply` succeeds, then run
# `terraform apply` again to pick these up.

resource "kubernetes_manifest" "karpenter_node_class" {
  manifest = {
    apiVersion = "karpenter.k8s.aws/v1"
    kind       = "EC2NodeClass"
    metadata   = { name = "default" }
    spec = {
      role = aws_iam_role.eks_node.name
      # Karpenter 1.x requires explicit AMI selection - amiFamily alone no
      # longer auto-selects one. The alias shorthand resolves to the latest
      # AL2023 AMI for this cluster's Kubernetes version via SSM, same AMI
      # source the managed node group itself uses.
      amiSelectorTerms = [
        { alias = "al2023@latest" }
      ]
      subnetSelectorTerms = [
        { tags = { "kubernetes.io/cluster/studymate" = "shared" } }
      ]
      securityGroupSelectorTerms = [
        { id = aws_security_group.eks_cluster.id }
      ]
    }
  }

  depends_on = [helm_release.karpenter]
}

resource "kubernetes_manifest" "karpenter_node_pool" {
  manifest = {
    apiVersion = "karpenter.sh/v1"
    kind       = "NodePool"
    metadata   = { name = "default" }
    spec = {
      template = {
        spec = {
          nodeClassRef = {
            group = "karpenter.k8s.aws"
            kind  = "EC2NodeClass"
            name  = "default"
          }
          requirements = [
            { key = "karpenter.sh/capacity-type", operator = "In", values = ["on-demand"] },
            { key = "node.kubernetes.io/instance-type", operator = "In", values = ["t3.medium", "t3.large"] },
          ]
        }
      }
      limits = { cpu = "8" }
      disruption = {
        consolidationPolicy = "WhenEmptyOrUnderutilized"
        # Required explicitly in this Karpenter version (1.14.1) - how long
        # a node must sit empty/underutilized before Karpenter consolidates
        # it away. 30s is Karpenter's own documented default value; older
        # versions applied it implicitly, this one validates it's present.
        consolidateAfter = "30s"
      }
    }
  }

  depends_on = [helm_release.karpenter]
}
