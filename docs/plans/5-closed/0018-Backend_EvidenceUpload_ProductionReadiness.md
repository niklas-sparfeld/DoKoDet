# DokoDetector Backend Evidence Upload — Production Readiness

## Plan status

- **Summary:** Reassess and harden the local evidence-ingestion PoC
- **Status:** Closed
- **Closure reason:** Superseded by [plan 0024](../0-to-specify/0024-System_Production_Readiness.md)
- **Starts after:** [Plan 0004](0004-Backend_EvidenceUpload.md) and the iOS/backend local integration
  in [plan 0016](../4-blocked/0016-iOS_EvidenceUpload_Integration.md)
- **Disposition:** Keep this document as a backend hardening reference. Select concrete work only
  after local pipeline and recognition measurements exist.

## 1. Purpose

Turn the proven local ingestion slice into a production service if product requirements call for
one.

This plan is intentionally short. Plan 0004 must first show real package sizes, upload behavior,
failure modes, and development needs. Those results should determine the production design.

## 2. Entry evidence

Before implementation, record:

- expected packages per game and concurrent games;
- observed package and frame sizes;
- retry and duplicate rates from the iOS integration;
- acceptable upload latency and data-loss risk;
- retention, deletion, privacy, and regional requirements;
- detector handoff and reprocessing needs;
- deployment environment and operator constraints.

If these values are not known, run a limited trial with the local design. Do not select
infrastructure from guesses.

## 3. Possible work areas

### Storage and concurrency

Decide whether SQLite and local files still meet the measured needs. If they do not, evaluate a
shared relational database and an object store. PostgreSQL and S3-compatible storage are candidates,
not preset requirements.

Define migration, rollback, consistency, backup, restore, and concurrent-ingest behavior only after
the storage choice is made.

### Deployment and operations

Choose a deployment shape that fits the target environment. Containers may help, but this plan does
not require Docker or a specific cloud.

Add health checks, structured logs, metrics, alerts, and runbooks for the chosen deployment. Keep the
container-free local loop from plan 0004.

### Security and data lifecycle

Add the authentication, authorization, transport, secret-management, rate-limit, audit, retention,
and deletion controls required by the product and its data classification.

### Reliability

Define service-level objectives. Then test the failure cases that threaten them, such as process
loss, partial storage failure, concurrent retries, unavailable dependencies, and restore from backup.

### Detector handoff

Integrate with [plan 0005](../3-in-progress/0005-VisionDetector_v1.md) only after its input and result contracts
exist. Decide whether detector work runs in-process, in a separate worker, or in another service
from measured latency, resource, and retry needs. Do not add a queue or broker by default.

## 4. Suggested sequence

1. Write a short requirements and measurement report.
2. Select the smallest architecture that meets those requirements.
3. Add contract tests for any replacement persistence adapters.
4. Migrate without changing the V1 HTTP behavior unless a new contract version is justified.
5. Add security, operations, and failure-recovery checks for the selected deployment.
6. Run an iOS-to-storage trial and document the result.

Each step should become its own concrete implementation plan when its inputs are known.

## 5. Completion condition

Production readiness is complete only when the selected service meets documented product,
security, reliability, recovery, and operational requirements in its target environment.

Do not use a checklist of technologies as proof of readiness.
