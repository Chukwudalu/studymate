# StudyMate → EKS Migration: Handoff / Session Continuity Doc

**Read this first if you're a new Claude session picking this up.** It
tells you what's been done, what's verified, what's currently running in
AWS, and exactly what's left. The full narrative detail (concepts, every
bug hit and how it was diagnosed) lives in the per-phase docs in this same
directory — read those when you need depth, use this doc for orientation.

## The project, in one paragraph

StudyMate is a small app (FastAPI backend, React frontend on Vercel,
Supabase Postgres) currently running on AWS Lambda (API) + ECS Fargate
(worker) + API Gateway, provisioned by Terraform. We're migrating it to
Kubernetes on EKS, split into 3 microservices (`auth-service`, `core-api`,
`worker`), as a learning/portfolio exercise in Docker, Kubernetes,
Terraform, and CI/CD — done properly, not as a toy. **Full replacement**
is the goal: Lambda/API Gateway/ECS get deleted once the EKS path is
verified end-to-end and cut over. Supabase, S3, and SQS stay as-is — only
compute moves.

The full original plan (still accurate) is at
`/home/jeremiah/.claude/plans/zany-dancing-bunny.md`.

## Decisions already made — do not re-litigate these

1. Full replacement of Lambda/ECS, not permanent side-by-side.
2. 3 services: `auth-service` (signup/login/reset/logout/me, owns no AWS
   IAM — only talks to Supabase), `core-api` (lecture CRUD, presign, chat,
   enqueue — S3+SQS via IRSA), `worker` (SQS consumer + LangGraph
   pipelines — S3+SQS via IRSA, scales 0→3 via KEDA).
3. CI/CD: GitHub Actions runs `helm upgrade` directly (push-based), not
   ArgoCD/GitOps. Deferred as a future upgrade, not designed.
4. Compute: EKS managed node group (1 always-on `t3.small` for system
   pods) + Karpenter for elastic capacity beyond that. Not Fargate.
5. No new VPC — reuses the existing default VPC. Documented trade-off
   (public subnets, no NAT), not an oversight.
6. Database stays single/shared (both new services point at the same
   Supabase `DATABASE_URL`) — *not* database-per-service. Deliberately
   out of scope for this exercise; see Phase 1 doc for the reasoning.
7. Secrets: plain Kubernetes `Secret`, applied by CI from GitHub encrypted
   secrets. Not AWS Secrets Manager / External Secrets Operator — judged
   as unneeded complexity at this scale.

## Status by phase

| Phase | What it is | Status |
|---|---|---|
| 0 | EKS cluster, Karpenter, KEDA, ALB controller | ✅ Done, verified, documented |
| 1 | Split `apps/api` → `auth-service` + `core-api` | ✅ Done, verified, documented |
| 2 | Helm charts, deploy to real cluster, real ALB | ✅ Done, verified, documented |
| 3 | Wire GitHub Actions CI/CD | ✅ Code done; **live CI run not yet verified** (needs GitHub secrets — see below) |
| 4 | Cutover: HTTPS/ACM, point frontend at ALB | ⬜ Not started |
| 5 | Decommission Lambda/API Gateway/ECS | ⬜ Not started (the one genuinely destructive step — do it deliberately, reviewed, on its own) |

Read `docs/eks-migration/phase-0-cluster-bootstrap.md`,
`phase-1-service-split.md`, `phase-2-helm-deploy.md`, `phase-3-cicd.md` for
full detail on each. They're written to actually teach the concepts, not
just log commands — worth reading in order if you're studying this, not
just executing it.

## Current live AWS state (as of last check)

**Everything is currently TORN DOWN.** Confirmed: `terraform state list`
returns empty (0 resources), nothing billing. This was a deliberate
end-of-session teardown, not a crash. Verify this is still true before
doing anything else, in case time has passed since:

```bash
cd terraform && terraform state list | wc -l   # should be 0 if torn down, ~90 if up
aws eks describe-cluster --name studymate --region us-west-2 --query 'cluster.status' 2>&1
```

**Your first real action in a new session should be rebuilding** (see
"How to rebuild from zero" below) — it's a known, fast, mostly-clean
process now; every bug hit across Phases 0-3 is fixed in the Terraform/Helm
code itself, not just patched live. Expect roughly 15-20 minutes end to
end (EKS cluster creation is the slow part, ~10-15 min alone).

### Kubeconfig — important

**Never run `aws eks update-kubeconfig` without `--kubeconfig
/tmp/studymate-kubeconfig`.** The user has a separate local Kubernetes
project (`kind-grade-sub-cluster` context) and an earlier session
accidentally overwrote their default `~/.kube/config` current-context,
which was confusing and had to be fixed. Always:

```bash
export KUBECONFIG=/tmp/studymate-kubeconfig
aws eks update-kubeconfig --name studymate --region us-west-2 --kubeconfig /tmp/studymate-kubeconfig
```

### Helm

Not installed system-wide (no sudo available in this environment).
Installed to `~/.local/bin/helm` — always `export PATH="$HOME/.local/bin:$PATH"`
before using it, or call it by full path.

## What's verified to actually work (via real tests, not just "applied without error")

- Karpenter scale-up/scale-down: an oversized test pod triggered a real
  EC2 node launch and termination.
- Full user flow over the real ALB (HTTP, no domain — raw ELB hostname):
  signup on `auth-service` → cookie accepted by `core-api` (proves
  cross-service auth works) → S3 presign → SQS enqueue → KEDA scales
  `worker` 0→1 → worker processes the job (real S3 call via IRSA, correct
  403 since no real audio was uploaded, correctly written back to
  Postgres as a failure) → KEDA scales back to 0.
- All 51 pytest tests pass against the new `auth_service`/`core_api`
  modules.
- Terraform's own IAM/access-entry setup for CI confirmed correct
  (`aws eks list-associated-access-policies`), but **the actual GitHub
  Actions workflow has never run for real** — see Phase 3 doc, "What's
  still unverified."

## Real bugs fixed along the way (don't reintroduce these)

These are all now fixed *in the Terraform/Helm code itself*, not just
patched live — but worth knowing about if something looks newly broken:

1. **EKS managed node group vs. Karpenter nodes used different security
   groups.** The single biggest bug of the whole migration — spanned two
   debugging sessions. `aws_eks_node_group` without an explicit launch
   template silently uses an EKS-auto-created SG, not the one Terraform
   manages. Fixed via `aws_launch_template.eks_node_system` in
   `terraform/eks_node_group.tf`, pinning it to
   `aws_security_group.eks_cluster`. If you ever see "works for one pod,
   not another, no clear pattern" again — check this first.
2. Security group self-ingress rule needs `protocol = "-1"`, not `"tcp"` —
   DNS runs over UDP, and a TCP-only rule breaks cross-node DNS silently
   (pods stay `Running`, no CNI errors logged, just "temporary failure in
   name resolution").
3. ALB controller needs `vpcId` passed explicitly as a Helm value, or it
   tries (and fails) to discover it via EC2 instance metadata from inside
   the pod.
4. ALB Ingress needs `alb.ingress.kubernetes.io/healthcheck-path:
   /healthz` — the default `/` health check path isn't a real route on
   either app.
5. `kubernetes_manifest`/`helm_release` Terraform resources need explicit
   `depends_on` for anything they implicitly depend on inside the cluster
   (e.g. KEDA depending on the ALB controller's webhook being live) —
   Terraform's dependency graph can't see intra-cluster dependencies on
   its own.
6. Namespace is Terraform-managed (`kubernetes_namespace.studymate`), not
   part of the Helm chart or CI — a namespace-scoped RBAC binding can
   never create a cluster-scoped `Namespace` object. See Phase 3 doc.
7. **Karpenter-provisioned EC2 instances are NOT cleaned up by
   `terraform destroy`** unless Karpenter's own controller is still alive
   to react — removing `helm_release.karpenter` from state before the
   cluster is destroyed orphans any nodes Karpenter had provisioned.
   Same for the ALB the AWS Load Balancer Controller creates. **Always
   tear down in this order**: delete workloads/NodeClaims via `kubectl`
   first (or at minimum, know you'll need to manually
   `aws ec2 terminate-instances` / `aws elbv2 delete-load-balancer` any
   orphans afterward) — this was not done cleanly in past teardowns and
   cost significant time both times.
8. ECR repos have `force_delete = true` — every fresh `terraform apply`
   after a `destroy` needs images re-pushed *before* Lambda/ECS/anything
   referencing `:latest` will succeed. Always push all 4 images
   (`api`, `worker`, `auth-service`, `core-api`) right after `terraform
   apply` creates the ECR repos, ideally before it reaches the resources
   that reference them.
9. Docker builds need `--provenance=false --sbom=false` or Lambda
   rejects the resulting OCI manifest-list image format.
10. `kubernetes_namespace.studymate` (added in Phase 3) hit the exact same
    "Unauthorized" failure as bug 7's `helm_release`/`kubernetes_manifest`
    resources during a teardown — it was added later and didn't get the
    same `depends_on = [..., aws_eks_access_entry.terraform_admin]`
    protection the first time. Now fixed in `eks_addons.tf`. General
    rule: **any `kubernetes_*`/`helm_release` Terraform resource needs
    this `depends_on`**, or a `terraform destroy` can revoke Terraform's
    own cluster access before reaching it.

## How to rebuild from zero (if torn down)

This is now a known, mostly-clean sequence (all bugs above are pre-fixed
in the code):

```bash
cd terraform
mv eks_karpenter_crds.tf eks_karpenter_crds.tf.disabled   # if not already
terraform apply   # creates everything except the 2 Karpenter CRD resources
# push all 4 images (see below) - do this as soon as ECR repos exist,
# ideally in parallel with the apply above
mv eks_karpenter_crds.tf.disabled eks_karpenter_crds.tf
terraform apply   # picks up EC2NodeClass + NodePool now that the cluster exists

# Images:
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin 458586357596.dkr.ecr.us-west-2.amazonaws.com
for svc in api worker auth-service core-api; do
  docker buildx build --provenance=false --sbom=false -f Dockerfile.$svc \
    -t 458586357596.dkr.ecr.us-west-2.amazonaws.com/studymate-$svc:latest --push .
done

# Deploy:
export KUBECONFIG=/tmp/studymate-kubeconfig
aws eks update-kubeconfig --name studymate --region us-west-2 --kubeconfig /tmp/studymate-kubeconfig
# get the new ALB security group ID and update charts/studymate/values.yaml's
# albSecurityGroupId (security group IDs are NOT deterministic across rebuilds,
# unlike IAM role ARNs which are)
terraform state show aws_security_group.alb | grep '^\s*id '

# Secrets (values from .env):
kubectl create secret generic studymate-secrets --namespace studymate \
  --from-literal=DATABASE_URL="..." --from-literal=AUTH_JWT_SECRET="..." \
  --from-literal=OPENAI_API_KEY="..." --from-literal=ANTHROPIC_API_KEY="..." \
  --from-literal=S3_BUCKET="..." --from-literal=SQS_QUEUE_URL="..." \
  --from-literal=COOKIE_SECURE=false \
  --dry-run=client -o yaml | kubectl apply -f -
# (namespace itself already exists via terraform import if state is intact;
# if truly starting from zero state, terraform apply above creates it)

export PATH="$HOME/.local/bin:$PATH"
cd charts/studymate
helm upgrade --install studymate . --namespace studymate --wait --timeout 5m
```

Expect one likely hiccup even on a clean rebuild: freshly-launched EC2
nodes can have a 1-3 minute window of flaky cross-node/ALB connectivity
while VPC networking fully converges — this is normal EKS/VPC-CNI
behavior, not a config bug (see Phase 2 doc, Bug 4/6 discussion). If a pod
seems unreachable right after a node just joined, wait a minute or
`kubectl delete pod` to reschedule it before assuming something's wrong.

## How to tear down cleanly (confirmed working, this exact sequence)

This procedure has now been run successfully end-to-end. Follow it in
order — skipping the verification steps is exactly what caused multi-hour
stuck destroys in earlier sessions.

```bash
export KUBECONFIG=/tmp/studymate-kubeconfig

# 1. Let the ALB controller delete its own load balancer, and let Karpenter
#    gracefully deprovision its own nodes, WHILE their controllers are
#    still alive to react:
kubectl delete ingress studymate -n studymate --wait --timeout=60s
kubectl scale deployment auth-service core-api --replicas=0 -n studymate
# (worker is already 0 unless a job is actively running)

# 2. VERIFY the ALB actually got deleted before proceeding - don't just wait a
#    fixed amount of time, poll for the actual result:
for i in $(seq 1 10); do
  COUNT=$(aws elbv2 describe-load-balancers --region us-west-2 \
    --query "length(LoadBalancers[?contains(LoadBalancerName, 'studymat')])" --output text)
  [ "$COUNT" = "0" ] && echo "ALB CLEANED UP" && break
  sleep 5
done

# 3. VERIFY no Karpenter NodeClaims are left - if any are, delete them
#    explicitly and wait for the node to actually disappear:
kubectl get nodeclaims
# if any are listed: kubectl delete nodeclaim <name> --wait --timeout=90s
kubectl get nodes   # should show only the one system node group node left

# 4. Only now, remove the cluster-internal Terraform resources from state
#    (nothing lost - they live inside the cluster being destroyed anyway)
#    and disable the Karpenter CRD file (same chicken-and-egg reason as
#    the rebuild steps need it disabled on create):
cd terraform
terraform state rm kubernetes_manifest.karpenter_node_class kubernetes_manifest.karpenter_node_pool \
  kubernetes_namespace.studymate \
  helm_release.aws_load_balancer_controller helm_release.karpenter helm_release.keda
mv eks_karpenter_crds.tf eks_karpenter_crds.tf.disabled

# 5. Destroy. Expect this to need 2 passes most of the time:
terraform destroy -auto-approve
# if it errors on one resource (commonly a security group or IAM role with
# a lingering dependency), just re-run `terraform destroy -auto-approve`
# again - it resolves itself once whatever it was waiting on finishes
# detaching/terminating.
```

If it still hangs on security group deletion after 2 retries: check for
orphaned ALBs (`aws elbv2 describe-load-balancers`) or orphaned Karpenter
EC2 instances (`aws ec2 describe-instances --filters
"Name=tag:karpenter.sh/nodepool,Values=default"
"Name=instance-state-name,Values=running,pending"`) and clean those up
directly (`aws elbv2 delete-load-balancer` / `aws ec2 terminate-instances`)
before retrying `terraform destroy`.

## Immediate next steps

**0. Rebuild first.** Everything is torn down (see "Current live AWS
state" above) — run "How to rebuild from zero" before anything else. Once
the cluster's up and Phase 2's verification flow passes again (signup →
cross-service auth → presign → KEDA scale-up/down), move on to Phase 4:

1. Request/validate an ACM certificate for a real domain (or decide to
   stay on the raw ALB hostname for now — TLS still needs *a* cert either
   way, ACM's free ones work fine on any domain you control DNS for).
2. Add HTTPS to `charts/studymate/values.yaml`'s `acmCertificateArn` and
   redeploy — the Ingress template already supports this conditionally
   (see `charts/studymate/templates/ingress.yaml`).
3. Flip `COOKIE_SECURE` to `true` in both the manual secret-creation
   commands and `deploy.yml` — the frontend's auth cookie is
   `Secure`+`SameSite=None` and silently won't be set by browsers over
   plain HTTP.
4. Point the frontend's Vercel env var (API base URL) at the new
   ALB/domain, deploy, smoke-test against real production traffic while
   Lambda/ECS still exist untouched as a rollback path.
5. Monitor before proceeding to Phase 5.

Then **Phase 5**: delete the Lambda/API Gateway/ECS Terraform resources
as one distinct, carefully-reviewed `terraform plan`/`apply` — the only
genuinely destructive step in the whole migration, per the user's explicit
preference to always review before applying anything destructive.

## Things this session learned about how the user wants to work

- Wants to drive the terraform/kubectl/helm commands narrative in real
  time — expects clear explanation of *what's about to happen and why*
  before any `apply`/`destroy`, but has been comfortable saying "go ahead"
  once that's given. Always show the plan/diff before applying.
- Cares about AWS cost — has asked to tear down overnight more than once.
  Proactively offer this rather than leaving a cluster running idle.
- Wants a documentation file per phase (this directory), written to
  actually teach the concepts and bugs, not just log what commands ran —
  explicitly said they want to study these later.
- Is doing this as a resume/portfolio project on a self-imposed one-week
  deadline — bias toward actually finishing phases over gold-plating.
- Only commit/push to git when explicitly asked — nothing in this
  migration has been committed yet as of this doc being written (verify
  with `git status` before assuming otherwise).
