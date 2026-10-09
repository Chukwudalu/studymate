# Phase 0 — Cluster Bootstrap

## What this phase was for

Before touching a single line of application code, we needed somewhere for
the future `auth-service`, `core-api`, and `worker` to actually run. Phase 0
built that somewhere: an EKS cluster with everything it needs to schedule
workloads elastically, tear itself down cleanly, and let our services talk
to AWS securely. Nothing application-specific happens in this phase — it's
pure infrastructure, and it's purely additive (nothing in the existing
Lambda/ECS setup was touched).

By the end of this phase we'd proven, with a real (throwaway) workload, that
the cluster can grow a node from nothing when work shows up, and shrink back
to nothing when it's done — which is the exact mechanism the real `worker`
service will lean on later.

---

## Part 1 — Concepts, explained from zero

If you already read the "what should I study" conversation, skip to Part 2.
This is the condensed version of that, specific to what Phase 0 built.

### The reconciliation model (the single biggest mental shift)

Lambda and ECS both work the way you'd expect: you tell AWS "run this," and
it runs it. Kubernetes works differently. You **declare a desired state**
("there should be 3 pods running this image"), and a background controller
continuously compares that desired state to reality and nudges reality
toward it. Every piece of this phase is an instance of that same loop:

- A `Deployment` says "N replicas should exist" → a controller creates/kills
  pods to match.
- Karpenter's `NodePool` says "pods should be schedulable" → Karpenter
  creates/destroys EC2 instances to match.
- KEDA's `ScaledObject` (Phase 2) says "replica count should track SQS
  depth" → it edits the Deployment's replica count, and the Deployment
  controller above takes it from there.

Once this clicks, "Karpenter," "the Deployment controller," and "KEDA" stop
looking like three unrelated tools and start looking like the same idea
applied at three different layers (nodes, pods, and pod *count*).

### The pieces we installed, and the problem each one solves

| Piece | Problem it solves |
|---|---|
| **EKS cluster** | The Kubernetes control plane — the "brain" that stores desired state and schedules pods onto nodes. AWS runs and patches this for us. |
| **Node group** | A fixed set of EC2 instances that register with the cluster as workers. We run exactly **one** small node here, just for cluster-system pods. |
| **Karpenter** | Watches for pods that can't be scheduled (no node has room) and reacts by launching a right-sized EC2 instance on demand — then terminates it once nothing needs it. This is what gives us elastic capacity beyond that one fixed system node. |
| **IRSA** (IAM Roles for Service Accounts) | Lets one specific Kubernetes pod assume one specific AWS IAM role — via a trust relationship keyed to that pod's Kubernetes identity, not a shared node-wide credential. This is the Kubernetes-native answer to "how does `core-api`'s pod get S3/SQS access without every pod on the cluster getting the same access." |
| **EKS access entries** | The modern way to say "this AWS IAM identity is allowed to run kubectl/helm against this cluster," replacing the older `aws-auth` ConfigMap approach. |
| **AWS Load Balancer Controller** | Watches for `Ingress` objects and provisions a real Application Load Balancer to match. This becomes our replacement for API Gateway in Phase 2. |
| **KEDA** | Kubernetes Event-Driven Autoscaling. Scales a Deployment's replica count based on an external metric (SQS queue depth, in our case) — the direct Kubernetes equivalent of the CloudWatch-alarm/Application-Auto-Scaling setup the ECS worker uses today. |

### Why IRSA's trust policy looks the way it does

Every IRSA role in `eks_irsa.tf` has a trust policy shaped like this:

```json
"Condition": {
  "StringEquals": {
    "<oidc-issuer>:sub": "system:serviceaccount:studymate:core-api",
    "<oidc-issuer>:aud": "sts.amazonaws.com"
  }
}
```

Read literally: *"only a pod whose Kubernetes ServiceAccount is named exactly
`core-api`, in the `studymate` namespace, may assume this role."* The
mechanism behind it: the EKS cluster runs its own OIDC (OpenID Connect)
token issuer. When a pod using that ServiceAccount starts, Kubernetes
mounts it a signed token proving "I am `core-api` in `studymate`." AWS's STS
(Security Token Service) trusts tokens from that issuer because we
registered it as an `aws_iam_openid_connect_provider` — the exact same
pattern this repo already used for GitHub Actions in `github_oidc.tf`, just
federating a different kind of identity (Kubernetes pods instead of GitHub
workflow runs). Once you see the two side by side, "let an external system
assume an AWS role without long-lived keys" stops being two separate tricks
and becomes one pattern with a different issuer.

### Why Karpenter's IAM policy is full of tag conditions

Karpenter's controller can create and terminate EC2 instances — that's a
powerful, security-sensitive permission. `eks_irsa.tf`'s Karpenter policy
scopes nearly every action with conditions like:

```json
"Condition": {
  "StringEquals": { "aws:ResourceTag/kubernetes.io/cluster/studymate": "owned" },
  "StringLike": { "aws:ResourceTag/karpenter.sh/nodepool": "*" }
}
```

This means Karpenter can only ever touch EC2 resources tagged as belonging
to *this* cluster and *a* Karpenter NodePool — not any EC2 instance in the
account. It's least-privilege applied to a controller that creates cloud
resources on its own, a pattern worth recognizing anywhere you grant a
piece of software the ability to provision infrastructure for itself.

---

## Part 2 — What we actually built, file by file

All of this lives in `terraform/`, split into focused files rather than one
giant one:

### `eks.tf` — the cluster itself
- An IAM role the EKS control plane assumes, and a security group for it.
- `aws_eks_cluster.main` — the cluster, named `studymate`, placed in the
  account's existing **default VPC** (no new VPC — see "design trade-offs"
  below).
- `access_config { authentication_mode = "API" }` — opts into EKS access
  entries instead of the legacy `aws-auth` ConfigMap.
- An access entry granting whoever runs `terraform apply` full admin on the
  cluster, so Terraform itself (acting as you) can install the Helm
  releases below in the same run.

### `eks_node_group.tf` — the one fixed node
- IAM role for EC2 instances joining as nodes (worker-node policy, CNI
  policy, ECR read-only).
- Tags every default-VPC subnet with `kubernetes.io/cluster/studymate =
  shared` — both EKS and Karpenter use this tag to know which subnets
  they're allowed to use.
- `aws_eks_node_group.system` — one `t3.small`, `desired_size = 1`. This
  node exists only to run always-on cluster plumbing (CoreDNS, the ALB
  controller, Karpenter itself, KEDA). Karpenter provisions everything else
  on demand.

### `eks_irsa.tf` — who's allowed to call which AWS APIs
- The cluster's own OIDC provider (see "why IRSA's trust policy" above).
- One IAM role each for: `core_api` (S3 put/get/delete + SQS send —
  matches what the Lambda has today), `worker` (S3 get + SQS
  receive/delete/change-visibility — matches the ECS task today), `keda`
  (SQS read-only, so it can poll queue depth), the ALB controller
  (AWS's own published policy, downloaded verbatim into
  `terraform/policies/alb_controller_policy.json`), and Karpenter (a long,
  tag-scoped policy — see above).
- **`auth-service` gets no AWS IAM role at all.** It only ever talks to
  Supabase Postgres over the public internet — no AWS API calls, so there's
  nothing to scope.
- An SQS queue + 4 EventBridge rules so Karpenter hears about spot
  interruptions, scheduled maintenance, and rebalance recommendations from
  AWS, and can drain a node gracefully before it disappears.

### `eks_addons.tf` — the controllers that make the cluster useful
- `helm` and `kubernetes` Terraform providers, pointed at the cluster using
  `aws eks get-token` (no static credentials — same OIDC-driven pattern as
  everywhere else in this repo).
- A security group for the future Application Load Balancer, plus a rule
  letting it reach pods on the nodes.
- Three `helm_release` resources: the AWS Load Balancer Controller,
  Karpenter, and KEDA — each wired to its IRSA role from `eks_irsa.tf`.

### `eks_karpenter_crds.tf` — the actual scaling policy
- `EC2NodeClass` — *what* Karpenter is allowed to launch (AMI, IAM role,
  which subnets/security groups).
- `NodePool` — *when* and *how much*: on-demand only, `t3.medium`/`t3.large`,
  consolidate (shrink) nodes that go empty or underused.

---

## Part 3 — Design trade-offs made deliberately

- **No new VPC.** The default VPC already has public subnets across every
  AZ, satisfying EKS's multi-AZ requirement. There's no NAT gateway, so
  nodes get public IPs directly, locked down by security groups — the same
  trade-off the existing ECS Fargate worker already makes. This avoids
  ~$32/mo and real Terraform complexity for a project at this scale; a
  genuinely production-hardened version would use private subnets + NAT.
- **One shared security group** for both the control plane and every node
  (rather than two separate SGs referencing each other). Simpler, but it's
  what caused the self-ingress bug below — worth knowing that trade-off
  exists if you ever split it later.
- **Helm releases installed via Terraform** (not a manual `helm install`
  step after `apply`), so "cluster is fully usable" stays one
  `terraform apply` away from a clean checkout.
- **Karpenter CRDs split into their own file**, applied in a second pass —
  explained in the bugs section below, it's structural, not a mistake.

---

## Part 4 — Bugs hit, and what each one actually teaches

Every one of these produced a real, correct error message once we knew
where to look — none of this was guesswork.

### Bug 1 — `helm_release` `set` block syntax
**Symptom:** `terraform validate` rejected `set = [{ name = ..., value =
... }]` in all three `helm_release` resources.
**Cause:** that list-of-objects syntax only exists in newer versions of the
`hashicorp/helm` provider. This repo pinned `~> 2.0`, which resolved to
2.17.0 — still on the older, repeatable `set { name = ... value = ... }`
block form.
**Lesson:** provider syntax isn't fixed by the resource type alone — it can
shift between provider *versions* even when the underlying Helm chart
doesn't change. Always check what version actually got installed
(`terraform init` output) when a syntax that "should" work doesn't.

### Bug 2 — `kubernetes_manifest` needs a cluster that doesn't exist yet
**Symptom:** `terraform plan` failed on both Karpenter CRD resources with
`cannot create REST client: no client config`.
**Cause:** the `kubernetes_manifest` resource type validates against the
*live* cluster's API schema, even during planning — but in this same
`apply`, the cluster it needs to talk to doesn't exist until later in the
same run. A structural chicken-and-egg problem, not a typo.
**Fix:** split those two resources into their own file, given a
`.disabled` extension so Terraform ignores it entirely on the first apply.
Once the cluster was real, we renamed the file back to `.tf` and ran
`apply` again to pick them up.
**Lesson:** some Terraform resource types need the thing they configure to
already exist. When you're creating both the platform and a resource that
configures *within* that platform in one file set, expect to split the
apply into stages.

### Bug 3 — security group description contained invalid characters
**Symptom:** `InvalidParameterValue: Invalid security group description`.
**Cause:** the description `"EKS control plane <-> node communication"`
used `<` and `>`, which aren't in AWS's allowed character set for SG
descriptions.
**Lesson:** small, easy to miss, easy to fix — AWS's security-group
description validator is stricter than you'd guess.

### Bug 4 — Lambda image missing (recurring)
**Symptom:** `InvalidParameterValueException: Source image ... does not
exist`.
**Cause:** this environment's ECR repos had been torn down and recreated
(empty) since images were last pushed — this happened more than once during
the session as the environment was rebuilt.
**Lesson:** `force_delete = true` on an ECR repo (needed so `terraform
destroy` can tear it down cleanly) means every fresh `apply` after a
`destroy` needs images pushed *before* anything that references
`:latest` (Lambda, ECS task definitions) can succeed. Order matters:
push images first, then apply resources that reference them.

### Bug 5 — background apply looked "stuck," wasn't
**Symptom:** an `apply` felt like it had hung.
**Reality:** `aws eks describe-cluster`/`describe-nodegroup` showed
`ACTIVE`/`CREATING` with zero health issues — it was just slow. EKS cluster
creation and node-group provisioning are both inherently multi-minute
operations (control plane spin-up, EC2 boot, kubelet registration). Not
every long wait is a bug.
**Lesson:** before assuming something's broken, check the *actual* resource
state via the AWS CLI directly, rather than only reading Terraform CLI
output. It disambiguates "slow" from "failed" immediately.

### Bug 6 — state drift after an interrupted apply
**Symptom:** `terraform plan` wanted to create `aws_eks_node_group.system`
— but `aws eks describe-nodegroup` showed it already existed and was
`ACTIVE`.
**Cause:** an earlier `apply` was interrupted after AWS had already
accepted the `CreateNodegroup` API call, but before Terraform could record
success in its state file. Terraform's state is just *what Terraform
believes exists* — when a real AWS create-call outlives the Terraform
process that issued it, state and reality disagree.
**Fix:** `terraform import aws_eks_node_group.system studymate:studymate-system`
— tells Terraform "this resource already exists, adopt it into state
instead of creating a duplicate."
**Lesson:** this is *the* reason state exists as a concept worth
understanding, not just a file to ignore. An interrupted apply doesn't
undo real-world changes; it just desynchronizes Terraform's belief from
reality. `import` is the repair tool for exactly that.

### Bug 7 — ALB controller stuck in `CrashLoopBackOff`
**Symptom:** pod logs: `"failed to get VPC ID: ... context deadline
exceeded"`.
**Cause:** the controller's default behavior is to discover its VPC ID by
querying EC2 instance metadata (IMDS) *from inside the pod*. A pod's
network namespace sits one extra hop away from the host than IMDS's default
hop-limit allows, so the query timed out.
**Fix:** pass `vpcId` directly as a Helm value, skipping the IMDS lookup
entirely.
**Lesson:** IMDS-from-a-pod is a known, recurring EKS gotcha across many
controllers, not specific to this one. When something works fine on a
plain EC2 instance but fails identically from inside a pod on that same
instance, IMDS hop-limits are always worth checking first.

### Bug 8 — a race between two Helm installs
**Symptom:** KEDA's install failed with `no endpoints available for
service "aws-load-balancer-webhook-service"`.
**Cause:** Terraform applied `helm_release.aws_load_balancer_controller`
and `helm_release.keda` in parallel (nothing in the code told it not to).
KEDA's install creates Kubernetes `Service` objects, and *every* Service
creation cluster-wide gets intercepted by the ALB controller's admission
webhook — which had no running pod yet to answer it.
**Fix:** an explicit `depends_on = [helm_release.aws_load_balancer_controller]`
on the KEDA release, forcing Terraform to wait for that resource's own
`apply` to fully complete (which only happens once Helm confirms the
controller's pods are actually `Running`) before starting KEDA's.
**Lesson:** Terraform's automatic dependency graph only sees dependencies
it can infer from resource *attributes* referencing each other. A
dependency that only exists inside the *cluster* (one workload's webhook
intercepting another's API calls) is invisible to Terraform unless you
state it explicitly.

### Bug 9 & 10 — Karpenter CRD schema drift
**Symptom:** `NodePool` rejected with `spec.disruption.consolidateAfter:
Required value`; then, separately, `EC2NodeClass` rejected with
`spec.amiSelectorTerms: Required value`.
**Cause:** the Karpenter version that actually installed (1.14.1) requires
both fields explicitly — older Karpenter versions defaulted
`consolidateAfter` implicitly, and used to auto-resolve an AMI from
`amiFamily` alone without requiring `amiSelectorTerms`.
**Fix:** added `consolidateAfter = "30s"` (Karpenter's own documented
default value, just made explicit), and `amiSelectorTerms = [{ alias =
"al2023@latest" }]` (the modern alias shorthand for "latest AL2023 AMI for
this cluster's Kubernetes version").
**Lesson:** fast-moving tools like Karpenter change their CRD's required
fields between minor versions. The Kubernetes API's own validation error is
the authoritative source of truth here — always more reliable than
whatever version of a tutorial or plan you started from.

### Bug 11 — the real root cause: no self-referencing security group rule
**Symptom:** a real Karpenter-launched node sat `NotReady` for 8+ minutes;
`aws-node` (the VPC CNI pod) was stuck `CrashLoopBackOff`, `1/2` containers
ready, readiness probe timing out on its own internal port; `kubectl logs`
against that pod failed outright with `dial tcp ...:10250: i/o timeout`.
**Cause:** `aws_security_group.eks_cluster` is shared by *both* the control
plane's ENIs and every node — but it only had an **egress** rule, no
**ingress** rule. Nothing in that security group was allowed to receive
traffic from anything else in that same security group. That meant the
control plane couldn't reach kubelet on any node (breaking `kubectl
logs`/`exec` directly, as seen), and — the actual root cause of the CNI
crash — the VPC CNI's components on a node couldn't complete their own
initialization traffic either.
**Fix:** added a self-referencing ingress rule (`source_security_group_id
= aws_security_group.eks_cluster.id`, all TCP ports) so members of the
security group can reach each other.
**Lesson:** this is the single most important bug of the whole phase to
actually understand, not just remember the fix for. A security group with
only an egress rule looks intuitively "open enough" (nodes can reach the
internet, so what's missing?) — but egress and ingress are independent;
allowing a resource to *initiate* outbound traffic says nothing about
whether it's allowed to *receive* traffic others send back on a new
connection, and cluster-internal control-plane-to-node traffic is exactly
that kind of inbound traffic. Whenever multiple AWS-networked things need
to talk to each other and they share one security group, that group needs
an explicit self-referencing ingress rule — it is never implied.

---

## Part 5 — How we proved it actually works

Applying without errors isn't proof something works — only a live test is.
We deployed a throwaway `Deployment` requesting more CPU/memory than the
one system node had free, and watched:

1. The pod went `Pending` (nothing could fit it).
2. Karpenter noticed within seconds and created a `NodeClaim` for a
   `t3.medium`.
3. A real EC2 instance launched, joined the cluster, and (after the
   security-group fix) went `Ready`.
4. The pod scheduled onto it and went `Running`.
5. We deleted the test `Deployment`.
6. Karpenter's `consolidateAfter: 30s` policy kicked in, drained the now-empty
   node, and terminated the EC2 instance — back down to exactly the 1
   system node.

That full loop — scale up from nothing, scale back down to nothing,
automatically, triggered purely by workload demand — is the exact mechanism
the real `worker` service will use in Phase 2, just driven by SQS queue
depth (via KEDA) instead of a raw resource request.

---

## What exists now, concretely

Run these yourself to see it:

```bash
aws eks update-kubeconfig --name studymate --region us-west-2

kubectl get nodes                    # 1 t3.small system node
kubectl get pods -n kube-system      # CoreDNS, ALB controller, aws-node, kube-proxy
kubectl get pods -n karpenter        # karpenter controller
kubectl get pods -n keda             # keda-operator, admission webhook, metrics apiserver
kubectl get ec2nodeclass,nodepool    # both "default", both READY
```

Nothing user-facing exists yet — no services, no Ingress, no way for the
frontend to reach anything. That's Phase 1 and Phase 2.
