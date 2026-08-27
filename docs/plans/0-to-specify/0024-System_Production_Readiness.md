# DokoDetector System — Production Readiness

## Plan status

- **Summary:** Harden the proven pipeline for a defined deployment and supported devices
- **Status:** To Specify
- **Depends on:** Local integration, recognition development, and game reconstruction measurements
- **Supersedes:** Plans 0017 and 0018 as active implementation plans

## 1. Purpose

Select production work from measured product, reliability, privacy, performance, and operational
requirements. Do not implement a technology checklist before those inputs exist.

## 2. Required entry evidence

Record:

- supported game structures, round rulesets, player counts, and deck variants;
- supported iPhone and operating-system classes;
- inference, capture, upload, recognition, and reconstruction latency distributions;
- package volume, storage growth, retry rate, and duplicate rate;
- model memory, accelerator, and throughput needs;
- expected concurrent games, recordings, and reprocessing volume;
- acceptable data-loss and recovery objectives;
- privacy, consent, retention, deletion, and regional requirements;
- deployment environment and operator responsibilities;
- observed failure modes from long local and field trials.

If these values are unknown, run limited trials with the local design. Do not guess infrastructure.

## 3. Possible work areas

### iOS field reliability

The reference items in [plan 0017](../5-closed/0017-iOS_EvidenceUpload_ProductionReadiness.md) include
background transfer, relaunch reconciliation, durable
retry, storage limits, camera lifecycle, thermal behavior, production UI, and device validation.
Select only the items required for the supported product flow.

### Backend and detector operations

The reference items in [plan 0018](../5-closed/0018-Backend_EvidenceUpload_ProductionReadiness.md) include
shared persistence, deployment, authentication,
authorization, backup, restore, concurrency, metrics, and detector handoff. SQLite, local files,
in-process detection, a queue, a database server, and object storage are choices to evaluate from
load and recovery needs, not preset stages.

### Model lifecycle

Define bundle promotion, rollback, compatibility, monitoring, reprocessing, and retirement for
CardEventNet and VisionDetector. Preserve old raw results when models change.

### Data governance

Apply the plan 0020 lineage and permission model to production retention, user-visible deletion,
contributed training data, derived artifacts, backups, and external processors.

### End-to-end reliability

Test process loss, app backgrounding, network loss, partial storage failure, corrupt evidence,
unavailable inference, model rollback, missing event proposals, low storage, and restore from
backup. Define service objectives before choosing acceptance thresholds.

## 4. Planning rule

When entry evidence exists, split this umbrella into small component plans with concrete acceptance
criteria. Keep the local, offline, fixture-driven development loop even if production uses cloud
services or dedicated accelerators.

Production readiness is complete only when the selected system meets documented product,
reliability, privacy, security, recovery, performance, and support requirements in its target
environment.
