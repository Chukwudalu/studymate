# StudyMate

Record or upload a lecture and get a transcript, topic-segmented notes, flashcards,
a multiple-choice quiz, and a chat assistant that answers questions from your notes.

This repository is also a **cloud-infrastructure portfolio project**: the app was
migrated from AWS Lambda + ECS Fargate to a Kubernetes (EKS) deployment, split into
microservices, and delivered with Terraform, Helm and GitHub Actions - with every
bug found on the way written up in [`docs/eks-migration/`](docs/eks-migration/).

> **The AWS deployment is torn down between demos to avoid paying for an idle
> cluster.** It rebuilds from scratch in roughly 20 minutes (see
> [`docs/eks-migration/HANDOFF.md`](docs/eks-migration/HANDOFF.md)). Screenshots /
> a demo recording are the reliable way to see it running.

## Architecture

```
                     Vercel (React + Vite SPA)
                              |  rewrites /auth /lectures /subjects /uploads
                              v
              https://api.steeze.ca  (ACM certificate, DNS CNAME)
                              |
                  AWS Application Load Balancer
          (created by the AWS Load Balancer Controller from an Ingress)
                    |                          |
              path /auth                  path /  (everything else)
                    v                          v
              auth-service                  core-api
        signup / login / reset / me     lecture CRUD, S3 presign, chat,
        (Supabase only, no AWS IAM)     enqueue jobs (S3 + SQS via IRSA)
                    \                          |
                     \                         v
                      \                 Amazon SQS queue
                       \                       |
                        \               KEDA scales 0 -> 3
                         \                     v
                          \                  worker
                           \        SQS consumer + LangGraph pipelines
                            \       (S3 + SQS via IRSA)
                             v                 |
                       Supabase Postgres  <----+
                                               |
                          OpenAI Whisper  +  Anthropic Claude
```

**EKS cluster:** one always-on `t3.small` managed node group for system pods;
**Karpenter** adds and removes EC2 nodes on demand; **KEDA** scales the worker
from zero based on SQS queue depth; each service has its own least-privilege IAM
role via **IRSA** (auth-service has none).

## What this project demonstrates

| Area | What was done |
|---|---|
| **Kubernetes / EKS** | Cluster, managed node group with a pinned launch template, Karpenter autoscaling, KEDA scale-to-zero, AWS Load Balancer Controller, IRSA |
| **Terraform** | ~68 resources: EKS, IAM/IRSA, OIDC, ACM, ECR, S3, SQS, security groups. Clean `apply`/`destroy` cycles, in-cluster resources protected with explicit `depends_on` |
| **Helm** | Umbrella chart with a subchart per service, conditional HTTPS ingress |
| **CI/CD** | GitHub Actions: tests, build/push 3 images over **OIDC (no stored AWS keys)**, `helm upgrade` under a **namespace-scoped, least-privilege** EKS access entry, Vercel deploy |
| **Security** | HttpOnly + Secure session cookies, bcrypt, scoped RBAC (extra `Role` for KEDA CRDs only), no secrets in Terraform |
| **Networking / TLS** | ACM certificate with DNS validation, HTTP->HTTPS redirect, Namecheap DNS |
| **Application** | FastAPI services, LangGraph pipelines, React + TypeScript frontend (responsive, in-browser recorder with live level meter) |
| **Debugging** | Real incidents documented: SG mismatch between node groups, UDP-vs-TCP DNS, CRD RBAC gaps, orphaned Karpenter nodes blocking `destroy`, etc. |

## Repository layout

```
apps/
  auth_service/   FastAPI - authentication
  core_api/       FastAPI - lectures, uploads, chat, job enqueueing
  worker/         SQS consumer running the pipelines
  web/            React + Vite frontend (deployed to Vercel)
services/pipeline/   LangGraph graphs: transcribe -> segment -> notes; flashcards; quiz
packages/            shared pydantic schemas and JWT helpers
charts/studymate/    Helm umbrella chart (auth-service, core-api, worker subcharts)
terraform/           EKS, IAM, OIDC, ACM, ECR, S3, SQS
.github/workflows/   CI (tests + build) and Deploy (images + helm + frontend)
docs/eks-migration/  per-phase write-ups and the session handoff
docs/RAILWAY_REBUILD_SPEC.md   spec for a cheaper non-AWS deployment of the same app
```

## The migration, phase by phase

1. [Phase 0 - cluster bootstrap](docs/eks-migration/phase-0-cluster-bootstrap.md): EKS, Karpenter, KEDA, ALB controller
2. [Phase 1 - service split](docs/eks-migration/phase-1-service-split.md): one API -> `auth-service` + `core-api`
3. [Phase 2 - Helm deploy](docs/eks-migration/phase-2-helm-deploy.md): charts, real ALB, end-to-end verification
4. [Phase 3 - CI/CD](docs/eks-migration/phase-3-cicd.md): OIDC, least-privilege deploys
5. [Phase 4 - HTTPS and domain](docs/eks-migration/phase-4-https-domain.md): ACM, DNS, secure cookies
6. [Phase 5 - decommission](docs/eks-migration/phase-5-decommission.md): removing Lambda/ECS safely

## Running the AWS deployment

Short version (full commands in the handoff): `terraform apply` (CRD file disabled
for the first pass), push the three images to ECR, re-enable the CRD file and apply
again, update the ALB security group and ACM ARN in `charts/studymate/values.yaml`,
create the `studymate-secrets` Secret, `helm upgrade --install`, then point the
`api` DNS record at the new ALB hostname. Teardown order matters (delete the Ingress
and Karpenter nodes before `terraform destroy`) and is documented step by step.

## Tech stack

Python 3.13, FastAPI, psycopg, LangGraph, OpenAI Whisper, Anthropic Claude, React 19,
TypeScript, Vite, Supabase Postgres, Docker, Kubernetes (EKS), Karpenter, KEDA, Helm,
Terraform, GitHub Actions, Vercel.
