import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  createDokoDetectorClient,
  type CalibrationRefinementResponse,
  type PipelineReferenceOperation,
  type PipelineReferenceResource,
  type PipelineProposalRunResponse,
} from "../api/client";
import {
  describeCommand,
  describeError,
} from "./PipelineVisibleCardFormatting";
import type {
  EditableFrame,
  PendingCommand,
  SaveState,
} from "./PipelineVisibleCardTypes";
import {
  coverageEntries,
  frameCoverageKey,
  frameCoverageKeyFromIdentity,
  frameDecision,
  readFramesFromResult,
  readProposalInputRevisionId,
  readProposalRevisionId,
  toEditableFrame,
} from "./PipelineVisibleCardData";
import {
  withCalibrationAnchorCommandDigest,
  type CalibrationAnchorCommand,
} from "./PoseBasedVisibleCardScene";

const CONTENT_TYPE = "visible_cards" as const;
const RETRY_LIMIT = 3;

type Client = ReturnType<typeof createDokoDetectorClient>;

type ControllerInput = {
  client?: Client;
  recordingId: string;
  operatorId: string;
  generatedRevisionId: string | null;
  generatedSourceRevisionId: string | null;
  proposalRevisionId: string | null;
  proposalRun: PipelineProposalRunResponse | null;
  referenceRef: { current: PipelineReferenceResource | null };
  serverRevisionRef: { current: number };
  getFrames: () => EditableFrame[];
  setLocalFrames: (frames: EditableFrame[]) => void;
  selectedFrameIdRef: { current: string | null };
  inspectedFrameKeysRef: { current: Set<string> };
  setInspectedFrameKeys: (keys: Set<string>) => void;
  completionBusy: boolean;
  saveState: SaveState;
  setSaveState: (state: SaveState) => void;
  setError: (error: string | null) => void;
  setNotice: (notice: string | null) => void;
  setRebasingReference: (busy: boolean) => void;
  setRebasingProposal: (busy: boolean) => void;
  generatedRunId: string | null;
  setGeneratedFrames: (frames: EditableFrame[]) => void;
  setGeneratedLoading: (loading: boolean) => void;
  setLoading: (loading: boolean) => void;
  setReference: (reference: PipelineReferenceResource | null) => void;
  setSelected: (itemId: string | null) => void;
  setProposalRun: (run: PipelineProposalRunResponse | null) => void;
  setProposalRevisionId: (revisionId: string | null) => void;
  setProposalLoading: (loading: boolean) => void;
  setProposalError: (error: string | null) => void;
  setCalibrationRefinement: (
    refinement: CalibrationRefinementResponse | null,
  ) => void;
  calibrationRefinementRef: {
    current: CalibrationRefinementResponse | null;
  };
  setCalibrationLoading: (loading: boolean) => void;
  setCalibrationError: (error: string | null) => void;
  setCreatingReference: (creating: boolean) => void;
  setCompletionBusy: (busy: boolean) => void;
  setReviewerId: (update: (current: string) => string) => void;
  calibrationProposalRevisionId: string | null;
};

export function usePipelineVisibleCardEditorController(input: ControllerInput) {
  const client = useMemo(
    () => input.client ?? createDokoDetectorClient(),
    [input.client],
  );
  const inputRef = useRef({ ...input, client });
  useEffect(() => {
    inputRef.current = { ...input, client } as ControllerInput & {
      client: Client;
    };
  });
  const hydrateReference = useCallback(
    (nextReference: PipelineReferenceResource, preserveSelection = true) => {
      const current = inputRef.current;
      const nextFrames = nextReference.draft.items
        .map(toEditableFrame)
        .filter((frame): frame is EditableFrame => frame !== null);
      current.referenceRef.current = nextReference;
      current.serverRevisionRef.current = nextReference.draft.revision;
      current.setReference(nextReference);
      current.setLocalFrames(nextFrames);
      if (!preserveSelection) {
        current.inspectedFrameKeysRef.current = new Set();
        current.setInspectedFrameKeys(new Set());
      }
      for (const entry of coverageEntries(nextReference.draft.coverage)) {
        current.inspectedFrameKeysRef.current.add(
          frameCoverageKeyFromIdentity(entry.frame_identity, entry.item_id),
        );
      }
      for (const frame of nextFrames) {
        if (frameDecision(frame) !== null) {
          current.inspectedFrameKeysRef.current.add(frameCoverageKey(frame));
        }
      }
      current.setInspectedFrameKeys(
        new Set(current.inspectedFrameKeysRef.current),
      );
      const selectedId = preserveSelection
        ? current.selectedFrameIdRef.current
        : null;
      const selected =
        nextFrames.find((frame) => frame.itemId === selectedId) ??
        nextFrames[0];
      current.setSelected(selected?.itemId ?? null);
    },
    [],
  );
  const queueRef = useRef<PendingCommand[]>([]);
  const processingRef = useRef(false);
  const processQueueRef = useRef<(() => void) | null>(null);
  const retryTimerRef = useRef<number | null>(null);
  const commandSequenceRef = useRef(0);
  const [queueLength, setQueueLength] = useState(0);
  const [firstUnappliedCommand, setFirstUnappliedCommand] = useState<
    string | null
  >(null);
  const calibrationCommandQueueRef = useRef<Promise<void>>(Promise.resolve());
  const calibrationCommandsPendingRef = useRef(0);

  const loadCalibrationRefinement = useCallback(async () => {
    const current = inputRef.current;
    if (current.calibrationProposalRevisionId === null) {
      current.setCalibrationRefinement(null);
      current.calibrationRefinementRef.current = null;
      return;
    }
    try {
      const loaded = await current.client.getCalibrationRefinement(
        current.recordingId,
        current.calibrationProposalRevisionId,
      );
      const latest = current.calibrationRefinementRef.current;
      if (
        latest !== null &&
        latest.proposal_revision_id === loaded.proposal_revision_id &&
        latest.draft.draft_id === loaded.draft.draft_id &&
        typeof latest.draft.revision === "number" &&
        typeof loaded.draft.revision === "number" &&
        latest.draft.revision > loaded.draft.revision
      )
        return;
      current.calibrationRefinementRef.current = loaded;
      current.setCalibrationRefinement(loaded);
      current.setCalibrationError(null);
    } catch (reason: unknown) {
      if (reason instanceof ApiError && reason.status === 404) {
        current.setCalibrationRefinement(null);
        current.calibrationRefinementRef.current = null;
        current.setCalibrationError(null);
      } else current.setCalibrationError(describeError(reason));
    }
  }, []);

  const startCalibrationRefinement = useCallback(async () => {
    const current = inputRef.current;
    if (current.calibrationProposalRevisionId === null) return;
    current.setCalibrationLoading(true);
    current.setCalibrationError(null);
    try {
      const started = await current.client.startCalibrationRefinement(
        current.recordingId,
        { proposal_revision_id: current.calibrationProposalRevisionId },
      );
      current.calibrationRefinementRef.current = started;
      current.setCalibrationRefinement(started);
    } catch (reason: unknown) {
      current.setCalibrationError(describeError(reason));
    } finally {
      current.setCalibrationLoading(false);
    }
  }, []);

  const refreshCalibrationPreview = useCallback(async () => {
    const current = inputRef.current;
    const refinement = current.calibrationRefinementRef.current;
    const proposalRevisionId = current.calibrationProposalRevisionId;
    const draftId = refinement?.draft.draft_id;
    if (proposalRevisionId === null || typeof draftId !== "string") return;
    current.setCalibrationLoading(true);
    current.setCalibrationError(null);
    try {
      const refreshed = await current.client.startCalibrationRefinement(
        current.recordingId,
        {
          proposal_revision_id: proposalRevisionId,
          draft_id: draftId,
        },
      );
      current.calibrationRefinementRef.current = refreshed;
      current.setCalibrationRefinement(refreshed);
    } catch (reason: unknown) {
      current.setCalibrationError(describeError(reason));
    } finally {
      current.setCalibrationLoading(false);
    }
  }, []);

  const updateCalibrationAnchor = useCallback(
    (command: CalibrationAnchorCommand) => {
      calibrationCommandsPendingRef.current += 1;
      inputRef.current.setCalibrationLoading(true);
      inputRef.current.setCalibrationError(null);
      const operation = calibrationCommandQueueRef.current
        .catch(() => undefined)
        .then(async () => {
          const current = inputRef.current;
          const refinement = current.calibrationRefinementRef.current;
          const draftId = refinement?.draft.draft_id;
          const revision = refinement?.draft.revision;
          if (
            refinement === null ||
            typeof draftId !== "string" ||
            typeof revision !== "number"
          ) {
            current.setCalibrationError(
              "Start a mapping preview before changing calibration anchors.",
            );
            calibrationCommandsPendingRef.current -= 1;
            current.setCalibrationLoading(
              calibrationCommandsPendingRef.current > 0,
            );
            return false;
          }
          const sequence = Array.isArray(refinement.draft.commands)
            ? refinement.draft.commands.length + 1
            : 1;
          const orderedCommand = {
            ...command,
            command_id: `${command.command_id}-${sequence}`,
            sequence,
            expected_draft_revision: revision,
          };
          try {
            const digested =
              await withCalibrationAnchorCommandDigest(orderedCommand);
            const updated = await current.client.updateCalibrationRefinement(
              current.recordingId,
              refinement.proposal_revision_id,
              {
                draft_id: draftId,
                expected_revision: revision,
                command: digested,
              },
            );
            current.calibrationRefinementRef.current = updated;
            current.setCalibrationRefinement(updated);
            return true;
          } catch (reason: unknown) {
            current.setCalibrationError(describeError(reason));
            return false;
          } finally {
            calibrationCommandsPendingRef.current -= 1;
            current.setCalibrationLoading(
              calibrationCommandsPendingRef.current > 0,
            );
          }
        });
      calibrationCommandQueueRef.current = operation.then(() => undefined);
      return operation;
    },
    [],
  );

  const discardCalibrationRefinement = useCallback(async () => {
    const current = inputRef.current;
    const refinement = current.calibrationRefinementRef.current;
    const draftId = refinement?.draft.draft_id;
    if (refinement === null || typeof draftId !== "string") return;
    current.setCalibrationLoading(true);
    current.setCalibrationError(null);
    try {
      const reset = await current.client.discardCalibrationRefinement(
        current.recordingId,
        {
          proposal_revision_id: refinement.proposal_revision_id,
          draft_id: draftId,
        },
      );
      current.calibrationRefinementRef.current = reset;
      current.setCalibrationRefinement(reset);
    } catch (reason: unknown) {
      current.setCalibrationError(describeError(reason));
    } finally {
      current.setCalibrationLoading(false);
    }
  }, []);

  const applyCalibrationRefinement = useCallback(
    async (confirmAffected: boolean) => {
      const current = inputRef.current;
      const refinement = current.calibrationRefinementRef.current;
      if (refinement === null) return;
      const draftId = refinement.draft.draft_id;
      const revision = refinement.draft.revision;
      const previewDigest = refinement.preview.preview_digest;
      if (
        typeof draftId !== "string" ||
        typeof revision !== "number" ||
        typeof previewDigest !== "string"
      ) {
        current.setCalibrationError(
          "The calibration preview is incomplete. Reload it and try again.",
        );
        return;
      }
      current.setCalibrationLoading(true);
      current.setCalibrationError(null);
      try {
        const applied = await current.client.applyCalibrationRefinement(
          current.recordingId,
          refinement.proposal_revision_id,
          {
            draft_id: draftId,
            expected_revision: revision,
            preview_digest: previewDigest,
            operator_id: current.operatorId.trim() || "operator",
            confirm_affected: confirmAffected,
          },
        );
        current.setProposalRevisionId(applied.proposal_revision_id);
        hydrateReference(applied.reference);
        current.setCalibrationRefinement(null);
        current.calibrationRefinementRef.current = null;
        current.setNotice(
          `Applied calibration ${applied.calibration_revision_id}; review affected frames before completion.`,
        );
      } catch (reason: unknown) {
        current.setCalibrationError(describeError(reason));
      } finally {
        current.setCalibrationLoading(false);
      }
    },
    [hydrateReference],
  );

  const createReference = useCallback(async () => {
    const current = inputRef.current;
    if (current.operatorId.trim() === "") return;
    current.setCreatingReference(true);
    current.setError(null);
    try {
      const proposalRevisionId = current.proposalRevisionId;
      const sourceRevisionId = current.generatedSourceRevisionId;
      const created = await current.client.createPipelineReference(
        current.recordingId,
        CONTENT_TYPE,
        {
          operator_id: current.operatorId.trim(),
          seed:
            proposalRevisionId !== null
              ? "proposal"
              : sourceRevisionId === null
                ? "empty"
                : "selected_generated",
          ...(proposalRevisionId !== null
            ? { proposal_revision_id: proposalRevisionId }
            : sourceRevisionId === null
              ? {}
              : { source_revision_id: sourceRevisionId }),
        },
      );
      hydrateReference(created, false);
      current.setReviewerId(
        (reviewer) => reviewer || current.operatorId.trim(),
      );
      current.setNotice(
        proposalRevisionId !== null
          ? "Maintained visible-card review started from the preserved proposal."
          : "Maintained visible-card reference created from the selected generated result.",
      );
    } catch (reason: unknown) {
      if (reason instanceof ApiError && reason.status === 409) {
        try {
          const winning = await current.client.getPipelineReference(
            current.recordingId,
            CONTENT_TYPE,
          );
          hydrateReference(winning);
          current.setSaveState("saved");
          current.setError(null);
        } catch (reloadReason: unknown) {
          current.setError(describeError(reloadReason));
        }
      } else current.setError(describeError(reason));
    } finally {
      current.setCreatingReference(false);
    }
  }, [hydrateReference]);

  const completeReference = useCallback(
    async (reviewerId: string) => {
      const current = inputRef.current;
      const reference = current.referenceRef.current;
      const currentFrames = current.getFrames();
      if (reference === null) return;
      current.setCompletionBusy(true);
      current.setSaveState("saving");
      try {
        const stalePoseFrames = currentFrames.filter((frame) => {
          const scene = frame.outcome.card_scene;
          return (
            scene?.completion_state === "complete" &&
            scene.scene.poses.length !== frame.outcome.candidates.length
          );
        });
        for (const frame of stalePoseFrames) {
          const refreshed = await current.client.updatePipelineReferenceDraft(
            current.recordingId,
            CONTENT_TYPE,
            {
              expected_revision: current.serverRevisionRef.current,
              operator_id: reviewerId.trim() || current.operatorId.trim(),
              command_id: `pipeline-visible-card-completion-${Date.now()}`,
              operations: [
                {
                  operation: "accept_frame_suggestions",
                  item_id: frame.itemId,
                },
              ],
            },
          );
          hydrateReference(refreshed);
        }
        const framesForCoverage = current.getFrames();
        const completed = await current.client.completePipelineReference(
          current.recordingId,
          CONTENT_TYPE,
          {
            expected_revision: current.serverRevisionRef.current,
            operator_id: reviewerId.trim(),
            coverage: {
              kind: "visible_frames",
              frames: framesForCoverage.map((frame) => ({
                item_id: frame.itemId,
                frame_identity: frame.outcome.frame_identity,
                decision: frameDecision(frame) as
                  | "cards"
                  | "ignored"
                  | "cards_and_ignored"
                  | "empty"
                  | "unusable",
              })),
            },
          },
        );
        hydrateReference(completed, false);
        current.setSaveState("saved");
        current.setNotice(
          `Completed reference ${completed.state.selected_completed_revision_id ?? "published"} is immutable.`,
        );
      } catch (reason: unknown) {
        current.setSaveState(
          reason instanceof ApiError && reason.status === 409
            ? "conflict"
            : "error",
        );
        current.setError(describeError(reason));
      } finally {
        current.setCompletionBusy(false);
      }
    },
    [hydrateReference],
  );

  const loadGenerated = useCallback(async (signal?: AbortSignal) => {
    const current = inputRef.current;
    const revisionId = current.generatedSourceRevisionId;
    if (current.generatedRunId === null || revisionId === null) {
      current.setGeneratedFrames([]);
      current.setGeneratedLoading(false);
      return;
    }
    current.setGeneratedLoading(true);
    try {
      const result = await current.client.getVisibleCardResult(
        current.recordingId,
        current.generatedRunId,
        { signal },
      );
      if (!signal?.aborted) {
        current.setGeneratedFrames(readFramesFromResult(result, revisionId));
      }
    } catch (reason: unknown) {
      if (!signal?.aborted) current.setError(describeError(reason));
    } finally {
      if (!signal?.aborted) current.setGeneratedLoading(false);
    }
  }, []);

  const loadReference = useCallback(
    async (signal?: AbortSignal) => {
      const current = inputRef.current;
      current.setLoading(true);
      try {
        const loaded = await current.client.getPipelineReference(
          current.recordingId,
          CONTENT_TYPE,
          { signal },
        );
        if (!signal?.aborted) {
          hydrateReference(loaded);
          current.setSaveState("saved");
          current.setError(null);
        }
      } catch (reason: unknown) {
        if (!signal?.aborted) {
          if (reason instanceof ApiError && reason.status === 404) {
            current.referenceRef.current = null;
            current.setReference(null);
            current.setLocalFrames([]);
            current.setSelected(null);
            current.setError(null);
          } else {
            current.setError(describeError(reason));
          }
        }
      } finally {
        if (!signal?.aborted) current.setLoading(false);
      }
    },
    [hydrateReference],
  );

  const loadProposalRun = useCallback(async (signal?: AbortSignal) => {
    const current = inputRef.current;
    if (current.generatedSourceRevisionId === null) {
      current.setProposalRun(null);
      current.setProposalRevisionId(null);
      return;
    }
    current.setProposalLoading(true);
    current.setProposalError(null);
    try {
      const response = await current.client.listProposedCardSceneRuns(
        current.recordingId,
        { signal },
      );
      const matching = (Array.isArray(response.runs) ? response.runs : [])
        .filter(
          (run) =>
            readProposalInputRevisionId(run) ===
            current.generatedSourceRevisionId,
        )
        .at(-1);
      if (matching === undefined) {
        if (!signal?.aborted) {
          current.setProposalRun(null);
          current.setProposalRevisionId(null);
        }
      } else if (!signal?.aborted) {
        current.setProposalRun(matching);
        current.setProposalRevisionId(readProposalRevisionId(matching));
      }
    } catch {
      // Proposal history is optional for older recordings.
    } finally {
      if (!signal?.aborted) current.setProposalLoading(false);
    }
  }, []);

  const refreshProposalRun = useCallback(
    async (runId: string, signal?: AbortSignal) => {
      const current = inputRef.current;
      try {
        const run = await current.client.getProposedCardSceneRun(
          current.recordingId,
          runId,
          { signal },
        );
        if (signal?.aborted) return null;
        current.setProposalRun(run);
        current.setProposalRevisionId(readProposalRevisionId(run));
        return run;
      } catch (reason: unknown) {
        if (!signal?.aborted) current.setProposalError(describeError(reason));
        return null;
      }
    },
    [],
  );

  const startProposal = useCallback(async () => {
    const current = inputRef.current;
    const revisionId = current.generatedSourceRevisionId;
    if (revisionId === null) return;
    current.setProposalLoading(true);
    current.setProposalError(null);
    try {
      const run = await current.client.startProposedCardSceneRun(
        current.recordingId,
        {
          run_id: `card-scene-proposal-${Date.now()}`,
          visible_card_revision_id: revisionId,
        },
      );
      current.setProposalRun(run);
      current.setProposalRevisionId(readProposalRevisionId(run));
      current.setNotice(
        run.status === "complete"
          ? "Proposed card scenes are ready to inspect."
          : `Proposal run ${run.status}.`,
      );
    } catch (reason: unknown) {
      current.setProposalError(describeError(reason));
    } finally {
      current.setProposalLoading(false);
    }
  }, []);

  const retryProposal = useCallback(async () => {
    const current = inputRef.current;
    const run = current.proposalRun;
    if (run === null || (run.status !== "failed" && run.status !== "partial"))
      return;
    current.setProposalLoading(true);
    current.setProposalError(null);
    try {
      const retried = await current.client.retryProposedCardSceneRun(
        current.recordingId,
        run.run_id,
      );
      current.setProposalRun(retried);
      current.setProposalRevisionId(readProposalRevisionId(retried));
      current.setNotice("Proposal run retried.");
    } catch (reason: unknown) {
      current.setProposalError(describeError(reason));
    } finally {
      current.setProposalLoading(false);
    }
  }, []);

  const nextCommandId = useCallback(() => {
    commandSequenceRef.current += 1;
    return `pipeline-visible-card-${Date.now()}-${commandSequenceRef.current}`;
  }, []);

  const processQueue = useCallback(async () => {
    const current = inputRef.current;
    if (processingRef.current || queueRef.current.length === 0) {
      if (queueRef.current.length === 0) {
        setQueueLength(0);
        setFirstUnappliedCommand(null);
        if (!current.completionBusy && current.saveState !== "conflict") {
          current.setSaveState("saved");
        }
      }
      return;
    }
    const command = queueRef.current[0];
    if (current.referenceRef.current === null) return;
    processingRef.current = true;
    try {
      const nextReference = await current.client.updatePipelineReferenceDraft(
        current.recordingId,
        CONTENT_TYPE,
        {
          expected_revision: current.serverRevisionRef.current,
          operator_id: current.operatorId.trim(),
          command_id: command.commandId,
          operations: command.operations,
        },
      );
      hydrateReference(nextReference);
      queueRef.current.shift();
      setQueueLength(queueRef.current.length);
      setFirstUnappliedCommand(
        queueRef.current.length === 0
          ? null
          : describeCommand(queueRef.current[0]),
      );
      current.setNotice(command.notice);
      current.setError(null);
      command.attempts = 0;
    } catch (reason: unknown) {
      command.attempts += 1;
      processingRef.current = false;
      if (reason instanceof ApiError && reason.status === 409) {
        current.setSaveState("conflict");
        setFirstUnappliedCommand(describeCommand(command));
        current.setError(describeError(reason));
        return;
      }
      if (isRetryableError(reason) && command.attempts <= RETRY_LIMIT) {
        current.setSaveState("retrying");
        current.setError(describeError(reason));
        retryTimerRef.current = window.setTimeout(
          () => {
            retryTimerRef.current = null;
            void processQueueRef.current?.();
          },
          Math.min(500, 100 * command.attempts),
        );
        return;
      }
      current.setSaveState("error");
      setFirstUnappliedCommand(describeCommand(command));
      current.setError(describeError(reason));
      return;
    }
    processingRef.current = false;
    if (queueRef.current.length > 0) {
      inputRef.current.setSaveState("saving");
      void processQueueRef.current?.();
    } else {
      inputRef.current.setSaveState("saved");
    }
  }, [hydrateReference]);

  useEffect(() => {
    processQueueRef.current = () => void processQueue();
    return () => {
      processQueueRef.current = null;
      if (retryTimerRef.current !== null) {
        window.clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
    };
  }, [processQueue]);

  const enqueueOperations = useCallback(
    (
      operations: PipelineReferenceOperation[],
      notice: string,
      optimistic: (frames: EditableFrame[]) => EditableFrame[],
    ) => {
      const current = inputRef.current;
      if (current.referenceRef.current === null) return;
      current.setLocalFrames(optimistic(current.getFrames()));
      queueRef.current.push({
        commandId: nextCommandId(),
        operations,
        notice,
        attempts: 0,
      });
      setQueueLength(queueRef.current.length);
      setFirstUnappliedCommand(describeCommand(queueRef.current[0]));
      current.setSaveState("saving");
      current.setError(null);
      void processQueueRef.current?.();
    },
    [nextCommandId],
  );

  const enqueue = useCallback(
    (
      operation: PipelineReferenceOperation,
      notice: string,
      optimistic: (frames: EditableFrame[]) => EditableFrame[],
    ) => enqueueOperations([operation], notice, optimistic),
    [enqueueOperations],
  );

  const retryQueuedCommands = useCallback(() => {
    if (queueRef.current.length === 0) return;
    queueRef.current[0].attempts = 0;
    inputRef.current.setSaveState("saving");
    inputRef.current.setError(null);
    void processQueueRef.current?.();
  }, []);

  const reloadWinningDraft = useCallback(async () => {
    const current = inputRef.current;
    try {
      const winning = await current.client.getPipelineReference(
        current.recordingId,
        CONTENT_TYPE,
      );
      hydrateReference(winning);
      current.setSaveState("saving");
      current.setError(null);
      current.setNotice(
        "Winning draft loaded. The queued visible-card commands will be retried in order.",
      );
      window.setTimeout(() => void processQueueRef.current?.(), 0);
    } catch (reason: unknown) {
      current.setSaveState("error");
      current.setError(describeError(reason));
    }
  }, [hydrateReference]);

  const startReference = useCallback(() => {
    const current = inputRef.current;
    const reference = current.referenceRef.current;
    if (
      reference === null ||
      reference.draft.source_revision_id !== null ||
      reference.draft.items.length > 0 ||
      current.generatedSourceRevisionId === null ||
      current.operatorId.trim() === ""
    ) {
      return;
    }
    enqueue(
      {
        operation: "rebase",
        source_revision_id: current.generatedSourceRevisionId,
        ...(current.proposalRevisionId === null
          ? {}
          : { proposal_revision_id: current.proposalRevisionId }),
      },
      "Maintained visible-card reference seeded from the selected generated result.",
      (frames) => frames,
    );
  }, [enqueue]);

  const rebaseReference = useCallback(async () => {
    const current = inputRef.current;
    const reference = current.referenceRef.current;
    const sourceRevisionId = current.generatedRevisionId;
    if (
      reference === null ||
      sourceRevisionId === null ||
      reference.draft.source_revision_id === sourceRevisionId ||
      current.operatorId.trim() === "" ||
      queueRef.current.length > 0 ||
      processingRef.current ||
      current.saveState !== "saved"
    ) {
      return;
    }
    current.setRebasingReference(true);
    current.setSaveState("saving");
    current.setError(null);
    current.setNotice(null);
    try {
      const rebased = await current.client.updatePipelineReferenceDraft(
        current.recordingId,
        CONTENT_TYPE,
        {
          expected_revision: current.serverRevisionRef.current,
          operator_id: current.operatorId.trim(),
          command_id: nextCommandId(),
          operations: [
            { operation: "rebase", source_revision_id: sourceRevisionId },
          ],
        },
      );
      hydrateReference(rebased, false);
      current.setSaveState("saved");
      current.setNotice(
        "Review switched to the selected generated result. Inspect the visible cards before completing the review.",
      );
    } catch (reason: unknown) {
      current.setSaveState(
        reason instanceof ApiError && reason.status === 409
          ? "conflict"
          : "error",
      );
      current.setError(describeError(reason));
    } finally {
      current.setRebasingReference(false);
    }
  }, [nextCommandId, hydrateReference]);

  const rebaseReferenceToProposal = useCallback(async () => {
    const current = inputRef.current;
    const reference = current.referenceRef.current;
    const sourceRevisionId = current.generatedSourceRevisionId;
    const proposalRevisionId = current.proposalRevisionId;
    if (
      reference === null ||
      sourceRevisionId === null ||
      proposalRevisionId === null ||
      reference.draft.proposal_revision_id === proposalRevisionId ||
      current.operatorId.trim() === "" ||
      queueRef.current.length > 0 ||
      processingRef.current ||
      current.saveState !== "saved"
    ) {
      return;
    }
    current.setRebasingProposal(true);
    current.setSaveState("saving");
    current.setError(null);
    current.setNotice(null);
    try {
      const rebased = await current.client.updatePipelineReferenceDraft(
        current.recordingId,
        CONTENT_TYPE,
        {
          expected_revision: current.serverRevisionRef.current,
          operator_id: current.operatorId.trim(),
          command_id: nextCommandId(),
          operations: [
            {
              operation: "rebase",
              source_revision_id: sourceRevisionId,
              proposal_revision_id: proposalRevisionId,
            },
          ],
        },
      );
      hydrateReference(rebased, false);
      current.setSaveState("saved");
      current.setNotice(
        "Proposed card scenes loaded. Inspect the poses and homography before completing the review.",
      );
    } catch (reason: unknown) {
      current.setSaveState(
        reason instanceof ApiError && reason.status === 409
          ? "conflict"
          : "error",
      );
      current.setError(describeError(reason));
    } finally {
      current.setRebasingProposal(false);
    }
  }, [nextCommandId, hydrateReference]);

  const hasPendingCommands = useCallback(() => queueRef.current.length > 0, []);
  const isProcessing = useCallback(() => processingRef.current, []);

  return {
    loadGenerated,
    loadReference,
    loadProposalRun,
    refreshProposalRun,
    startProposal,
    retryProposal,
    loadCalibrationRefinement,
    startCalibrationRefinement,
    refreshCalibrationPreview,
    updateCalibrationAnchor,
    discardCalibrationRefinement,
    applyCalibrationRefinement,
    createReference,
    completeReference,
    enqueue,
    enqueueOperations,
    nextCommandId,
    queueLength,
    firstUnappliedCommand,
    retryQueuedCommands,
    reloadWinningDraft,
    startReference,
    rebaseReference,
    rebaseReferenceToProposal,
    hasPendingCommands,
    isProcessing,
  };
}

function isRetryableError(reason: unknown): boolean {
  return !(
    reason instanceof ApiError &&
    reason.status >= 400 &&
    reason.status < 500
  );
}
