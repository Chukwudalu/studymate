# Default VPC, reused by the EKS cluster and node groups (no new VPC - see
# docs/eks-migration/HANDOFF.md, decision 5).

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}
