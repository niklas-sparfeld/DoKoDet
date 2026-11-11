import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { ApiError } from "../api/transport";
import type { DokoDetectorClient } from "../api/clientTypes";
import type {
  PipelineSelectionUpdateRequest,
  PipelineSelectableContentType,
  PipelineWorkspace,
  PipelineWorkspaceStage,
  PipelineStageKey,
} from "../api/pipelineContracts";
import {
  readPipelineUrlState,
  recordingPipelineComparePath,
  recordingPipelineNavigationPath,
  type PipelineNavigationStepKey,
  type PipelineUrlState,
} from "./recordingPipelineUrl";

const STAGE_CONTENT_TYPES: Record<
  Exclude<PipelineWorkspaceStage["key"], "round_analyses">,
  PipelineSelectableContentType
> = {
  events: "events",
  visible_cards: "visible_cards",
  visual_identities: "visual_identities",
  table_observations: "table_observations",
};

type SelectionClient = Pick<DokoDetectorClient, "updatePipelineSelection">;

export function useRecordingPipelineSelection({
  recordingId,
  stageKey,
  compare,
  backendStageKey,
  stage,
  setWorkspace,
  loadWorkspace,
  client,
  setNotice,
  urlState,
  setUrlState,
}: {
  recordingId: string;
  stageKey: PipelineNavigationStepKey | null;
  compare: boolean;
  backendStageKey: PipelineStageKey | null;
  stage: PipelineWorkspaceStage | undefined;
  setWorkspace: (
    workspace:
      | PipelineWorkspace
      | null
      | ((current: PipelineWorkspace | null) => PipelineWorkspace | null),
  ) => void;
  loadWorkspace: () => Promise<void>;
  client: SelectionClient;
  setNotice: (notice: string | null) => void;
  urlState: PipelineUrlState;
  setUrlState: (state: PipelineUrlState) => void;
}) {
  const [busyRequest, setBusyRequest] = useState<{
    owner: { recordingId: string };
    requestId: number;
  } | null>(null);
  const recordingOwner = useMemo(() => ({ recordingId }), [recordingId]);
  const recordingOwnerRef = useRef(recordingOwner);
  const requestIdRef = useRef(0);
  useLayoutEffect(() => {
    recordingOwnerRef.current = recordingOwner;
    requestIdRef.current += 1;
  }, [recordingOwner]);

  const navigateTo = useCallback((path: string, replace = false): void => {
    if (replace) window.history.replaceState({}, "", path);
    else window.history.pushState({}, "", path);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, []);

  const replaceUrlState = useCallback(
    (nextState: PipelineUrlState): void => {
      const nextPath = compare
        ? recordingPipelineComparePath(
            recordingId,
            backendStageKey ?? "events",
            nextState,
          )
        : recordingPipelineNavigationPath(
            recordingId,
            stageKey ?? "events",
            nextState,
          );
      window.history.replaceState({}, "", nextPath);
      setUrlState(nextState);
    },
    [backendStageKey, compare, recordingId, setUrlState, stageKey],
  );

  const selectGeneratedRevision = useCallback(
    async (nextRevisionId: string | null): Promise<void> => {
      if (
        stage === undefined ||
        stage.key === "round_analyses" ||
        stage.key === "events"
      )
        return;
      const requestId = ++requestIdRef.current;
      const ownsRequest = () =>
        recordingOwnerRef.current === recordingOwner &&
        requestIdRef.current === requestId;
      setBusyRequest({ owner: recordingOwner, requestId });
      setNotice(null);
      const contentType = STAGE_CONTENT_TYPES[stage.key];
      const selectedOption =
        nextRevisionId === null
          ? undefined
          : stage.input_options.find(
              (option) => option.node_revision_id === nextRevisionId,
            );
      if (nextRevisionId !== null && selectedOption === undefined) {
        if (ownsRequest()) {
          setBusyRequest(null);
          setNotice(
            "That processor input is no longer available. Reload the workspace.",
          );
        }
        return;
      }
      const payload: PipelineSelectionUpdateRequest = {
        expected_revision: stage.selection_revision ?? 0,
        selected_generated:
          selectedOption === undefined
            ? null
            : {
                node_id: selectedOption.node_id,
                revision_id: selectedOption.node_revision_id,
              },
      };
      try {
        const response = await client.updatePipelineSelection(
          recordingId,
          contentType,
          payload,
        );
        if (!ownsRequest()) return;
        setWorkspace((current) =>
          !ownsRequest() || current?.recording_id !== recordingId
            ? current
            : {
                ...current,
                stages: current.stages.map((candidate) =>
                  candidate.key === stage.key
                    ? {
                        ...candidate,
                        selection_revision: response.selection.revision,
                        selected_generated:
                          response.selection.selected_generated,
                        selected_completed_reference:
                          response.selection.selected_completed_reference,
                      }
                    : candidate,
                ),
              },
        );
        setNotice("Processor input revision selected.");
      } catch (reason: unknown) {
        if (!ownsRequest()) return;
        if (reason instanceof ApiError && reason.status === 409) {
          await loadWorkspace();
          if (ownsRequest()) {
            setNotice(
              "The processor input changed elsewhere. The winning selection is shown.",
            );
          }
        } else {
          if (ownsRequest()) setNotice(describeSelectionError(reason));
        }
      } finally {
        if (ownsRequest()) setBusyRequest(null);
      }
    },
    [
      client,
      loadWorkspace,
      recordingId,
      recordingOwner,
      setNotice,
      setWorkspace,
      stage,
    ],
  );

  return {
    urlState,
    selectionBusy: busyRequest?.owner === recordingOwner,
    navigateTo,
    replaceUrlState,
    selectGeneratedRevision,
    setUrlState,
  };
}

export function useRecordingPipelineUrlState() {
  const [urlState, setUrlState] = useState(() =>
    readPipelineUrlState(window.location.search),
  );
  useEffect(() => {
    const updateUrlState = () =>
      setUrlState(readPipelineUrlState(window.location.search));
    window.addEventListener("popstate", updateUrlState);
    return () => window.removeEventListener("popstate", updateUrlState);
  }, []);
  return { urlState, setUrlState };
}

function describeSelectionError(reason: unknown): string {
  if (!(reason instanceof ApiError)) return "The backend could not be reached.";
  const body =
    typeof reason.body === "object" && reason.body !== null
      ? (reason.body as Record<string, unknown>)
      : null;
  const detail =
    typeof body?.detail === "object" && body.detail !== null
      ? (body.detail as Record<string, unknown>)
      : null;
  const message =
    typeof detail?.message === "string"
      ? detail.message
      : typeof body?.message === "string"
        ? body.message
        : null;
  if (
    message?.toLowerCase().includes("video") ||
    message?.toLowerCase().includes("recording")
  ) {
    return `The accepted recording video is unavailable: ${message}`;
  }
  if (reason.status === 422) {
    return message === null
      ? "The selected pipeline input is incompatible with this stage."
      : `The selected pipeline input is incompatible with this stage: ${message}`;
  }
  return message ?? `The backend returned HTTP ${reason.status}.`;
}
