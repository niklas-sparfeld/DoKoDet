import type {
  RoundAnalysisStatus,
  RoundAnalysisTimeline,
  RoundCounterfactualResponse,
} from "../api/client";

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
  diagnostics: {
    ruleset: "doko-normal/v1",
    deck_variant: "doko-40-v1",
    capabilities: ["identity_candidates"],
    calibration_states: ["fixture"],
    observations_seen: 2,
    card_proposals_seen: 2,
    search_nodes: 4,
    complete_branches: 2,
    merged_branches: 0,
    rejected_branches: [],
    ignored_observations: [],
    incomplete_observations: [],
    search_limits: {
      max_missing_plays: 40,
      effective_missing_play_budget: 40,
      missing_play_slots: -1,
      max_hypotheses: 8,
      max_search_nodes: 1000,
    },
    truncated: false,
    evidence_families: ["identity_candidates"],
    ablated_evidence: [],
  },
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
  focused_decisions: [
    {
      kind: "card_play",
      play_index: 1,
      player: "player-01",
      alternatives: ["player-01:CLUBS_NINE", "player-01:DIAMONDS_JACK"],
      source_observation_ids: ["observation-001"],
      description:
        "card play 1 has retained legal alternatives: player-01:CLUBS_NINE, player-01:DIAMONDS_JACK",
    },
  ],
  inferred_plays: [],
  warnings: [],
} satisfies RoundAnalysisTimeline;

export const ambiguousTimeline = {
  ...resolvedTimeline,
  reconstruction_status: "ambiguous" as const,
  diagnostics: {
    ...resolvedTimeline.diagnostics,
    rejected_branches: [
      "search result truncated: maximum retained hypotheses reached (x2)",
    ],
    truncated: true,
  },
  warnings: [
    {
      code: "search_truncated",
      message:
        "The search reached a configured limit. Retained hypotheses may not include every legal sequence.",
    },
  ],
} satisfies RoundAnalysisTimeline;

const incompleteObservation = (() => {
  return {
    ...resolvedTimeline.rows[0],
    table_observation: {
      ...resolvedTimeline.rows[0].table_observation,
      status: "insufficient_evidence" as const,
      cards: undefined,
      diagnostics: { reason: "The frame did not contain enough evidence." },
    },
  };
})();

export const incompleteTimeline = {
  ...resolvedTimeline,
  reconstruction_status: "incomplete" as const,
  rows: [incompleteObservation, resolvedTimeline.rows[1]],
  hypotheses: [],
  focused_decisions: [],
  diagnostics: {
    ...resolvedTimeline.diagnostics,
    card_proposals_seen: 1,
    incomplete_observations: ["observation-001"],
    rejected_branches: [
      "incomplete result: fewer card proposals than the complete card-play count (1 < 2) (x1)",
    ],
  },
  warnings: [
    {
      code: "insufficient_evidence",
      message: "One or more table observations do not contain enough evidence.",
    },
    {
      code: "missing_frame",
      message: "One or more evidence packages have no usable central frame.",
    },
  ],
} satisfies RoundAnalysisTimeline;

export const impossibleTimeline = {
  ...resolvedTimeline,
  reconstruction_status: "impossible" as const,
  hypotheses: [],
  focused_decisions: [],
  diagnostics: {
    ...resolvedTimeline.diagnostics,
    rejected_branches: [
      "impossible result: no legal complete hypothesis survived replay (x3)",
    ],
  },
  warnings: [
    {
      code: "impossible_input",
      message:
        "No legal complete hypothesis survived replay under the selected ruleset.",
    },
  ],
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

function statusForTimeline(
  timeline: RoundAnalysisTimeline,
): RoundAnalysisStatus {
  return {
    ...resolvedStatus,
    result: {
      ...resolvedStatus.result,
      reconstruction_status: timeline.reconstruction_status,
      diagnostics: timeline.diagnostics,
      focused_decisions: timeline.focused_decisions,
      hypotheses: timeline.hypotheses,
    },
  };
}

export const ambiguousStatus = statusForTimeline(ambiguousTimeline);
export const incompleteStatus = statusForTimeline(incompleteTimeline);
export const impossibleStatus = statusForTimeline(impossibleTimeline);

const CHANGED_COUNTERFACTUAL_ID = "550e8400-e29b-41d4-a716-446655440036";
const UNCHANGED_COUNTERFACTUAL_ID = "550e8400-e29b-41d4-a716-446655440037";

function counterfactualResult(
  counterfactualId: string,
  timeline: RoundAnalysisTimeline,
): Record<string, unknown> {
  return {
    schema_version: "round-reconstruction-result/v2",
    run_id: counterfactualId,
    operations_version: "fixture-v1",
    request_sha256: "d".repeat(64),
    sources: [],
    search: timeline.search,
    status: timeline.reconstruction_status,
    hypotheses: timeline.hypotheses,
    focused_decisions: timeline.focused_decisions,
    diagnostics: timeline.diagnostics,
  };
}

function counterfactualResponse(
  counterfactualId: string,
  result: Record<string, unknown>,
): RoundCounterfactualResponse {
  const request = {
    schema_version: "round-analysis-counterfactual/v1" as const,
    counterfactual_id: counterfactualId,
    source_analysis_id: ANALYSIS_ID,
    source_input_sha256: "a".repeat(64),
    source_result_sha256: "b".repeat(64),
    excluded_observation_ids: ["observation-001"],
    excluded_observed_cards: [],
    card_identity_overrides: [],
    candidate_probability_overrides: [],
  };
  const artifact = (name: string) => ({
    relative_path:
      "round-analyses/" +
      ANALYSIS_ID +
      "/counterfactuals/" +
      counterfactualId +
      "/" +
      name +
      ".json",
    byte_length: 1,
    sha256: "e".repeat(64),
  });
  return {
    schema_version: "round-analysis-counterfactual-response/v1",
    counterfactual_id: counterfactualId,
    source_analysis_id: ANALYSIS_ID,
    request,
    artifacts: {
      request: artifact("request"),
      input: artifact("input"),
      result: artifact("result"),
    },
    result,
  };
}

const changedBestHypothesis = {
  ...resolvedTimeline.hypotheses[1],
  rank: 1,
  total_score: -1.386294361,
};
const changedSecondHypothesis = {
  ...resolvedTimeline.hypotheses[0],
  rank: 2,
  total_score: -0.287682072,
};

const changedCounterfactualTimeline = {
  ...resolvedTimeline,
  reconstruction_status: "ambiguous" as const,
  hypotheses: [changedBestHypothesis, changedSecondHypothesis],
  focused_decisions: [],
  diagnostics: {
    ...resolvedTimeline.diagnostics,
    search_nodes: 2,
    complete_branches: 1,
    truncated: true,
  },
};

export const changedCounterfactualResponse = counterfactualResponse(
  CHANGED_COUNTERFACTUAL_ID,
  counterfactualResult(
    CHANGED_COUNTERFACTUAL_ID,
    changedCounterfactualTimeline,
  ),
);

export const unchangedCounterfactualResponse = counterfactualResponse(
  UNCHANGED_COUNTERFACTUAL_ID,
  counterfactualResult(UNCHANGED_COUNTERFACTUAL_ID, resolvedTimeline),
);
