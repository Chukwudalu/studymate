# Phase 3 — Wiring CI/CD

## What this phase was for

Phases 0-2 stood up the cluster and proved the app runs on it — but every
deploy so far was done by hand: build an image, `docker push` it, run
`helm upgrade` from a terminal. Phase 3 replaces those manual steps with
GitHub Actions, so a push to `main` builds and deploys automatically —
the same shape of pipeline the existing Lambda/ECS deploy already had,
extended to cover 3 services and a Kubernetes deploy step instead of 2
services and `aws lambda update-function-code`/`aws ecs update-service`.

This phase also surfaced one real, easy-to-miss security/RBAC bug that's
worth understanding on its own, independent of Kubernetes or Terraform:
**a namespace-scoped permission can never grant a cluster-scoped action,
no matter what the underlying policy says.**

---

## Part 1 — Concepts, explained from zero

### Why the tests needed to move, not just the app code

`tests/test_api.py`, `test_auth_routes.py`, and `test_chat.py` imported
`from apps.api import ...` — the *old* monolith module, which Phase 1
never touched (it still backs the live Lambda). Once `ci.yml`'s install
step stops installing `apps/api/requirements.txt` (replaced by
`auth_service`'s and `core_api`'s), those imports would fail at collection
time — not because the code is wrong, but because a dependency
(`mangum`, specific to the old Lambda-shaped app) would no longer be
installed in the CI environment. The fix was mechanical — change which
module each test imports from — because the *old* and *new* code have
identical attribute names (`main.get_lecture`, `main.s3`, etc.); only the
import path changed. Verified by actually running `pytest` locally before
touching CI at all: 51 passed, not "the file compiles."

### Why the CI role's Kubernetes access is scoped to one namespace

The GitHub Actions role (`studymate-github-actions-deploy`) already
existed from before this migration, with IAM permissions scoped tightly
to specific ECR repos, one Lambda function, one ECS service. Extending it
for Kubernetes access follows the same philosophy: an **EKS access
entry** (`aws_eks_access_entry.github_actions`) plus an **access policy
association** using `AmazonEKSEditPolicy`, scoped with
`access_scope { type = "namespace", namespaces = ["studymate"] }`. This
means a compromised CI token could redeploy the app — but couldn't touch
the node group, other namespaces, or cluster-wide resources like the
Karpenter/KEDA custom resources. Same least-privilege instinct as every
other IAM policy in this repo, just expressed through EKS's access-entry
system instead of raw IAM.

### The bug this scoping decision surfaced: cluster-scoped vs. namespace-scoped resources

Kubernetes resources come in two flavors: **namespaced** (Pods, Deployments,
Services, Secrets — anything that lives "inside" a namespace) and
**cluster-scoped** (Namespaces themselves, ClusterRoles, Nodes,
PersistentVolumes — things that exist above any single namespace). RBAC
rules bound via a namespace-scoped binding (a `RoleBinding`, which is what
EKS creates for a `namespace`-scoped access policy) can **only** ever
grant permissions on namespaced resource kinds. This isn't a matter of
what the underlying policy document lists as allowed actions — it's a
structural property of how Kubernetes authorization works. A
`RoleBinding` scoped to `studymate` literally cannot authorize a request
to create, read, or delete a `Namespace` object, because "create a
namespace" has no namespace of its own to scope the binding against.

This directly broke something already in `deploy.yml`: the
`kubectl create namespace studymate --dry-run=client -o yaml | kubectl
apply -f -` step, and — less obviously — the Helm chart's own
`templates/namespace.yaml`, since `helm upgrade` applying a chart that
declares a `Namespace` object hits the exact same authorization wall,
regardless of whether `kubectl` or Helm issues the underlying API call.

---

## Part 2 — What we actually built

### Test suite moved to the new modules
- `tests/test_api.py` → renamed `tests/test_core_api.py`, import changed
  to `from apps.core_api import main`.
- `tests/test_auth_routes.py` → imports changed to `apps.auth_service.*`.
- `tests/test_chat.py` → import changed to `from apps.core_api import chat`.
- All 51 tests pass unchanged otherwise — proof the split in Phase 1 didn't
  alter behavior, only location.

### `ci.yml`
One change: the install step now installs `apps/auth_service/requirements.txt`
and `apps/core_api/requirements.txt` instead of `apps/api/requirements.txt`.
`apps/worker/requirements.txt` and the frontend build job are untouched.

### `terraform/github_oidc.tf` (extended)
- `EcrPush` statement's resource list grew to include the new
  `auth_service` and `core_api` ECR repo ARNs.
- New `EksDescribe` statement (`eks:DescribeCluster`) — needed by
  `aws eks update-kubeconfig` in the deploy job; this is what generates a
  kubeconfig, separate from what that kubeconfig is actually *authorized*
  to do once generated.
- New `aws_eks_access_entry.github_actions` +
  `aws_eks_access_policy_association.github_actions` — the namespace-scoped
  `AmazonEKSEditPolicy` grant described above.
- Lambda/ECS permissions (`LambdaDeploy`, `EcsDeploy`, `EcsUpdateService`,
  `PassEcsRoles`) deliberately **kept**, even though the new `deploy.yml`
  no longer uses them — Lambda/ECS aren't decommissioned until Phase 5,
  and leaving a manual-rollback path available costs nothing.

### `terraform/eks_addons.tf` — the namespace becomes infrastructure
- New `resource "kubernetes_namespace" "studymate"`, imported from the
  namespace we'd already been creating by hand in Phases 1-2 (`terraform
  import kubernetes_namespace.studymate studymate`) rather than recreated.
- Carries a `helm.sh/resource-policy: keep` annotation — explained below,
  this isn't decorative.
- `charts/studymate/templates/namespace.yaml` **deleted** — the chart no
  longer declares a Namespace at all.
- `deploy.yml`'s `kubectl create namespace` step **removed** — replaced
  with a comment explaining why, so a future reader doesn't "fix" the
  apparent gap by adding it back.

### `deploy.yml`, rewritten
- `deploy-api` and `deploy-worker` jobs replaced with:
  1. **`build-and-push`** — a `strategy.matrix.service: [auth-service,
     core-api, worker]` job, parameterized by `Dockerfile.${{
     matrix.service }}` and the matching ECR repo name. One job definition
     instead of three near-duplicate ones.
  2. **`deploy-k8s`** (needs `build-and-push`) — `aws eks
     update-kubeconfig`, apply the `studymate-secrets` Secret from GitHub
     encrypted secrets, then `helm upgrade --install` with each service's
     image tag set to the commit SHA.
- `deploy-frontend` — untouched.
- `COOKIE_SECURE=false` in the Secret, with a comment flagging it must
  flip to `true` in Phase 4 once HTTPS lands — the ALB is still
  plain-HTTP right now, and a `Secure` cookie is silently refused by every
  browser over plain HTTP, which would break login in a way that's easy
  to misdiagnose as a backend bug.

---

## Part 3 — The bug, start to finish

**Symptom, if this had shipped untested:** the first real CI deploy would
fail on `kubectl create namespace studymate` with a `Forbidden` error —
`User "...studymate-github-actions-deploy" cannot create resource
"namespaces" at the cluster scope`.

**Why it wasn't obvious from the Terraform alone:** `AmazonEKSEditPolicy`
*does* include broad permissions, including on namespaces, when
associated at `cluster` scope. Reading the IAM/EKS policy in isolation, it
looks like it should work. The restriction only becomes visible when you
know that `access_scope { type = "namespace" }` changes *how* that policy
gets bound in the cluster (a namespaced `RoleBinding`, not a cluster-wide
`ClusterRoleBinding`) — and that Kubernetes authorization checks the
binding's scope against the resource kind's own scope, independent of
what the policy document says is allowed.

**The fix, and why it needed two parts:**
1. Move namespace *ownership* to Terraform (which runs with the
   Terraform-applying identity's own cluster-admin access entry, not the
   CI role's scoped one) — `kubernetes_namespace.studymate`, imported from
   the existing namespace rather than recreated from scratch.
2. Remove the namespace from *every* other path that might try to
   manage it: the Helm chart's own template, and the CI workflow's
   explicit `kubectl create namespace` step. Missing either one would
   have reintroduced the same failure the next time that path ran.

**The subtler follow-on risk, caught before it caused damage:** simply
deleting `templates/namespace.yaml` from the chart isn't safe on its own.
Helm 3's upgrade process prunes resources that were present in a
release's *stored history* but are missing from the *new* chart version —
and it decides what to prune from that stored history, not from whatever
annotations happen to be on the live object right now. Without a
safeguard, the very next `helm upgrade` (even run with full admin
credentials, this has nothing to do with the CI role's scoping) would
have tried to **delete the Namespace itself** — which cascades to
deleting everything inside it. Caught and fixed *before* running that
upgrade, using `helm.sh/resource-policy: keep` (now declared permanently
in the Terraform resource's own annotations, not just a one-off `kubectl
annotate`) — this tells Helm's prune logic to leave the object alone even
though its own history says it should be removed. Verified directly: ran
`helm upgrade` after all these changes and confirmed via
`kubectl get namespace` and `kubectl get pods -n studymate` that both the
namespace and the already-running pods were completely undisturbed.

**The general lesson:** when moving a resource *out* of Helm's management
(to Terraform, or anywhere else), removing it from the chart's templates
is necessary but not sufficient — Helm's own upgrade history needs to be
told not to delete it, or the very next `helm upgrade` (potentially run
by anyone, admin or CI, at any point in the future) can silently take it
down.

---

## What's still unverified

Everything Terraform and `kubectl` can confirm has been checked: the IAM
policy, the access entry, the access policy's exact scope, the absence of
a stray `RoleBinding` (correctly absent — EKS's access-entry system
authorizes directly, it doesn't materialize RBAC objects). What's **not**
verified is a real, live GitHub Actions run — that needs actual repository
secrets configured on GitHub's side, which only you can do:

```
DATABASE_URL, AUTH_JWT_SECRET, OPENAI_API_KEY, ANTHROPIC_API_KEY,
BUCKET_NAME, SQS_QUEUE_URL
```

(`VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` already exist for
`deploy-frontend`.) Once those are set and a real push to `main` happens,
the first live run is the true end-to-end test of this phase — watch it
closely the first time, since a scoping mistake this specific (works with
admin credentials locally, fails only under the CI role's restricted
access) is exactly the kind of bug that's invisible until the exact
credentials that will actually be used in production are the ones making
the call.
