import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { TimelineRailSeekingControls } from "../pipeline/TimelineRailSeekingControls";
import styles from "./PipelineVisibleCardEditor.module.css";
import {
  applyPoseSceneAction,
  type AnchorState,
  type PoseSceneEnvelope,
  type TablePoint,
} from "./PoseBasedVisibleCardScene";
import {
  getWorkbenchAvailability,
  WORKBENCH_LAYERS,
  type WorkbenchLayer,
  type WorkbenchPreferences,
  type WorkbenchSelection,
  type WorkbenchViewpoint,
} from "./VisibleCardReviewWorkbenchState";
import {
  createWorkbenchGuidance,
  type WorkbenchGuidance,
  type WorkbenchGuidanceStep,
  type WorkbenchGuidanceTarget,
} from "./VisibleCardWorkbenchGuidance";
import { selectedPoseForSelection } from "./VisibleCardWorkbenchGeometry";
import type {
  VisibleCardReviewWorkbenchAction,
  VisibleCardFrameDecision,
  VisibleRegionWorkbenchAction,
  VirtualCardWorkbenchAction,
  VisibleCardReviewWorkbenchProps,
} from "./VisibleCardReviewWorkbench";

type WorkbenchCalibrationRefinement = NonNullable<
  VisibleCardReviewWorkbenchProps["calibrationRefinement"]
>;

export type WorkbenchCalibrationAnchor = {
  anchorId: string;
  cardId: string;
  sourceFrameId: string;
  eligible: boolean;
  state: AnchorState;
  corners: TablePoint[];
};

const VIEWPOINT_LABELS: Record<WorkbenchViewpoint, string> = {
  camera: "Camera",
  rectified: "Rectified",
};

const LAYER_LABELS: Record<WorkbenchLayer, string> = {
  visible_regions: "Visible regions",
  virtual_cards: "Virtual cards",
  ignore_regions: "Ignore regions",
  suggestions: "Detector suggestions",
  mapping: "Mapping diagnostics",
};

const LATER_EDIT_REASON =
  "This edit tool is planned for a later workbench phase.";

export type WorkbenchCommandBarViewModel = {
  viewpoint: WorkbenchViewpoint;
  enabledLayers: readonly WorkbenchLayer[];
  activeTool: WorkbenchPreferences["activeTool"];
  availability: ReturnType<typeof getWorkbenchAvailability>;
  readOnly: boolean;
  enabledEditTools: readonly WorkbenchPreferences["activeTool"][];
};

export type WorkbenchCommandBarCallbacks = {
  onToggleViewpoint: () => void;
  onToggleLayer: (layer: WorkbenchLayer) => void;
  onSelectTool: (tool: WorkbenchPreferences["activeTool"]) => void;
  onStartProposal?: () => void;
  onStartMappingPreview?: () => void;
};

export function WorkbenchCommandBar({
  viewModel,
  callbacks,
}: {
  viewModel: WorkbenchCommandBarViewModel;
  callbacks: WorkbenchCommandBarCallbacks;
}) {
  const {
    viewpoint,
    enabledLayers,
    activeTool,
    availability,
    readOnly,
    enabledEditTools,
  } = viewModel;
  const {
    onToggleViewpoint,
    onToggleLayer,
    onSelectTool,
    onStartProposal,
    onStartMappingPreview,
  } = callbacks;
  const nextViewpoint: WorkbenchViewpoint =
    viewpoint === "camera" ? "rectified" : "camera";
  const viewpointAvailability = availability.viewpoints[nextViewpoint];
  const viewpointLabel = `Viewpoint: ${VIEWPOINT_LABELS[viewpoint]}. Switch to ${VIEWPOINT_LABELS[nextViewpoint]}`;
  const [guidance, setGuidance] = useState<{
    target: WorkbenchGuidanceTarget;
    content: WorkbenchGuidance;
    stepIndex: number;
  } | null>(null);
  const commandBarRef = useRef<HTMLDivElement | null>(null);
  const guidanceButtonRef = useRef<HTMLButtonElement | null>(null);
  const [guidancePosition, setGuidancePosition] = useState<{
    top: number;
    left: number;
  } | null>(null);

  const targetKey = (target: WorkbenchGuidanceTarget) =>
    `${target.kind}:${target.id}`;
  const guidanceTargetKey =
    guidance === null ? null : targetKey(guidance.target);

  useLayoutEffect(() => {
    if (guidance === null || guidanceButtonRef.current === null) {
      setGuidancePosition(null);
      return;
    }
    const updatePosition = () => {
      const button = guidanceButtonRef.current;
      if (button === null) return;
      const rect = button.getBoundingClientRect();
      const width = Math.min(22 * 16, window.innerWidth - 16);
      setGuidancePosition({
        top: rect.bottom + 8,
        left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)),
      });
    };
    const commandBar = commandBarRef.current;
    updatePosition();
    window.addEventListener("resize", updatePosition);
    commandBar?.addEventListener("scroll", updatePosition);
    return () => {
      window.removeEventListener("resize", updatePosition);
      commandBar?.removeEventListener("scroll", updatePosition);
    };
  }, [guidance]);

  const closeGuidance = () => setGuidance(null);
  const openGuidance = (
    target: WorkbenchGuidanceTarget,
    button: HTMLButtonElement,
  ) => {
    guidanceButtonRef.current = button;
    setGuidance({
      target,
      content: createWorkbenchGuidance(target, {
        onStartProposal,
        onStartMappingPreview,
        onSelectTool,
      }),
      stepIndex: 0,
    });
  };
  const currentStep =
    guidance === null ? null : guidance.content.steps[guidance.stepIndex];
  const isGuidanceTarget = (target: WorkbenchGuidanceTarget) =>
    guidanceTargetKey === targetKey(target);
  const targetClassName = (target: WorkbenchGuidanceTarget) =>
    `${styles.workbenchToggle}${
      isGuidanceTarget(target) ? ` ${styles.workbenchToggleGuidanceTarget}` : ""
    }`;
  const handleUnavailableClick = (
    target: WorkbenchGuidanceTarget,
    available: boolean,
    button: HTMLButtonElement,
  ) => {
    if (!available) openGuidance(target, button);
  };

  return (
    <div
      ref={commandBarRef}
      className={styles.workbenchCommandBar}
      aria-label="Workbench command bar"
      role="toolbar"
      onKeyDown={(event) => {
        if (event.key === "Escape" && guidance !== null) {
          event.preventDefault();
          closeGuidance();
        }
      }}
    >
      <div className={styles.workbenchCommandGroup} aria-label="View">
        <span className={styles.workbenchCommandLabel}>View</span>
        <button
          type="button"
          className={targetClassName({
            kind: "viewpoint",
            id: nextViewpoint,
            label: VIEWPOINT_LABELS[nextViewpoint],
            reason: viewpointAvailability.disabledReason ?? "",
          })}
          aria-label={viewpointLabel}
          title={viewpointAvailability.disabledReason ?? undefined}
          aria-expanded={isGuidanceTarget({
            kind: "viewpoint",
            id: nextViewpoint,
            label: VIEWPOINT_LABELS[nextViewpoint],
            reason: viewpointAvailability.disabledReason ?? "",
          })}
          aria-describedby={
            isGuidanceTarget({
              kind: "viewpoint",
              id: nextViewpoint,
              label: VIEWPOINT_LABELS[nextViewpoint],
              reason: viewpointAvailability.disabledReason ?? "",
            })
              ? "workbench-guidance"
              : undefined
          }
          onClick={(event) => {
            const target = {
              kind: "viewpoint" as const,
              id: nextViewpoint,
              label: VIEWPOINT_LABELS[nextViewpoint],
              reason: viewpointAvailability.disabledReason ?? "",
            };
            handleUnavailableClick(
              target,
              viewpointAvailability.available,
              event.currentTarget,
            );
            if (viewpointAvailability.available) {
              closeGuidance();
              onToggleViewpoint();
            }
          }}
        >
          {VIEWPOINT_LABELS[viewpoint]}
        </button>
      </div>
      <div className={styles.workbenchCommandGroup} aria-label="Show">
        <span className={styles.workbenchCommandLabel}>Show</span>
        {WORKBENCH_LAYERS.map((layer) => {
          const layerAvailability = availability.layers[layer];
          return (
            <button
              key={layer}
              type="button"
              className={targetClassName({
                kind: "layer",
                id: layer,
                label: LAYER_LABELS[layer],
                reason: layerAvailability.disabledReason ?? "",
              })}
              aria-label={LAYER_LABELS[layer]}
              aria-pressed={enabledLayers.includes(layer)}
              title={layerAvailability.disabledReason ?? undefined}
              aria-expanded={isGuidanceTarget({
                kind: "layer",
                id: layer,
                label: LAYER_LABELS[layer],
                reason: layerAvailability.disabledReason ?? "",
              })}
              aria-describedby={
                isGuidanceTarget({
                  kind: "layer",
                  id: layer,
                  label: LAYER_LABELS[layer],
                  reason: layerAvailability.disabledReason ?? "",
                })
                  ? "workbench-guidance"
                  : undefined
              }
              onClick={(event) => {
                const target = {
                  kind: "layer" as const,
                  id: layer,
                  label: LAYER_LABELS[layer],
                  reason: layerAvailability.disabledReason ?? "",
                };
                handleUnavailableClick(
                  target,
                  layerAvailability.available,
                  event.currentTarget,
                );
                if (layerAvailability.available) {
                  closeGuidance();
                  onToggleLayer(layer);
                }
              }}
            >
              {LAYER_LABELS[layer]}
            </button>
          );
        })}
      </div>
      <div className={styles.workbenchCommandGroup} aria-label="Edit">
        <span className={styles.workbenchCommandLabel}>Edit</span>
        {(["visible_regions", "virtual_cards", "mapping"] as const).map(
          (tool) => {
            const toolAvailability = availability.tools[tool];
            const enabledInPhase = enabledEditTools.includes(tool);
            const disabledReason = readOnly
              ? toolAvailability.mutationDisabledReason
              : enabledInPhase
                ? null
                : LATER_EDIT_REASON;
            return (
              <button
                key={tool}
                type="button"
                className={targetClassName({
                  kind: "tool",
                  id: tool,
                  label: LAYER_LABELS[tool],
                  reason: toolAvailability.disabledReason ?? "",
                })}
                aria-pressed={activeTool === tool}
                aria-label={`Edit ${LAYER_LABELS[tool]}`}
                title={
                  (toolAvailability.available
                    ? disabledReason
                    : toolAvailability.disabledReason) ?? undefined
                }
                disabled={toolAvailability.available && disabledReason !== null}
                aria-expanded={isGuidanceTarget({
                  kind: "tool",
                  id: tool,
                  label: LAYER_LABELS[tool],
                  reason: toolAvailability.disabledReason ?? "",
                })}
                aria-describedby={
                  isGuidanceTarget({
                    kind: "tool",
                    id: tool,
                    label: LAYER_LABELS[tool],
                    reason: toolAvailability.disabledReason ?? "",
                  })
                    ? "workbench-guidance"
                    : undefined
                }
                onClick={(event) => {
                  const target = {
                    kind: "tool" as const,
                    id: tool,
                    label: LAYER_LABELS[tool],
                    reason: toolAvailability.disabledReason ?? "",
                  };
                  handleUnavailableClick(
                    target,
                    toolAvailability.available,
                    event.currentTarget,
                  );
                  if (toolAvailability.available) {
                    closeGuidance();
                    onSelectTool(tool);
                  }
                }}
              >
                {tool === "mapping" ? "Mapping" : LAYER_LABELS[tool]}
              </button>
            );
          },
        )}
      </div>
      {guidance !== null && currentStep !== null && guidancePosition !== null
        ? createPortal(
            <WorkbenchGuidanceBubble
              guidance={guidance.content}
              step={currentStep}
              stepIndex={guidance.stepIndex}
              position={guidancePosition}
              onClose={closeGuidance}
              onPrevious={() =>
                setGuidance((current) =>
                  current === null
                    ? current
                    : { ...current, stepIndex: current.stepIndex - 1 },
                )
              }
              onNext={() =>
                setGuidance((current) =>
                  current === null ||
                  current.stepIndex >= current.content.steps.length - 1
                    ? current
                    : { ...current, stepIndex: current.stepIndex + 1 },
                )
              }
              onAction={() => {
                currentStep.action?.();
                if (currentStep.dismissOnAction) closeGuidance();
              }}
            />,
            document.body,
          )
        : null}
    </div>
  );
}

function WorkbenchGuidanceBubble({
  guidance,
  step,
  stepIndex,
  position,
  onClose,
  onPrevious,
  onNext,
  onAction,
}: {
  guidance: WorkbenchGuidance;
  step: WorkbenchGuidanceStep;
  stepIndex: number;
  position: { top: number; left: number };
  onClose: () => void;
  onPrevious: () => void;
  onNext: () => void;
  onAction: () => void;
}) {
  const isLastStep = stepIndex === guidance.steps.length - 1;
  return (
    <aside
      id="workbench-guidance"
      className={styles.workbenchGuidanceBubble}
      role="dialog"
      aria-label={guidance.title}
      style={{ top: position.top, left: position.left }}
      data-workbench-guidance
    >
      <div className={styles.workbenchGuidanceHeader}>
        <div>
          <span className={styles.workbenchGuidanceEyebrow}>
            Step {stepIndex + 1} of {guidance.steps.length}
          </span>
          <h3>{guidance.title}</h3>
        </div>
        <button
          type="button"
          className={styles.workbenchGuidanceClose}
          aria-label="Close guidance"
          onClick={onClose}
        >
          ×
        </button>
      </div>
      <p className={styles.workbenchGuidanceDescription}>
        {guidance.description}
      </p>
      <section className={styles.workbenchGuidanceStep} aria-label={step.title}>
        <h4>{step.title}</h4>
        <p>{step.description}</p>
        {step.action !== undefined && step.actionLabel !== undefined ? (
          <button
            type="button"
            className={styles.workbenchGuidanceAction}
            onClick={onAction}
          >
            {step.actionLabel}
          </button>
        ) : null}
      </section>
      <div className={styles.workbenchGuidanceNavigation}>
        <button
          type="button"
          className={styles.workbenchGuidanceSecondary}
          onClick={onPrevious}
          disabled={stepIndex === 0}
        >
          Back
        </button>
        <button
          type="button"
          className={styles.workbenchGuidancePrimary}
          onClick={isLastStep ? onClose : onNext}
        >
          {isLastStep ? "Done" : "Next"}
        </button>
      </div>
    </aside>
  );
}

export type VisibleCardEditorSummary = {
  cardId: string | null;
  polygonCount: number;
  polygonIndex: number;
};

export type WorkbenchTimelineSelectionViewModel = {
  activeTool: WorkbenchPreferences["activeTool"];
  selection: WorkbenchSelection | null;
  readOnly: boolean;
  selectedCandidateIds: string[];
  editor: VisibleCardEditorSummary | null;
  sourceAvailable: boolean;
  canCopyIgnoreRegions: boolean;
  canRestoreSuggestion: boolean;
  frameDecision?: VisibleCardFrameDecision;
  scene: PoseSceneEnvelope | null;
  calibrationRefinement: WorkbenchCalibrationRefinement | null;
  mappingAnchors: WorkbenchCalibrationAnchor[];
  mappingLoading: boolean;
  anchorCornerIndex: number;
  numericAnchor: { anchorId: string; point: TablePoint } | null;
};

export type WorkbenchTimelineSelectionCallbacks = {
  onNumericChange: (value: number, axis: 0 | 1) => void;
  onEmitNumeric: () => void;
  onCardDecision?: (cardId: string, decision: "accept" | "reject") => void;
  onResolveRemaining?: () => void;
  onSceneAction: (
    action: Parameters<typeof applyPoseSceneAction>[1],
    notice: string,
  ) => void;
  onAction: (action: VisibleCardReviewWorkbenchAction) => void;
};

export function WorkbenchTimelineSelectionActions({
  viewModel,
  callbacks,
}: {
  viewModel: WorkbenchTimelineSelectionViewModel;
  callbacks: WorkbenchTimelineSelectionCallbacks;
}) {
  const {
    activeTool,
    selection,
    readOnly,
    selectedCandidateIds,
    editor,
    sourceAvailable,
    canCopyIgnoreRegions,
    canRestoreSuggestion,
    frameDecision,
    scene,
    calibrationRefinement,
    mappingAnchors,
    mappingLoading,
    anchorCornerIndex,
    numericAnchor,
  } = viewModel;
  const {
    onNumericChange,
    onEmitNumeric,
    onCardDecision,
    onResolveRemaining,
    onSceneAction,
    onAction,
  } = callbacks;
  const content = (
    <div
      className={styles.workbenchTimelineActions}
      aria-label="Selection actions"
    >
      {activeTool === "visible_regions" || selectedCandidateIds.length > 0 ? (
        <VisibleRegionSelectionActions
          readOnly={readOnly}
          sourceAvailable={sourceAvailable}
          selectedCandidateCount={selectedCandidateIds.length}
          editor={editor}
          selection={selection}
          canCopyIgnoreRegions={canCopyIgnoreRegions}
          canRestoreSuggestion={canRestoreSuggestion}
          onAction={onAction}
        />
      ) : null}
      {activeTool === "virtual_cards" && selectedCandidateIds.length === 0 ? (
        <VirtualCardSelectionActions
          readOnly={readOnly}
          scene={scene}
          selection={selection}
          onAction={onAction}
          onCardDecision={onCardDecision}
          onResolveRemaining={onResolveRemaining}
          onSceneAction={onSceneAction}
        />
      ) : null}
      {activeTool === "mapping" && selectedCandidateIds.length === 0 ? (
        <MappingSelectionActions
          readOnly={readOnly}
          refinement={calibrationRefinement}
          anchors={mappingAnchors}
          selection={selection}
          anchorCornerIndex={anchorCornerIndex}
          numericAnchor={numericAnchor}
          mappingLoading={mappingLoading}
          onNumericChange={onNumericChange}
          onEmitNumeric={onEmitNumeric}
          onAction={onAction}
        />
      ) : null}
      {frameDecision !== undefined ? (
        <FrameDecisionActions decision={frameDecision} />
      ) : null}
    </div>
  );
  return content;
}

function FrameDecisionActions({
  decision,
}: {
  decision: VisibleCardFrameDecision;
}) {
  return (
    <div
      className={styles.workbenchCommandGroup}
      aria-label="Frame decision"
      role="group"
    >
      <span className={styles.workbenchCommandLabel}>Frame decision</span>
      <button
        type="button"
        className={styles.workbenchToggle}
        aria-keyshortcuts="A"
        disabled={!decision.canAccept}
        title={
          decision.canAccept
            ? "Accept frame · A"
            : decision.acceptDisabledReason
        }
        onClick={decision.onAccept}
      >
        {decision.accepted ? "Mark frame unreviewed" : "Accept frame"}
      </button>
      <button
        type="button"
        className={styles.workbenchToggle}
        aria-keyshortcuts="E"
        title="Mark empty frame · E"
        onClick={decision.onMarkEmpty}
      >
        Mark empty
      </button>
      <button
        type="button"
        className={styles.workbenchToggle}
        aria-keyshortcuts="U"
        title="Mark unusable frame · U"
        onClick={decision.onMarkUnusable}
      >
        Mark unusable
      </button>
    </div>
  );
}

function VirtualCardSelectionActions({
  readOnly,
  scene,
  selection,
  onAction,
  onCardDecision,
  onResolveRemaining,
  onSceneAction,
}: {
  readOnly: boolean;
  scene: PoseSceneEnvelope | null;
  selection: WorkbenchSelection | null;
  onAction: (action: VisibleCardReviewWorkbenchAction) => void;
  onCardDecision?: (cardId: string, decision: "accept" | "reject") => void;
  onResolveRemaining?: () => void;
  onSceneAction: (
    action: Parameters<typeof applyPoseSceneAction>[1],
    notice: string,
  ) => void;
}) {
  const selectedPose =
    scene === null ? null : selectedPoseForSelection(scene, selection);
  const selectedReviewState =
    scene?.card_review_states?.find(
      (state) => state.card_id === selectedPose?.card_id,
    ) ?? null;
  const pendingCount =
    scene?.card_review_states?.filter((state) => state.state === "pending")
      .length ?? 0;
  const selectedCardId = selectedPose?.card_id ?? null;
  const sceneAvailable = scene !== null;
  const cardTarget = selectedCardId ?? "selected card";
  const actionControl = (
    action: VirtualCardWorkbenchAction,
    label: string,
    symbol: string,
    shortcut: string,
    disabled: boolean,
    reason: string,
  ) => ({
    label,
    symbol,
    shortcut,
    ariaShortcut: shortcut === "Click" ? undefined : shortcut,
    disabled,
    disabledReason: reason,
    onClick: () => {
      if (
        (action === "accept_card" || action === "reject_card") &&
        selectedCardId !== null &&
        onCardDecision !== undefined
      ) {
        onCardDecision(
          selectedCardId,
          action === "accept_card" ? "accept" : "reject",
        );
      } else if (
        action === "accept_remaining_cards" &&
        onResolveRemaining !== undefined
      ) {
        onResolveRemaining();
      } else {
        onAction(action);
      }
    },
  });
  const controls = [
    actionControl(
      "add_virtual_card",
      "Add virtual card",
      "＋",
      "Click",
      readOnly || !sceneAvailable,
      readOnly
        ? "Generated visible-card results are read-only."
        : "A proposed card scene is required to add a virtual card.",
    ),
    actionControl(
      "accept_card",
      selectedCardId === null ? "Accept card" : `Accept card ${cardTarget}`,
      "✓",
      "Click",
      readOnly ||
        selectedCardId === null ||
        selectedReviewState === null ||
        selectedReviewState.state === "accepted",
      selectedCardId === null
        ? "Select a virtual card first."
        : selectedReviewState === null
          ? "This card has no review decision state."
          : "The selected card is already accepted.",
    ),
    actionControl(
      "reject_card",
      selectedCardId === null ? "Reject card" : `Reject card ${cardTarget}`,
      "×",
      "Click",
      readOnly ||
        selectedCardId === null ||
        selectedReviewState === null ||
        selectedReviewState.state === "rejected",
      selectedCardId === null
        ? "Select a virtual card first."
        : selectedReviewState === null
          ? "This card has no review decision state."
          : "The selected card is already rejected.",
    ),
    actionControl(
      "accept_remaining_cards",
      "Accept remaining cards",
      "✓✓",
      "Click",
      readOnly || pendingCount === 0 || onResolveRemaining === undefined,
      pendingCount === 0
        ? "No pending card decisions remain."
        : "All pending cards must be resolved through the maintained reference.",
    ),
    actionControl(
      "remove_card",
      selectedCardId === null ? "Remove card" : `Remove card ${cardTarget}`,
      "−",
      "Click",
      readOnly || selectedPose === null || scene?.scene.poses.length === 1,
      selectedPose === null
        ? "Select a virtual card first."
        : scene?.scene.poses.length === 1
          ? "A card scene must keep one virtual card."
          : "",
    ),
    actionControl(
      "bring_forward",
      selectedCardId === null
        ? "Bring card forward"
        : `Bring card ${cardTarget} forward`,
      "↑",
      "Click",
      readOnly || selectedPose === null,
      "Select a virtual card first.",
    ),
    actionControl(
      "send_backward",
      selectedCardId === null
        ? "Send card backward"
        : `Send card ${cardTarget} backward`,
      "↓",
      "Click",
      readOnly || selectedPose === null,
      "Select a virtual card first.",
    ),
    actionControl(
      "restore_proposed_scene",
      "Restore proposed scene",
      "↺",
      "Click",
      readOnly || !sceneAvailable,
      readOnly
        ? "Generated visible-card results are read-only."
        : "A proposed card scene is required to restore the scene.",
    ),
  ];
  return (
    <>
      <TimelineRailSeekingControls
        groups={[{ label: "Selection actions", controls }]}
      />
      <label
        key={selectedPose?.card_id ?? "no-selected-card"}
        className={styles.workbenchTimelineField}
      >
        <span>Rotation</span>
        <input
          aria-label="Rotation (degrees)"
          type="number"
          step="1"
          defaultValue={selectedPose?.rotation_degrees ?? ""}
          disabled={readOnly || selectedPose === null}
          title={
            selectedPose === null
              ? "Select a virtual card to set its rotation."
              : "Set rotation in degrees."
          }
          onBlur={(event) => {
            const value = Number(event.target.value);
            if (
              !Number.isFinite(value) ||
              scene === null ||
              selectedPose === null
            )
              return;
            onSceneAction(
              {
                type: "rotate",
                cardId: selectedPose.card_id,
                rotationDegrees: value,
              },
              "Card angle saved.",
            );
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              event.currentTarget.blur();
            }
          }}
        />
      </label>
    </>
  );
}

function MappingSelectionActions({
  readOnly,
  refinement,
  anchors,
  selection,
  anchorCornerIndex,
  numericAnchor,
  mappingLoading,
  onNumericChange,
  onEmitNumeric,
  onAction,
}: {
  readOnly: boolean;
  refinement: WorkbenchCalibrationRefinement | null;
  anchors: WorkbenchCalibrationAnchor[];
  selection: WorkbenchSelection | null;
  anchorCornerIndex: number;
  numericAnchor: { anchorId: string; point: TablePoint } | null;
  mappingLoading: boolean;
  onNumericChange: (value: number, axis: 0 | 1) => void;
  onEmitNumeric: () => void;
  onAction: (action: VisibleCardReviewWorkbenchAction) => void;
}) {
  const selectedAnchor =
    selection?.type === "calibration_anchor"
      ? (anchors.find((anchor) => anchor.anchorId === selection.id) ?? null)
      : null;
  const stateButton = (
    state: "accepted" | "excluded",
    label: string,
    symbol: string,
  ) => ({
    label,
    symbol,
    shortcut: "Click",
    disabled:
      readOnly ||
      selectedAnchor === null ||
      (!selectedAnchor.eligible && state !== "excluded") ||
      selectedAnchor.state === state ||
      refinement === null,
    disabledReason:
      selectedAnchor === null
        ? "Select a calibration anchor first."
        : refinement === null
          ? "Start a mapping preview before changing anchor decisions."
          : "The selected anchor already has this state.",
    onClick: () =>
      onAction(state === "accepted" ? "accept_anchor" : "exclude_anchor"),
  });
  const corner =
    selectedAnchor?.corners[anchorCornerIndex] ?? ([0, 0] as TablePoint);
  const numericPoint =
    numericAnchor !== null &&
    numericAnchor.anchorId === selectedAnchor?.anchorId
      ? numericAnchor.point
      : corner;
  const controls = [
    stateButton("accepted", "Accept anchor", "✓"),
    stateButton("excluded", "Exclude anchor", "⊘"),
    {
      label: "Start mapping preview",
      symbol: "▶",
      shortcut: "Click",
      disabled: readOnly || refinement !== null || mappingLoading,
      disabledReason: "A mapping preview is already active.",
      onClick: () => onAction("start_mapping_preview"),
    },
    {
      label: "Discard mapping preview",
      symbol: "↶",
      shortcut: "Click",
      disabled: readOnly || refinement === null || mappingLoading,
      disabledReason: "Start a mapping preview first.",
      onClick: () => onAction("discard_mapping_preview"),
    },
  ];
  return (
    <>
      <p>
        Drag corners to save corrected anchors. Apply the calibration to the
        table in Recording-wide mapping.
      </p>
      <TimelineRailSeekingControls
        groups={[{ label: "Anchor decisions", controls }]}
      />
      {selectedAnchor !== null ? (
        <div className={styles.workbenchTimelineFields}>
          <label className={styles.workbenchTimelineField}>
            <span>Corner {anchorCornerIndex + 1} X</span>
            <input
              aria-label={`Anchor corner ${anchorCornerIndex + 1} X`}
              type="number"
              step="0.01"
              value={numericPoint[0]}
              disabled={readOnly}
              onChange={(event) =>
                onNumericChange(Number(event.target.value), 0)
              }
            />
          </label>
          <label className={styles.workbenchTimelineField}>
            <span>Corner {anchorCornerIndex + 1} Y</span>
            <input
              aria-label={`Anchor corner ${anchorCornerIndex + 1} Y`}
              type="number"
              step="0.01"
              value={numericPoint[1]}
              disabled={readOnly}
              onChange={(event) =>
                onNumericChange(Number(event.target.value), 1)
              }
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  onEmitNumeric();
                }
              }}
            />
          </label>
          <button
            type="button"
            className={styles.workbenchTimelineFieldButton}
            aria-label="Save corner coordinates"
            disabled={readOnly || numericAnchor === null}
            title="Save corner coordinates · Enter"
            onClick={onEmitNumeric}
          >
            <span aria-hidden="true">✓</span>
          </button>
        </div>
      ) : null}
    </>
  );
}

function VisibleRegionSelectionActions({
  readOnly,
  sourceAvailable,
  selectedCandidateCount,
  editor,
  selection,
  canCopyIgnoreRegions,
  canRestoreSuggestion,
  onAction,
}: {
  readOnly: boolean;
  sourceAvailable: boolean;
  selectedCandidateCount: number;
  editor: VisibleCardEditorSummary | null;
  selection: WorkbenchSelection | null;
  canCopyIgnoreRegions: boolean;
  canRestoreSuggestion: boolean;
  onAction: (action: VisibleRegionWorkbenchAction) => void;
}) {
  const actions: Array<{
    action: VisibleRegionWorkbenchAction;
    label: string;
    ariaLabel?: string;
    symbol: string;
    shortcut: string;
    ariaShortcut?: string;
    disabled: boolean;
    reason: string;
  }> = [
    {
      action: "add_visible_card",
      label: "Add visible card",
      symbol: "＋",
      shortcut: "N",
      ariaShortcut: "N",
      disabled: readOnly || !sourceAvailable,
      reason: readOnly
        ? "Generated visible-card results are read-only."
        : "A resolved source frame is required to add a visible card.",
    },
    {
      action: "add_polygon",
      label: "Add polygon",
      symbol: "◇+",
      shortcut: "Click",
      disabled: readOnly || editor === null || editor.cardId === null,
      reason: "Select a visible card before adding a polygon.",
    },
    {
      action: "remove_polygon",
      label: "Remove polygon",
      symbol: "◇−",
      shortcut: "Click",
      disabled: readOnly || editor === null || editor.polygonCount <= 1,
      reason: "A visible card must keep one polygon.",
    },
    {
      action: "draw_ignore_region",
      label: "Draw ignore region",
      ariaLabel: "Draw ignore region in shared workbench",
      symbol: "⊘",
      shortcut: "Click",
      disabled: readOnly || !sourceAvailable,
      reason: "A resolved source frame is required to draw an ignore region.",
    },
    {
      action: "convert_to_ignore_region",
      label: "Convert selection to ignore region",
      symbol: "⇢",
      shortcut: "I",
      ariaShortcut: "I",
      disabled: readOnly || selectedCandidateCount === 0,
      reason:
        "Select one or more proposals to convert them to an ignore region.",
    },
    {
      action: "copy_ignore_regions",
      label: "Copy ignore regions",
      symbol: "⧉",
      shortcut: "Click",
      disabled: readOnly || !canCopyIgnoreRegions,
      reason: "Review an earlier frame with ignore regions first.",
    },
    {
      action: "delete_selection",
      label: "Delete selection",
      symbol: "⌫",
      shortcut: "Delete",
      ariaShortcut: "Delete",
      disabled:
        readOnly ||
        selection === null ||
        (selection.type !== "visible_card" &&
          selection.type !== "polygon" &&
          selection.type !== "ignore_region"),
      reason: "Select a visible card or ignore region first.",
    },
    {
      action: "restore_suggestion",
      label: "Restore suggestion",
      symbol: "↺",
      shortcut: "Click",
      disabled: readOnly || !canRestoreSuggestion,
      reason: "A generated suggestion is required to restore this frame.",
    },
  ];
  return (
    <TimelineRailSeekingControls
      groups={[
        {
          label: "Selection actions",
          controls: actions.map(
            ({
              action,
              label,
              ariaLabel,
              symbol,
              shortcut,
              ariaShortcut,
              disabled,
              reason,
            }) => ({
              label,
              ariaLabel,
              symbol,
              shortcut,
              ariaShortcut,
              disabled,
              disabledReason: reason,
              onClick: () => onAction(action),
            }),
          ),
        },
      ]}
    />
  );
}
