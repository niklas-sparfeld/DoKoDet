import { useCallback, useMemo, useState } from "react";

import { createJobsClient } from "../api/jobsClient";
import type { EnqueueJobBody } from "../api/jobsContracts";
import type {
  PipelineCompatibleInputSet,
  PipelineWorkspaceStage,
} from "../api/pipelineContracts";
import styles from "../App.module.css";
import { JobStartActions } from "../jobs/JobStartActions";
import { AcceptedJobReceipt, useJobSubmission } from "../jobs/useJobSubmission";
import {
  buildObservationRequest,
  formatValue,
} from "./ObservationRunFormatting";

export type ObservationRunControlsProps = {
  recordingId: string;
  stage: PipelineWorkspaceStage;
  stages: PipelineWorkspaceStage[];
  onRefresh: () => Promise<void>;
};

const INPUT_ROLES = ["events", "visible_cards", "visual_identities"] as const;

export function ObservationRunControls({
  recordingId,
  stage,
  stages,
  onRefresh,
}: ObservationRunControlsProps) {
  const client = useMemo(() => createJobsClient(), []);
  const compatibleSets = (stage.compatible_input_sets ??
    []) as PipelineCompatibleInputSet[];
  const selectedDefaults = INPUT_ROLES.map((key) => {
    const upstream = stages.find((candidate) => candidate.key === key);
    return (
      upstream?.selected_completed_reference ??
      upstream?.selected_generated ??
      null
    );
  });
  const eventStage = stages.find((candidate) => candidate.key === "events");
  const selectedEventSet = eventStage?.selected_event_set_generated ?? null;
  const selectedEventReference =
    eventStage?.selected_event_set_reference ?? null;
  const matchingDefaults = compatibleSets.filter((candidate) => {
    if (candidate.input_event_set_ref != null) {
      const selected = selectedEventSet ?? selectedEventReference;
      return (
        selected !== null &&
        candidate.input_event_set_ref.set_id === selected.set_id &&
        candidate.input_event_set_ref.version === selected.version &&
        candidate.input_node_refs.every(
          (reference, index) =>
            reference.node_id === selectedDefaults[index + 1]?.node_id &&
            reference.revision_id === selectedDefaults[index + 1]?.revision_id,
        )
      );
    }
    return candidate.input_node_refs.every(
      (reference, index) =>
        reference.node_id === selectedDefaults[index]?.node_id &&
        reference.revision_id === selectedDefaults[index]?.revision_id,
    );
  });
  const defaultSet =
    matchingDefaults.length === 1
      ? matchingDefaults[0]
      : matchingDefaults.length === 0 && compatibleSets.length === 1
        ? compatibleSets[0]
        : null;
  const [selectedSetKey, setSelectedSetKey] = useState("");
  const [pendingRequest, setPendingRequest] = useState<EnqueueJobBody | null>(
    null,
  );
  const selectedSet = selectedSetKey
    ? (compatibleSets.find(
        (candidate) => JSON.stringify(candidate) === selectedSetKey,
      ) ?? null)
    : defaultSet;
  const validSet =
    selectedSet !== null &&
    (selectedSet.input_event_set_ref != null
      ? selectedSet.input_node_refs.length === 2
      : selectedSet.input_node_refs.length === INPUT_ROLES.length) &&
    new Set(selectedSet.input_node_refs.map((reference) => reference.node_id))
      .size === selectedSet.input_node_refs.length &&
    new Set(
      selectedSet.input_node_refs.map((reference) => reference.revision_id),
    ).size === INPUT_ROLES.length;
  const enqueue = useCallback(
    (payload: EnqueueJobBody, key: string) => client.enqueueJob(payload, key),
    [client],
  );
  const submission = useJobSubmission(enqueue);
  const uncertain =
    submission.error?.startsWith("Acceptance is uncertain") ?? false;
  const latestRun = stage.runs[0] ?? null;
  const action = {
    id: "assemble-table-observations",
    label: "Assemble table observations",
    description:
      "Create a fresh table-observation revision from one compatible set of exact event, visible-card, and visual-identity revisions.",
    expectedOutput:
      "A new table-observation data revision with all three exact input revisions retained in its lineage.",
    sections: [
      {
        title: "Exact input revisions",
        content: (
          <>
            <label className={styles.pipelineRunSelector}>
              <span>Compatible input set</span>
              <select
                aria-label="Compatible input set"
                value={selectedSet ? JSON.stringify(selectedSet) : ""}
                disabled={uncertain}
                onChange={(event) => setSelectedSetKey(event.target.value)}
              >
                <option value="">Select a compatible input set</option>
                {compatibleSets.map((candidate) => (
                  <option
                    key={JSON.stringify(candidate)}
                    value={JSON.stringify(candidate)}
                  >
                    {candidate.display_label}
                  </option>
                ))}
              </select>
            </label>
            {selectedSet ? (
              <dl>
                {selectedSet.input_event_set_ref != null ? (
                  <div key="events">
                    <dt>events</dt>
                    <dd>
                      {selectedSet.input_event_set_ref.set_id}@
                      {selectedSet.input_event_set_ref.version} · SHA-256{" "}
                      {selectedSet.input_event_set_ref.content_sha256.slice(
                        0,
                        12,
                      )}
                    </dd>
                  </div>
                ) : null}
                {selectedSet.input_node_refs.map((reference, index) => (
                  <div key={`${reference.node_id}:${reference.revision_id}`}>
                    <dt>
                      {INPUT_ROLES[
                        index +
                          (selectedSet.input_event_set_ref != null ? 1 : 0)
                      ] ?? `Input ${index + 1}`}
                    </dt>
                    <dd>
                      {reference.node_id}@{reference.revision_id} ·{" "}
                      {reference.revision_policy}
                    </dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p>
                No compatible event, visible-card, and visual-identity input set
                is available.
              </p>
            )}
          </>
        ),
      },
      {
        title: "Assembly configuration",
        content: (
          <dl>
            <div>
              <dt>Implementation</dt>
              <dd>
                {latestRun?.implementation.name ?? "observation-assembler"} ·{" "}
                {latestRun?.implementation.version ?? "v1"}
              </dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd>{formatValue(latestRun?.model ?? null)}</dd>
            </div>
            <div>
              <dt>Configuration</dt>
              <dd>{formatValue(latestRun?.configuration ?? {})}</dd>
            </div>
            <div>
              <dt>Extraction policy</dt>
              <dd>
                {formatValue(
                  latestRun?.extraction_policy ?? {
                    policy_id: "exact-event/v1",
                  },
                )}
              </dd>
            </div>
          </dl>
        ),
      },
    ],
  };
  const errors = [
    ...(submission.error ? [submission.error] : []),
    ...stage.run_blockers,
    ...(!validSet
      ? [
          "Select a compatible event, visible-card, and visual-identity revision set.",
        ]
      : []),
  ];

  return (
    <section
      className={styles.pipelineRunControls}
      aria-label="Table observation actions"
    >
      <JobStartActions
        actions={[action]}
        submitting={submission.submitting}
        validationErrors={errors}
        canSubmit={validSet && stage.can_run && stage.run_blockers.length === 0}
        onStart={async () => {
          if (uncertain && pendingRequest !== null) {
            const accepted = await submission.submit(pendingRequest);
            if (!accepted) return false;
            setPendingRequest(null);
            await onRefresh();
            return true;
          }
          if (!selectedSet || !validSet) return false;
          const request: EnqueueJobBody = {
            type: "table_observation_assembly",
            context: { recording_id: recordingId },
            request: buildObservationRequest(
              createId(),
              selectedSet.input_node_refs,
              latestRun,
              selectedSet.input_event_set_ref,
            ).request as Record<string, unknown>,
          };
          setPendingRequest(request);
          const accepted = await submission.submit(request);
          if (!accepted) return false;
          setPendingRequest(null);
          await onRefresh();
          return true;
        }}
      />
      {submission.job ? <AcceptedJobReceipt job={submission.job} /> : null}
    </section>
  );
}

function createId(): string {
  return `observation-run-${crypto.randomUUID()}`;
}
