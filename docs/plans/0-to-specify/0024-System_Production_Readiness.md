# DokoDetector System — Production Readiness

## Plan status

- **Summary:** Harden the proven pipeline for a defined deployment and supported devices
- **Status:** To Specify
- **Depends on:** Local integration, snippet transport, table-observation recognition, game
  reconstruction, and human-review measurements
- **Supersedes:** Plans 0017 and 0018 as active implementation plans
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## 1. Purpose

Select production work from measured product, reliability, privacy, performance, and operational
requirements. Do not implement a technology checklist before those inputs exist.

## 2. Required entry evidence

Record:

- supported game structures, round rulesets, player counts, and deck variants;
- supported iPhone and operating-system classes;
- inference, capture, snippet encoding, upload, recognition, and reconstruction latency distributions;
- frame and snippet package volume, storage growth, retry rate, and duplicate rate;
- model memory, accelerator, and throughput needs;
- expected concurrent games, recordings, and reprocessing volume;
- acceptable data-loss and recovery objectives;
- privacy, consent, retention, deletion, and regional requirements;
- ambiguity, focused-question, full-edit, and unresolved-review rates;
- expected reviewer volume, response time, and audit requirements;
- deployment environment and operator responsibilities;
- observed failure modes from long local and field trials.

If these values are unknown, run limited trials with the local design. Do not guess infrastructure.

## 3. Possible work areas

### iOS field reliability

The reference items in [plan 0017](../5-closed/0017-iOS_EvidenceUpload_ProductionReadiness.md) include
background transfer, relaunch reconciliation, durable
retry, storage limits, camera lifecycle, thermal behavior, production UI, and device validation.
Select only the items required for the supported product flow.

### Backend and analyzer operations

The reference items in [plan 0018](../5-closed/0018-Backend_EvidenceUpload_ProductionReadiness.md) include
shared persistence, deployment, authentication,
authorization, backup, restore, concurrency, metrics, and analyzer handoff. SQLite, local files,
in-process detection, a queue, a database server, and object storage are choices to evaluate from
load and recovery needs, not preset stages.

### Model lifecycle

Define bundle promotion, rollback, compatibility, monitoring, reprocessing, and retirement for
CardEventNet, TableEvidenceAnalyzer capabilities, and reconstruction weights. Preserve old raw
results, table observations, correction constraints, and reviewed reconstructions when models
change.

### Video evidence lifecycle

Use the measurements from plan 0025 to select snippet limits, queued storage, upload policy,
retention, encryption, playback authorization, and deletion behavior. Preserve selected frames as a
fallback. Do not assume that PoC encoding settings are production settings.

### Human review operations

Use plan 0026 measurements to define review roles, queue objectives, audit records, correction
authority, unresolved-case handling, and support workflows. Keep a complete local fixture-based
review path for recovery and testing.

### Data governance

Apply the plan 0020 lineage and permission model to production retention, user-visible deletion,
contributed training data, derived artifacts, backups, and external processors.

### End-to-end reliability

Test process loss, app backgrounding, network loss, partial storage failure, corrupt frames or
snippets, unavailable inference, model rollback, missing event proposals, observation-version
changes, reconstruction truncation, correction conflicts, low storage, and restore from backup.
Define service objectives before choosing acceptance thresholds.

## 4. Planning rule

When entry evidence exists, split this umbrella into small component plans with concrete acceptance
criteria. Keep the local, offline, fixture-driven development loop even if production uses cloud
services or dedicated accelerators.

Production readiness is complete only when the selected system meets documented product,
reliability, privacy, security, recovery, performance, and support requirements in its target
environment.
