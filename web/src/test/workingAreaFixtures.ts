export type WorkingAreaStep =
  | "events"
  | "visible_cards"
  | "virtual_scenes"
  | "visual_identities"
  | "table_observations"
  | "round_analyses";

export type WorkingAreaFrameIdentity = {
  sourceId: string;
  frameId: string;
  width: number;
  height: number;
  contentSha256: string;
  requestedTimeUs: number | null;
  resolvedTimeUs: number | null;
};

export type WorkingAreaFixture = {
  step: WorkingAreaStep;
  frame:
    | { state: "loading"; requestedTimeUs: number | null }
    | { state: "ready"; identity: WorkingAreaFrameIdentity; imageUrl: string }
    | {
        state: "missing" | "failed";
        requestedTimeUs: number | null;
        reason: string;
      };
  selection: {
    node: { nodeId: string; revisionId: string } | null;
    itemId: string | null;
    analysisId: string | null;
    hypothesisRank: number | null;
  };
  evidence: Record<string, unknown>;
};

const frame: WorkingAreaFrameIdentity = {
  sourceId: "recording-fixture",
  frameId: "frame-001",
  width: 1920,
  height: 1080,
  contentSha256: "a".repeat(64),
  requestedTimeUs: 1_000_000,
  resolvedTimeUs: 1_000_000,
};

const base = {
  frame: { state: "ready" as const, identity: frame, imageUrl: "/fixture.jpg" },
  selection: {
    node: { nodeId: "node-1", revisionId: "revision-1" },
    itemId: "item-1",
    analysisId: null,
    hypothesisRank: null,
  },
  evidence: {},
};

export const workingAreaStepFixtures = [
  { ...base, step: "events" },
  { ...base, step: "visible_cards" },
  { ...base, step: "virtual_scenes" },
  { ...base, step: "visual_identities" },
  { ...base, step: "table_observations" },
  { ...base, step: "round_analyses" },
] satisfies WorkingAreaFixture[];

export const missingCalibrationFixture: WorkingAreaFixture = {
  ...base,
  step: "virtual_scenes",
  evidence: {
    overlayFrame: frame,
    requiresCalibration: true,
    calibration: null,
    expectedOverlayVisible: false,
    expectedEditingEnabled: false,
    reason: "No exact table-plane calibration is available.",
  },
};

export const intervalOnlyEvidenceFixture: WorkingAreaFixture = {
  ...base,
  step: "table_observations",
  selection: { ...base.selection, itemId: "interval-1" },
  evidence: {
    startUs: 1_000_000,
    endUs: 2_500_000,
    sourceFrameId: null,
    expectedSeek: false,
  },
};

export const untimedInferredActionFixture: WorkingAreaFixture = {
  ...base,
  step: "round_analyses",
  selection: {
    ...base.selection,
    analysisId: "analysis-1",
    hypothesisRank: 1,
  },
  evidence: {
    kind: "inferred_play",
    playIndex: 4,
    requestedTimeUs: null,
    resolvedFrameId: null,
    expectedRailRow: true,
    expectedSeek: false,
  },
};

export const comparisonFixture = {
  leftRunId: "run-left",
  rightRunId: "run-right",
  referenceRevisionId: "reference-r1",
};

export const emptyAndFailedFixtures = [
  { state: "empty", reason: "No exact revision is selected." },
  { state: "failed", reason: "The selected result failed." },
] as const;

export const historicalReadOnlyFixture = {
  headRevisionId: "revision-2",
  selectedRevisionId: "revision-1",
  expectedEditable: false,
} as const;
