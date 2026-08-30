import type { RoundAnalysisStatus, RoundAnalysisTimeline } from "../api/client";

export const ANALYSIS_ID = "550e8400-e29b-41d4-a716-446655440033";

const PACKAGE_ID = "550e8400-e29b-41d4-a716-446655440035";

function observation(
  observationId: string,
  observedAtMs: number,
  card: string,
  probability: number,
) {
  return {
    schema_version: "table-observation/v1" as const,
    observation_id: observationId,
    source: { package_id: PACKAGE_ID },
    session: {
      session_id: "550e8400-e29b-41d4-a716-446655440034",
      event_sequence: observedAtMs / 1000,
    },
    observed_at_ms: observedAtMs,
    status: "observed" as const,
    capabilities: ["identity_candidates" as const],
    cards: [
      {
        observed_card_id: `${observationId}-card-01`,
        identity_candidates: [
          { card, probability },
          ...(probability < 1
            ? [{ card: "CLUBS_NINE", probability: 1 - probability }]
            : []),
        ],
      },
    ],
    calibration: "fixture" as const,
    analyzer: { name: "synthetic", version: "fixture-v1" },
  };
}

function action(
  observationId: string,
  card: string,
  probability: number,
  playIndex: number,
) {
  return {
    kind: "selected",
    observation_id: observationId,
    observed_card_id: `${observationId}-card-01`,
    play_index: playIndex,
    player: `player-0${playIndex}`,
    card,
    candidate_probability: probability,
    identity_log_score_contribution: Math.log(probability),
    visual_evidence_score: {
      presence: 0,
      newly_visible: 0,
      predecessor: 0,
      active_area: 0,
      tracklet: 0,
    },
    score_contribution: Math.log(probability),
  };
}

const scoreBreakdown = {
  identity_candidate_log_score: 0,
  ignored_observed_card_count: 0,
  inferred_missing_play_count: 0,
  visual_evidence_score: {
    presence: 0,
    newly_visible: 0,
    predecessor: 0,
    active_area: 0,
    tracklet: 0,
  },
};

export const resolvedTimeline = {
  schema_version: "round-analysis-timeline/v1",
  analysis_id: ANALYSIS_ID,
  recording_id: "recording-0033",
  round_id: "round-0033",
  session_id: "550e8400-e29b-41d4-a716-446655440034",
  reconstruction_status: "resolved",
  search: {
    max_missing_plays: 40,
    max_hypotheses: 8,
    max_search_nodes: 1000,
  },
  diagnostics: { truncated: false },
  artifact_hashes: {
    input_artifact_id: `round-analyses/${ANALYSIS_ID}/input.json`,
    input_sha256: "a".repeat(64),
    result_artifact_id: `round-analyses/${ANALYSIS_ID}/result.json`,
    result_sha256: "b".repeat(64),
  },
  rows: [
    {
      observation_id: "observation-001",
      package_id: PACKAGE_ID,
      event_sequence: 1,
      event_time_ms: 1000,
      observed_at_ms: 1000,
      central_frame: {
        package_id: PACKAGE_ID,
        part_name: "frame_00",
        url: `/v1/round-analyses/${ANALYSIS_ID}/evidence-packages/${PACKAGE_ID}/frames/frame_00`,
        actual_offset_ms: 12,
        captured_at_utc: "2026-08-30T12:00:01Z",
        width: 1920,
        height: 1080,
        byte_length: 123,
        content_type: "image/jpeg",
        sha256: "c".repeat(64),
      },
      table_observation: observation(
        "observation-001",
        1000,
        "DIAMONDS_JACK",
        0.75,
      ),
    },
    {
      observation_id: "observation-002",
      package_id: PACKAGE_ID,
      event_sequence: 2,
      event_time_ms: 2000,
      observed_at_ms: 2000,
      central_frame: null,
      table_observation: observation("observation-002", 2000, "HEARTS_TEN", 1),
    },
  ],
  hypotheses: [
    {
      rank: 1,
      gameplay: {
        plays: [
          { player: "player-01", card: "DIAMONDS_JACK" },
          { player: "player-02", card: "HEARTS_TEN" },
        ],
        tricks: [],
        initial_hands: {},
      },
      source_observation_ids: ["observation-001", "observation-002"],
      source_observed_card_ids: [
        "observation-001-card-01",
        "observation-002-card-01",
      ],
      ignored_observed_card_ids: [],
      missing_play_indices: [],
      actions: [
        action("observation-001", "DIAMONDS_JACK", 0.75, 1),
        action("observation-002", "HEARTS_TEN", 1, 2),
      ],
      total_score: -0.287682072,
      score_breakdown: scoreBreakdown,
      inferred_plays: [],
    },
    {
      rank: 2,
      gameplay: {
        plays: [
          { player: "player-01", card: "CLUBS_NINE" },
          { player: "player-02", card: "HEARTS_TEN" },
        ],
        tricks: [],
        initial_hands: {},
      },
      source_observation_ids: ["observation-001", "observation-002"],
      source_observed_card_ids: [
        "observation-001-card-01",
        "observation-002-card-01",
      ],
      ignored_observed_card_ids: [],
      missing_play_indices: [],
      actions: [
        action("observation-001", "CLUBS_NINE", 0.25, 1),
        action("observation-002", "HEARTS_TEN", 1, 2),
      ],
      total_score: -1.386294361,
      score_breakdown: scoreBreakdown,
      inferred_plays: [],
    },
  ],
  focused_decisions: [],
  inferred_plays: [],
  warnings: [],
} satisfies RoundAnalysisTimeline;

export const resolvedStatus = {
  analysis_id: ANALYSIS_ID,
  recording_id: "recording-0033",
  round_id: "round-0033",
  session_id: "550e8400-e29b-41d4-a716-446655440034",
  state: "complete",
  total_evidence_packages: 2,
  completed_evidence_packages: 2,
  result: {
    analysis_id: ANALYSIS_ID,
    diagnostics: {},
    focused_decisions: [],
    hypotheses: [],
    input_artifact_id: `round-analyses/${ANALYSIS_ID}/input.json`,
    input_artifact_sha256: "a".repeat(64),
    reconstruction_status: "resolved",
    result_artifact_id: `round-analyses/${ANALYSIS_ID}/result.json`,
    result_artifact_sha256: "b".repeat(64),
    terminal_status: "complete",
  },
  error: null,
  created_at: "2026-08-30T12:00:00Z",
  started_at: "2026-08-30T12:00:01Z",
  completed_at: "2026-08-30T12:00:02Z",
} satisfies RoundAnalysisStatus;
