# Phase 4 - HTTPS and a real domain

**Goal:** serve the API over HTTPS on `api.steeze.ca` from the EKS ALB, turn on
secure cookies, and point the Vercel frontend at the new domain.

**Result:** done and verified live. `https://api.steeze.ca/healthz` returns 200
with a valid Amazon-issued certificate, HTTP redirects to HTTPS, and signup,
login, presign and lecture creation all work through the Vercel site with a
`Secure; SameSite=None; HttpOnly` session cookie.

---

## Part 1 - The concepts

### Why HTTPS was blocking everything
Up to Phase 3 the ALB only listened on plain HTTP (port 80). That caused two
separate problems for a frontend served from `https://...vercel.app`:

1. **Mixed content.** A page loaded over HTTPS is not allowed to call an
   `http://` API. The browser blocks the request before it leaves.
2. **Cookies.** The session cookie is `Secure` + `SameSite=None` so it can be
   sent cross-site. Browsers refuse to store a `Secure` cookie that arrived over
   plain HTTP, so login would silently never "stick".

Both vanish once the API is on HTTPS.

### TLS certificates and ACM
HTTPS needs a certificate that proves the server really is `api.steeze.ca`.
**ACM (AWS Certificate Manager)** issues free public certificates for domains you
own, renews them automatically, and plugs directly into an ALB. It can't issue
one for `*.elb.amazonaws.com` or `*.vercel.app` - you don't own those names,
which is exactly why this phase needed a real domain.

### DNS validation
To prove ownership, ACM gives you a one-off **CNAME record** to publish in your
domain's DNS. ACM looks it up, sees it, and issues the certificate. Two details
that matter:
- The validation record for a given account + domain is **the same every time**,
  so after the first time it never needs touching again, even across
  `terraform destroy` / rebuild cycles. A rebuilt cert is issued within seconds.
- Registrars like Namecheap want only the **host label** (`_abc.api`), not the
  full name (`_abc.api.steeze.ca`), or you end up with `...steeze.ca.steeze.ca`.

### How the ALB gets the certificate
The AWS Load Balancer Controller reads annotations on the Ingress
(`charts/studymate/templates/ingress.yaml`). When `acmCertificateArn` is set in
`values.yaml` the template switches on:
```
alb.ingress.kubernetes.io/listen-ports: '[{"HTTP": 80}, {"HTTPS":443}]'
alb.ingress.kubernetes.io/certificate-arn: <arn>
alb.ingress.kubernetes.io/ssl-redirect: '443'
```
The controller then adds an HTTPS:443 listener with the cert and turns the HTTP
listener into a 301 redirect. The ALB's security group already allowed 443.

### Why the frontend still goes through a Vercel rewrite
`apps/web/vercel.json` rewrites `/auth`, `/lectures`, `/subjects` and `/uploads`
to `https://api.steeze.ca`. The browser only ever talks to the Vercel origin, so
the cookie is first-party and there is no CORS to configure. The API URL is
hardcoded in `vercel.json` rather than an env var because rewrites don't read
env vars.

---

## Part 2 - What was built

- `terraform/acm.tf` - `aws_acm_certificate.api` for `api.steeze.ca`, DNS
  validation, outputs the ARN and the validation CNAME.
- `charts/studymate/values.yaml` - `acmCertificateArn` and the ALB security group.
- `.github/workflows/deploy.yml` - `COOKIE_SECURE=true` in the secret CI applies.
- `apps/web/vercel.json` - rewrites now point at `https://api.steeze.ca`.
- Two DNS records at Namecheap (the registrar and DNS host):
  1. the ACM validation CNAME (set once, never changes);
  2. `api` CNAME -> the ALB hostname (**changes on every rebuild**).

No `aws_acm_certificate_validation` resource was added on purpose: it makes
`terraform apply` block until DNS is in place, which is awkward when a human has
to add the record. The cert simply becomes `ISSUED` once DNS resolves; the code
only needs the ARN.

---

## Part 3 - Problems hit, in order

### 1. A brand-new `.ca` domain didn't resolve (NXDOMAIN)
Adding the records had no effect because `steeze.ca` didn't exist in the `.ca`
registry's zone yet. Querying the TLD servers showed NXDOMAIN, which is what
separates "my record is wrong" from "the domain isn't published". New `.ca`
domains can need the registrant (CIRA) agreement accepted before they're
active. It resolved some hours later with no changes on our side.

### 2. The `api` CNAME points at an ALB that's recreated on every rebuild
Each cluster rebuild creates a new ALB with a new hostname
(`...-1538864527...` vs `...-1388564425...`), so the `api` CNAME must be edited
by hand each time. The validation record does not. Options for later
(not done): a Route 53 hosted zone for the subdomain managed by Terraform /
ExternalDNS (~$0.50/month), or a registrar with an API. Manual is fine at this
scale.

### 3. Stale DNS on one machine
After fixing the CNAME, public resolvers (1.1.1.1, 8.8.8.8) returned the new
value but the local network resolver kept the old one, so `curl` failed with
"could not resolve host". Querying specific resolvers with `dig @1.1.1.1` and
using `curl --resolve api.steeze.ca:443:<ip>` separated "DNS cache" from "the
service is broken".

### 4. The Supabase free-tier project pauses itself
Three times the app returned 500 on signup. The pod logs showed
`FATAL: (ENOTFOUND) tenant/user postgres.<ref> not found` from the Supabase
pooler. That message means the project is **paused** (inactive about a week on
the free tier), not that the network or credentials are wrong - the pod reached
the pooler fine. Fix: restore the project in the Supabase dashboard. Testing the
connection from *inside the pod* (`kubectl exec ... python -c "psycopg.connect(...)"`)
is the quickest way to tell DB-down from app-bug.

### 5. The old ECS worker competed with the EKS worker
Rebuilding recreated the old ECS Fargate worker, which autoscales 0-3 on SQS
queue depth and reads the **same queue** as the KEDA-scaled EKS worker, with a
stale OpenAI key. Whichever worker grabs a message first processes (or fails) it.
Temporary fix: cap the ECS autoscaling target at 0. Permanent fix: Phase 5
deleted the ECS worker entirely.

### 6. Failed jobs keep the worker alive for ~45 minutes
A job that raises is not deleted from SQS (the handler marks the lecture
`failed`, re-raises, `poll()` skips `delete_message`). After the 900 s
visibility timeout it is redelivered; after `maxReceiveCount=3` it moves to the
DLQ. KEDA sees a non-empty queue the whole time, so the worker pod stays up.
Behaviour is intentional retry-on-error, but wasteful for permanent failures
(missing file, bad API key). Purge the queue after testing with fake keys.

### 7. The rebuild's two known races
`aws_eks_access_policy_association` 404s if created right after its access entry
(eventual consistency), and the Lambda failed because the image wasn't in ECR
yet. Re-running `terraform apply` clears both.

---

## Part 4 - Verification

```
dig +short CNAME api.steeze.ca @1.1.1.1      # -> current ALB hostname
curl https://api.steeze.ca/healthz            # {"status":"ok"} 200
curl -I http://<alb-hostname>/healthz         # 301 -> https
# through Vercel:
POST /auth/signup  -> 200, Set-Cookie: ...; HttpOnly; SameSite=none; Secure
GET  /auth/me, /subjects -> 200 with the cookie
POST /uploads/presign, POST /lectures -> 200
```
Certificate: `CN=api.steeze.ca`, issuer Amazon RSA 2048, valid ~13 months,
auto-renewing while the DNS validation record stays in place.

---

## Part 5 - Decision: this is a showcase, not the product

Partway through, the plan changed: real users will use a separate, cheaper
project (Vercel + a single Railway service, no AWS). This AWS/EKS stack stays as
the portfolio piece - brought up for demos, torn down otherwise - and shares
**nothing** with the product: separate database, storage, queue, keys and
frontend. `docs/RAILWAY_REBUILD_SPEC.md` is a self-contained spec for building
that version. Consequences for this stack: Phase 5 can proceed without a
production-soak period, and HTTPS here exists to demonstrate the full
production-grade setup rather than to serve users.
