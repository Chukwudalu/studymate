# Phase 5 - Decommission the Lambda / ECS stack

**Goal:** remove the old compute path (Lambda + API Gateway + the ECS Fargate
worker) now that everything runs on EKS, leaving EKS as the single way the app
runs.

**Result:** done. One reviewed `terraform plan` -> `0 to add, 1 to change,
25 to destroy`, applied, followed by `terraform plan` -> *No changes* and a live
smoke test (API health 200, signup + subjects through Vercel).

---

## Part 1 - Why this was done carefully

Deleting infrastructure is the one step in the migration that can't be walked
back by re-running a pipeline. The rules followed:
1. **Plan first, read every line, then apply.** The plan was saved to a file and
   *that exact plan* was applied (`terraform apply <planfile>`), so nothing
   could change between review and apply.
2. **Check what the plan does NOT touch** as much as what it does. The things
   that must never appear: EKS, node groups, Karpenter, KEDA, the ALB and its
   cert, S3, SQS, the three EKS ECR repos.
3. **Prove the app still works** immediately afterwards, not later.

---

## Part 2 - What was removed

| Group | Resources |
|---|---|
| Lambda | `aws_lambda_function.api`, `aws_lambda_permission.api_gateway`, role `api_lambda` + its policy and basic-execution attachment |
| API Gateway | `aws_apigatewayv2_api / integration / stage` and 2 routes |
| ECS worker | cluster, service, task definition, log group, execution + task roles and policies, ECS-only security group |
| Autoscaling | `aws_appautoscaling_target`, scale-in/out policies, 2 CloudWatch alarms |
| ECR | the `studymate-api` repository |

One resource was **changed**, not destroyed: the CI role's IAM policy
(`github_actions_deploy`). The Lambda-update, ECS-update and `iam:PassRole`
statements came out, leaving only what the EKS pipeline needs (ECR push,
`eks:DescribeCluster`). That is least privilege tightening for free.

Repo cleanup: `apps/api/` (the Lambda monolith), `Dockerfile.api`, and the
now-unused Terraform variables (`database_url`, `auth_jwt_secret`,
`openai_api_key`, `anthropic_api_key`, `api_image_tag`, `worker_image_tag`).
**Side benefit:** Terraform no longer needs any application secrets at all - they
live in GitHub Actions secrets and the Kubernetes Secret only.

---

## Part 3 - The tricky part: shared resources in a "mixed" file

`worker.tf` held the ECS worker, but also two things EKS depends on:
- `data.aws_vpc.default` / `data.aws_subnets.default` - used by `eks.tf`,
  `eks_node_group.tf` and `eks_addons.tf`;
- `aws_ecr_repository.worker` - the **EKS worker image lives in this repo**; it
  was only named "worker" because ECS got there first.

Deleting the file wholesale would have destroyed the VPC lookups' consumers and
the worker's image repository. Approach:
1. Search for every reference (`grep` for each resource address) before touching
   anything - that's how the dependencies on `worker.tf` were found.
2. Move the shared blocks to `network.tf` and `main.tf`, delete `worker.tf`.
3. `terraform validate`, then `terraform plan`: shared resources showing **no
   diff** proves the move was safe.

Key concept: **a Terraform resource's identity is its address
(`aws_ecr_repository.worker`), not the file it lives in.** Moving a block between
`.tf` files changes nothing in state.

---

## Part 4 - Operational notes

- The ECS autoscaling target had been capped at 0 earlier as a stop-gap so the
  old worker couldn't steal queue messages from the EKS worker (see Phase 4,
  problem 5). Phase 5 removes the cause outright.
- `terraform fmt` also reformatted `eks.tf`; harmless whitespace.
- The next rebuild is shorter: **3 images** to push (`worker`, `auth-service`,
  `core-api`), no Lambda/ECS to create, and no image-push race for the Lambda.
- `terraform/terraform.tfvars` may still hold the old secret values; they're no
  longer read and can be deleted (the `.env` file keeps them for local use).

---

## Part 5 - Verification checklist

```
terraform plan                                  # No changes
curl https://api.steeze.ca/healthz              # 200
POST https://<frontend>/auth/signup             # 200   (full path: Vercel -> ALB -> pod -> DB)
GET  https://<frontend>/subjects                # 200
aws lambda list-functions / aws ecs list-clusters   # no studymate resources
```
