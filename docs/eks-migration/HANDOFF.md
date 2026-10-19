# StudyMate → EKS Migration: Handoff / Session Continuity Doc

**Read this first if you're a new Claude session picking this up.** It
tells you what's been done, what's verified, what's currently running in
AWS, and exactly what's left. The full narrative detail (concepts, every
bug hit and how it was diagnosed) lives in the per-phase docs in this same
directory — read those when you need depth, use this doc for orientation.

## The project, in one paragraph

StudyMate is a small app (FastAPI backend, React frontend on Vercel,
Supabase Postgres). It was migrated from AWS Lambda + ECS Fargate +
API Gateway to Kubernetes on EKS, split into 3 microservices
(`auth-service`, `core-api`, `worker`), as a learning/portfolio exercise in
Docker, Kubernetes, Terraform, and CI/CD — done properly, not as a toy.
**All phases (0-5) are complete.** The Lambda/API Gateway/ECS stack has been
deleted; EKS is the only compute path. Supabase, S3, and SQS stayed as-is.

**This AWS stack is a portfolio showcase, not the product.** Real users will
use a separate, cheaper project (Vercel + one Railway service). It shares
nothing with this stack. A self-contained spec for building it is in
`docs/RAILWAY_REBUILD_SPEC.md`. The AWS stack is brought up for demos and torn
down otherwise to avoid cost.

The full original plan (still accurate) is at
`/home/jeremiah/.claude/plans/zany-dancing-bunny.md`.

## Decisions already made — do not re-litigate these

1. Full replacement of Lambda/ECS, not permanent side-by-side (done, Phase 5).
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
8. This stack is a showcase only; the user-facing product is a separate
   project with its own database, storage, queue and keys (see top).

## Status by phase

| Phase | What it is | Status |
|---|---|---|
| 0 | EKS cluster, Karpenter, KEDA, ALB controller | ✅ Done, verified, documented |
| 1 | Split `apps/api` → `auth-service` + `core-api` | ✅ Done, verified, documented |
| 2 | Helm charts, deploy to real cluster, real ALB | ✅ Done, verified, documented |
| 3 | Wire GitHub Actions CI/CD | ✅ Done, verified by a real green run on `main` |
| 4 | HTTPS/ACM on `api.steeze.ca`, secure cookies, frontend rewrite | ✅ Done, verified live, documented |
| 5 | Decommission Lambda/API Gateway/ECS | ✅ Done (25 resources destroyed, reviewed plan), documented |

Read `docs/eks-migration/phase-0-cluster-bootstrap.md`,
`phase-1-service-split.md`, `phase-2-helm-deploy.md`, `phase-3-cicd.md`,
`phase-4-https-domain.md`, `phase-5-decommission.md` for full detail on each. They're written to actually teach the concepts, not
just log commands — worth reading in order if you're studying this, not
just executing it.

## Current live AWS state

Check before assuming anything - this stack is torn down between sessions:

```bash
cd terraform && terraform state list | wc -l   # ~68 if up, 0 if torn down
aws eks describe-cluster --name studymate --region us-west-2 --query 'cluster.status' 2>&1
```

If torn down, follow "How to rebuild from zero" below. Things that bite on a
rebuild:
- The first `terraform apply` can fail on access-policy associations (404,
  the access entry hasn't propagated yet). Re-run apply; nothing is wrong.
- The ALB security group ID in `charts/studymate/values.yaml` changes every
  rebuild, and so does `acmCertificateArn` (the ACM cert is part of
  Terraform state).
- **The `api` CNAME in Namecheap must be re-pointed at the new ALB hostname**
  every rebuild. The ACM *validation* CNAME does not change, so the new cert
  issues within seconds.
- The **Supabase free-tier project pauses after ~a week idle**. Signup
  returning 500 with `ENOTFOUND tenant/user ... not found` in the auth-service
  logs means restore the project in the Supabase dashboard (not an app bug).
- GitHub Actions secrets (DB, JWT, OpenAI, Anthropic, bucket, queue, Vercel)
  are already set on the repo and survive teardowns.
- The Vercel frontend keeps working only while the cluster is up
  (`apps/web/vercel.json` rewrites to `https://api.steeze.ca`).

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
- Full user flow: signup on `auth-service` → cookie accepted by `core-api`
  (cross-service auth) → S3 presign → SQS enqueue → KEDA scales `worker`
  0→1 → worker processes the job (real S3 call via IRSA; correct 403 for a
  fake audio key; failure written back to Postgres) → KEDA scales to 0 once
  the queue is empty. Also verified end to end with real recordings and the
  full pipeline (transcript, notes, flashcards, quiz, chat).
- HTTPS: valid ACM cert on `api.steeze.ca`, HTTP→HTTPS redirect, session
  cookie `HttpOnly; Secure; SameSite=None`, full flow through the Vercel
  rewrite.
- CI/CD: CI + Deploy run green from a plain push to `main` (images over OIDC,
  secrets, `helm upgrade`, Vercel deploy).
- 51 pytest tests pass against `auth_service`/`core_api`.

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
   referencing `:latest` will succeed (the Lambda no longer exists, so this now only matters for CI and the first helm deploy). Always push all 3 images
   (`worker`, `auth-service`, `core-api`) right after `terraform
   apply` creates the ECR repos, ideally before it reaches the resources
   that reference them.
9. Docker builds use `--provenance=false --sbom=false` (needed when Lambda
   was in the stack; harmless to keep).
10. `kubernetes_namespace.studymate` (added in Phase 3) hit the exact same
    "Unauthorized" failure as bug 7's `helm_release`/`kubernetes_manifest`
    resources during a teardown — it was added later and didn't get the
    same `depends_on = [..., aws_eks_access_entry.terraform_admin]`
    protection the first time. Now fixed in `eks_addons.tf`. General
    rule: **any `kubernetes_*`/`helm_release` Terraform resource needs
    this `depends_on`**, or a `terraform destroy` can revoke Terraform's
    own cluster access before reaching it.

11. The CI role (`AmazonEKSEditPolicy`) can't touch custom resources. KEDA's
    `ScaledObject` needed an extra namespaced `Role`/`RoleBinding` bound to
    the `studymate-deployers` group on the access entry. Any new CRD in the
    chart needs the same. See Phase 3 doc, Part 4.

12. The CI role's `AmazonEKSEditPolicy` can't touch custom resources: KEDA's
    `ScaledObject` needed an extra namespaced `Role`/`RoleBinding` for the
    `studymate-deployers` group (Phase 3 doc, Part 4). Any new CRD in the
    chart needs the same.
13. A failing job is retried by SQS for ~45 min (900 s visibility timeout x 3
    receives, then DLQ), which keeps KEDA's worker up. Purge the queue after
    testing with fake audio keys.
14. The worker image needs `PYTHONUNBUFFERED=1` or `kubectl logs` is empty
    until the process exits (fixed in `Dockerfile.worker`).

## How to rebuild from zero (if torn down)

All bugs above are pre-fixed in the code. ~20 minutes end to end (EKS cluster
creation is ~10-15 min of that).

```bash
cd terraform
# eks_karpenter_crds.tf must be named .disabled for the FIRST apply (its
# resources need the cluster's CRDs, which Helm installs during this apply):
ls eks_karpenter_crds.tf.disabled || mv eks_karpenter_crds.tf eks_karpenter_crds.tf.disabled
terraform plan -out=rebuild.tfplan && terraform apply rebuild.tfplan
# Push the 3 images as soon as the ECR repos exist (parallel with the apply):
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin 458586357596.dkr.ecr.us-west-2.amazonaws.com
for svc in worker auth-service core-api; do
  docker buildx build --provenance=false --sbom=false -f Dockerfile.$svc \
    -t 458586357596.dkr.ecr.us-west-2.amazonaws.com/studymate-$svc:latest --push .
done
# If apply errored on an access-policy association (404), just re-run it.
mv eks_karpenter_crds.tf.disabled eks_karpenter_crds.tf
terraform apply    # second pass: EC2NodeClass + NodePool

# Update charts/studymate/values.yaml with the NEW values:
terraform state show aws_security_group.alb | grep '^\s*id '   # -> albSecurityGroupId
terraform output -raw acm_certificate_arn                       # -> acmCertificateArn
# (the cert is ISSUED within seconds - the validation CNAME in Namecheap is permanent)

export KUBECONFIG=/tmp/studymate-kubeconfig
aws eks update-kubeconfig --name studymate --region us-west-2 --kubeconfig /tmp/studymate-kubeconfig

# Secrets (values from .env; COOKIE_SECURE is true now that the ALB serves HTTPS):
kubectl create secret generic studymate-secrets --namespace studymate \
  --from-literal=DATABASE_URL="..." --from-literal=AUTH_JWT_SECRET="..." \
  --from-literal=OPENAI_API_KEY="..." --from-literal=ANTHROPIC_API_KEY="..." \
  --from-literal=S3_BUCKET="studymate-lecture-audio-jeremiah" \
  --from-literal=SQS_QUEUE_URL="https://sqs.us-west-2.amazonaws.com/458586357596/studymate-lectures" \
  --from-literal=COOKIE_SECURE=true \
  --dry-run=client -o yaml | kubectl apply -f -

export PATH="$HOME/.local/bin:$PATH"
cd ../charts/studymate
helm upgrade --install studymate . --namespace studymate --wait --timeout 6m

# Then: get the ALB hostname and update the `api` CNAME in Namecheap
kubectl get ingress studymate -n studymate -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```
Commit the `values.yaml` change (and push - CI redeploys the same config).
Check Supabase isn't paused before testing signup.

Expect one likely hiccup even on a clean rebuild: freshly-launched EC2
nodes can have a 1-3 minute window of flaky cross-node/ALB connectivity
while VPC networking fully converges — this is normal EKS/VPC-CNI
behavior, not a config bug (see Phase 2 doc, Bug 4/6 discussion). If a pod
seems unreachable right after a node just joined, wait a minute or
`kubectl delete pod` to reschedule it before assuming something's wrong.

## How to tear down cleanly (confirmed working, this exact sequence)

Last run: 79 resources destroyed in ~11 min in a single pass (the managed node
group takes ~8 min of that, the cluster ~2 min - normal for EKS).

This procedure has now been run successfully end-to-end. Follow it in
order — skipping the verification steps is exactly what caused multi-hour
stuck destroys in earlier sessions.

```bash
export KUBECONFIG=/tmp/studymate-kubeconfig

# 1. Let the ALB controller delete its own load balancer, and let Karpenter
#    gracefully deprovision its own nodes, WHILE their controllers are
#    still alive to react:
kubectl delete ingress studymate -n studymate --wait --timeout=60s
kubectl scale deployment auth-service core-api worker --replicas=0 -n studymate
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
# if any are listed (a Karpenter node is usually left): kubectl delete nodeclaim <name> --wait --timeout=120s
# then confirm the EC2 instance is gone: aws ec2 describe-instances --filters Name=tag:karpenter.sh/nodepool,Values=default Name=instance-state-name,Values=running,pending
kubectl get nodes   # should show only the one system node group node left

# 4. Only now, remove the cluster-internal Terraform resources from state
#    (nothing lost - they live inside the cluster being destroyed anyway)
#    and disable the Karpenter CRD file (same chicken-and-egg reason as
#    the rebuild steps need it disabled on create):
cd terraform
terraform state rm kubernetes_manifest.karpenter_node_class kubernetes_manifest.karpenter_node_pool \
  kubernetes_namespace.studymate \
  kubernetes_role_v1.studymate_deployer_keda kubernetes_role_binding_v1.studymate_deployer_keda \
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

## What's left

**Nothing required.** All six phases are complete and documented. Optional
follow-ups, none designed or started:
- Make the `api` DNS record automatic (Route 53 hosted zone for the subdomain
  + ExternalDNS or Terraform) so a rebuild doesn't need a manual CNAME edit.
- GitOps (ArgoCD) instead of push-based `helm upgrade` (decision 3).
- Tighten failed-job behaviour: fail fast on permanent errors (missing file,
  bad API key) instead of 3 x 15 min SQS retries.
- Capture a demo recording and screenshots while the stack is up (it is torn
  down between sessions) and link them from `README.md`.
- Database hygiene: `users` has row-level security off and the Supabase `anon`
  role has full privileges on it; enable RLS and revoke the grants (the app
  connects as `postgres`, which bypasses RLS, so nothing breaks). Rotate the DB
  password if it was ever printed in a log.
- `terraform/terraform.tfvars` may still contain old application secrets that
  Terraform no longer reads; they can be deleted.

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
- Only commit/push to git when explicitly asked. Commit messages should
  read like a person wrote them (short, plain, no AI-style phrasing or
  trailers).
