# Phase 2 — Helm Charts and Deploying to the Real Cluster

## What this phase was for

Phase 0 built a cluster. Phase 1 built two services and proved they work
correctly outside Kubernetes (via `docker compose`, against real AWS
resources). Phase 2 is where those two things actually meet: packaging
`auth-service`, `core-api`, and `worker` into Helm charts, deploying them
onto the real EKS cluster, exposing them through a real Application Load
Balancer, and proving the whole system — including the worker's
KEDA-driven scale-to-zero — works over the network, not just in theory.

This was, by a wide margin, the hardest phase so far. Not because the Helm
chart itself was complicated, but because it surfaced a real, non-obvious
AWS networking bug that took multiple debugging passes across two separate
sessions to fully root-cause. That bug — and the process of finding it —
is the most valuable thing to actually study from this phase.

---

## Part 1 — Concepts, explained from zero

### Why an umbrella chart with subcharts, not three separate `helm install`s

A Helm **chart** is a template for a set of Kubernetes objects, plus a
`values.yaml` of parameters to fill into that template. An **umbrella
chart** is a chart whose only job is to bundle other charts (its
**subcharts**) so one `helm install` deploys all of them together, with one
shared release history and one `helm upgrade`/`rollback` covering
everything. We used this because `auth-service`, `core-api`, and `worker`
are deployed together, versioned together, and share one Ingress — treating
them as three unrelated Helm releases would mean three separate install
commands, three separate histories, and no single command that represents
"the current state of StudyMate on this cluster."

### Why each subchart's ServiceAccount name is hardcoded, not templated

Normally a Helm chart templates resource names with the release name
(`{{ .Release.Name }}-auth-service`) so multiple copies of a chart can
coexist in one cluster. We deliberately did **not** do that here — every
ServiceAccount is named exactly `auth-service`, `core-api`, or `worker`,
with no release-name prefix. This is because Phase 0's IRSA trust policies
(`terraform/eks_irsa.tf`) are keyed to an *exact* string:
`system:serviceaccount:studymate:core-api`. If the ServiceAccount's actual
name doesn't match that string precisely, IRSA silently fails (the pod
just doesn't get AWS credentials) with no obvious error pointing at the
mismatch. Templating would make the chart more "reusable" in the abstract,
at the cost of breaking a security boundary that depends on an exact name
match. Concrete requirement beat abstract reusability.

### What `target-type: ip` actually means for the Ingress

The `alb.ingress.kubernetes.io/target-type: ip` annotation tells the AWS
Load Balancer Controller to register **pod IP addresses directly** as ALB
targets, bypassing `kube-proxy`/Services entirely for the actual traffic
path. This only works because the VPC CNI gives every pod a real,
directly-routable VPC IP (no overlay network) — the ALB's own ENIs can
reach pod IPs the same way any two VPC resources reach each other. This
is also exactly why security groups matter so much in this phase: ALB → pod
traffic is ordinary VPC networking, fully subject to security group rules,
not something Kubernetes abstracts away.

### KEDA counts in-flight messages on purpose

We initially thought the worker not scaling back to 0 was a bug. It
wasn't: KEDA's `aws-sqs-queue` scaler sums `ApproximateNumberOfMessages`
(visible) **and** `ApproximateNumberOfMessagesNotVisible` (in-flight,
currently being processed or awaiting SQS's visibility-timeout retry)
by default. This is deliberate — it stops KEDA from killing a worker pod
mid-job just because the queue looks empty from the visible-count alone.
Our test job failed (expected 403, no real audio uploaded), and
`apps/worker/run.py` intentionally does *not* delete a message on job
failure — that's what lets SQS redeliver it for a retry. So the "stuck"
in-flight message was the system working exactly as designed; it would
have cleared itself after the queue's 900-second visibility timeout, or
sooner if we hadn't manually purged it for a faster test.

---

## Part 2 — What we actually built

### The chart, file by file
- `charts/studymate/Chart.yaml` — declares 3 local subchart dependencies
  with aliases (`auth-service` → `authService`, `core-api` → `coreApi`),
  so the umbrella `values.yaml` can use clean camelCase keys while the
  subchart directories/names stay kebab-case. Confirmed via `helm
  template` that aliasing works correctly for *physically present*
  subchart directories without ever needing `helm dependency update`.
- `templates/namespace.yaml`, `templates/ingress.yaml` — cluster-wide
  resources not owned by any one service.
- Each subchart (`auth-service`, `core-api`, `worker`) — `Deployment` +
  `Service` (not `worker`, which has no HTTP server) + `ServiceAccount`,
  following the exact-name-match rule above.
- `worker`'s `scaledobject.yaml` — the KEDA `ScaledObject`, using
  `identityOwner: operator` deliberately: KEDA's own IRSA role
  (`studymate-keda-irsa`, read-only `sqs:GetQueueAttributes`) polls queue
  depth, kept separate from the worker pod's own IRSA role (which only
  has receive/delete/change-visibility) — two different jobs, two
  different least-privilege roles.
- **A new ECR repo** (`aws_ecr_repository.core_api` in `terraform/main.tf`)
  — `core-api` needed its own image repo separate from the existing
  `studymate-api` one, since that repo still backs the live Lambda during
  this migration; the two are running in parallel until Phase 5.
- **Health-check-path annotation** on the Ingress
  (`alb.ingress.kubernetes.io/healthcheck-path: /healthz`) — without it,
  the ALB defaults to health-checking `/`, which isn't a real route on
  either app and always fails.

---

## Part 3 — Bugs, in the order they were found

### Bug 1 — missing ECR repo for `core-api`
Straightforward: `core-api` needed a new ECR repository that didn't exist
yet (only `studymate-api` and `studymate-auth-service` did). Added
`aws_ecr_repository.core_api` and applied it before the first image push.

### Bug 2 — Helm can't adopt a namespace it didn't create
**Symptom:** `helm upgrade --install` failed with "invalid ownership
metadata" on the `studymate` namespace.
**Cause:** the namespace was created manually via `kubectl create
namespace` *before* the chart (which also has its own `namespace.yaml`
template) ran — Helm refuses to manage a resource it doesn't already own,
as a safety measure against silently adopting someone else's resource.
**Fix:** `kubectl label`/`annotate` the existing namespace with Helm's
ownership metadata (`app.kubernetes.io/managed-by=Helm`,
`meta.helm.sh/release-name`, `meta.helm.sh/release-namespace`) so Helm
would adopt it. Recurred on the second full rebuild too — the manual
`kubectl create namespace` step in the deploy routine is redundant (the
chart already creates it) and should just be dropped going forward.

### Bug 3 — ALB target groups unhealthy: wrong health check path
**Symptom:** both target groups showed `unhealthy` immediately after
first deploy.
**Cause:** default ALB health check path is `/`, which isn't a route on
either FastAPI app (both only expose real routes plus `/healthz`) —
confirmed the apps themselves were fine the whole time, since kubelet's
own readiness probes against `/healthz` were succeeding in the pod logs
throughout.
**Fix:** `alb.ingress.kubernetes.io/healthcheck-path: /healthz` on the
Ingress.

### Bug 4 — one target stuck on `Target.Timeout`, others fine
**Symptom:** after fixing Bug 3, `auth-service`'s target went healthy
immediately: `core-api`'s did not — a *different* failure mode
(`Target.Timeout`, meaning literally no response, not a wrong status
code).
**First (incomplete) diagnosis:** suspected a single degraded EC2 instance
(the node had been running continuously for hours through heavy Phase-0
test churn). Deleting the pod and letting it reschedule onto the other
node "fixed" it immediately, which seemed to confirm the theory.
**Why this diagnosis was incomplete:** the same exact symptom reappeared
on a *freshly rebuilt* cluster in the next session, on a brand-new node
that had never experienced any churn. A truly node-specific degradation
theory couldn't explain a fresh node having the identical problem. This
is a good example of a fix that appeared to work while treating the wrong
root cause — rescheduling the pod worked as *incidental* mitigation
(it happened to move the pod onto a node that had the right security
group — see Bug 6), not because the original node was actually broken.

### Bug 5 — the *real* Phase 0 bug wasn't fully fixed: TCP-only self-ingress
While investigating Bug 4's reappearance, direct testing (pod-to-pod
`curl`, bypassing the ALB and Kubernetes Services entirely) proved this
wasn't ALB-specific at all: **no pod anywhere could reach another pod on a
different node**, including DNS to CoreDNS. Re-examining Phase 0's
security-group fix (`aws_security_group_rule.eks_cluster_self_ingress`)
showed it only opened **TCP** (`protocol = "tcp"`), never UDP — and DNS
runs over UDP port 53. Fixed by changing the rule to `protocol = "-1"`
(all protocols). This explained the DNS failures specifically, but,
importantly, **did not fully explain Bug 4** — TCP traffic (like an HTTP
health check on port 8000) should already have been covered by the
original TCP-only rule. That gap in the explanation is what led to
finding the real root cause next.

### Bug 6 — the actual root cause: two different security groups in play
Directly comparing the *actual* security groups attached to each node's
EC2 instance (`aws ec2 describe-instances ... SecurityGroups`) revealed
the real problem: **the managed node group's nodes and Karpenter's nodes
were using two completely different security groups.** Karpenter's
`EC2NodeClass` explicitly selects our Terraform-managed
`studymate-eks-cluster` SG (the one carrying the self-ingress fix).
`aws_eks_node_group.system`, with no launch template specified, silently
falls back to an **EKS-auto-created** security group
(`eks-cluster-sg-studymate-<hash>`) that Terraform never touches and has
no self-ingress rule at all. Every "flaky node" symptom across two
sessions — DNS failures, ALB timeouts, cross-node unreachability — traced
back to whichever pod happened to land on the *system node group's* node,
because that node was never actually running with the security group we
thought it was.
**Fix:** added `aws_launch_template.eks_node_system`, explicitly setting
`vpc_security_group_ids = [aws_security_group.eks_cluster.id]`, and
referenced it from `aws_eks_node_group.system` via a `launch_template`
block. This is the correct way to control a managed node group's security
group — `aws_eks_node_group` has no direct `security_group_ids` argument;
you must go through a launch template. Applying this change forced a full
node group replacement (the running node terminated, a new one launched
with the right SG) — confirmed via
`aws ec2 describe-instances ... SecurityGroups` on the new node before
re-testing.
**Lesson, the important one:** *"it works on one node type but not the
other"* is a much stronger signal than *"it's flaky."* The first symptom
(Bug 4) looked like general flakiness and tempted a superficial fix
(reschedule and move on). It was actually a structural, deterministic
difference between two node provisioning paths, and only became obvious
once directly comparing the two node types' actual AWS-level
configuration — not their Kubernetes-level status, which looked identical
(`Ready`, no CNI errors, no log warnings) on both.

### Bug 7 — orphaned Karpenter node blocked teardown
**Symptom:** `terraform destroy` hung for hours (confirmed via `ps aux`
showing the process still alive) stuck deleting a security group, then
errored with `DependencyViolation: resource has a dependent object` once
manually interrupted and retried.
**Cause:** Karpenter provisions EC2 instances *outside* Terraform's direct
management — when we removed `helm_release.karpenter` from Terraform state
and destroyed the cluster (same pattern as Phase 0's teardown), Karpenter's
own controller pod died before it ever got a chance to clean up the nodes
*it* had provisioned. One such node sat running indefinitely, its ENIs
still attached to our security groups, blocking their deletion.
**Fix (that session):** manually identified and terminated the orphaned
instance via `aws ec2 terminate-instances`, waited for its ENIs to detach,
then re-ran `terraform destroy`.
**Lesson for next time:** before removing Karpenter from Terraform state
during a teardown, first delete its `NodeClaim`/`Node` objects (or scale
all Karpenter-managed workloads to 0) so Karpenter's own controller
gracefully deprovisions its nodes *before* the cluster (and Karpenter's
controller along with it) disappears. This wasn't done this time, and
should be step 1 of any future teardown routine.

### Bug 8 — orphaned ALB, same underlying cause as Bug 7
A related second teardown blocker: the ALB itself (created by the AWS
Load Balancer Controller in response to our `Ingress`) was still `active`
in AWS after the cluster was gone — same story: nothing was left alive to
issue the `DeleteLoadBalancer` call, since the controller that owned it
died with the cluster. Fixed by deleting it directly via
`aws elbv2 delete-load-balancer`, which let its ENIs detach and unblocked
the same security groups Bug 7 was fighting.
**General lesson combining Bugs 7 and 8:** anything a Kubernetes
*controller* creates in AWS (Karpenter's nodes, the ALB controller's load
balancers) is invisible to Terraform and won't be cleaned up by
`terraform destroy` — it only exists as long as the controller that
manages it is alive to react to its Kubernetes object being deleted.
Before tearing down a cluster with controllers like these installed, their
managed AWS resources need to be torn down *first*, through Kubernetes
(deleting the Ingress, deleting NodeClaims), not last, through Terraform.

### Bug 9 — stale Terraform state lock after an interrupted session
**Symptom:** `terraform destroy` failed immediately with "Error acquiring
the state lock."
**Cause:** the previous night's background `terraform destroy` process
had been silently orphaned (lost its output pipe when the session ended)
and was still running, untouched, hours later — holding the local state
lock the whole time.
**Fix:** confirmed via `ps aux` that the process was genuinely hung (not
making progress, not just slow), killed it, confirmed via
`terraform force-unlock` that the lock had already released with the
process, removed the stale `.lock.info` file, and re-ran destroy cleanly.
**Lesson:** a `terraform apply`/`destroy` run in the background across a
session boundary can outlive the session that started it. Always check
`ps aux` for the real process before assuming a lock file represents an
active, healthy operation — the lock file's existence and the operation's
actual health are two different questions.

---

## Part 4 — How we proved it actually works

Every seam, exercised for real, through the actual ALB endpoint (not a
port-forward, not `docker compose`):

1. **Signup** against `auth-service`, through the ALB, over `/auth/signup`.
2. **`/auth/me`** with that cookie, through the ALB — same-service check.
3. **`/subjects`** on `core-api`, same cookie, different container — proves
   cross-service auth survives the real Kubernetes network path, not just
   `docker compose`'s shared bridge network.
4. **`/uploads/presign`** → a real, validly-signed S3 URL, proving
   `core-api`'s IRSA role actually grants S3 access from inside the pod.
5. **`/lectures`** → created a lecture, enqueued a real SQS message.
6. **KEDA scaled `worker` 0→1** automatically, confirmed via
   `kubectl get deployment worker` and the `ScaledObject`'s own `ACTIVE:
   True` condition — no manual scaling involved.
7. The **worker pod** picked up the message, used its own separate IRSA
   role to attempt the S3 fetch, got the expected `403` (no real audio
   uploaded), and correctly wrote the failure back to Postgres via
   `core-api`'s database code.
8. **`GET /lectures/{id}`** on `core-api` read that failure state back
   correctly.
9. After clearing the queue, **KEDA scaled `worker` back to 0** — the
   full elastic loop, over real infrastructure, no shortcuts.

---

## What exists now, concretely

```bash
export KUBECONFIG=/tmp/studymate-kubeconfig   # never touches your default kubeconfig
aws eks update-kubeconfig --name studymate --region us-west-2 --kubeconfig /tmp/studymate-kubeconfig

kubectl get pods -n studymate         # auth-service, core-api Running; worker 0 unless a job is active
kubectl get ingress -n studymate      # real ALB hostname
kubectl get scaledobject -n studymate # worker's KEDA scaling state
```

Still HTTP-only (no ACM cert/HTTPS yet — needed before Phase 4's cutover,
since the frontend's `Secure`+`SameSite=None` cookie requires HTTPS to
function at all). Still nothing in CI/CD — every deploy in this phase was
done by hand. That's Phase 3.
