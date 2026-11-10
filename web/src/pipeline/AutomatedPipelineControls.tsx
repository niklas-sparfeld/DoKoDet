import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { createPipelineProcessingClient } from "../api/pipelineProcessingClient";
import { createRecordingsClient } from "../api/recordingsClient";
import {
  type AutomatedPipelineRun,
  type AutomatedPipelineStartRequest,
  type PipelineWorkspace,
  type PipelineWorkspaceStage,
} from "../api/pipelineContracts";
import { type RecordingDetail } from "../api/recordingContracts";
import { ApiError } from "../api/transport";
import styles from "../App.module.css";
import { useJobState } from "../jobs/JobState";
import { JobStartActions, type JobStartAction } from "../jobs/JobStartActions";
import { recordingPipelinePath } from "./recordingPipelineUrl";

const STAGES = [
  ["event_proposals", "events", "events", "Event proposals", {}],
  [
    "visible_card_and_pile_proposals",
    "visible_cards",
    "visible_cards",
    "Visible cards and piles",
    { provider: "local-rfdetr-segmentation" },
  ],
  [
    "card_scene_and_calibration",
    null,
    "visible_cards",
    "Card scenes and calibration",
    {},
  ],
  [
    "visual_identity_proposals",
    "visual_identities",
    "visual_identities",
    "Visual identities",
    { provider: "local" },
  ],
  [
    "table_observations",
    "table_observations",
    "table_observations",
    "Table observations",
    {},
  ],
  ["reconstruction", "round_analyses", "round_analyses", "Round analysis", {}],
] as const;

type RoundFacts = {
  gameId: string;
  roundId: string;
  players: string;
  dealer: string;
  firstTrickLeader: string;
};

type StageSetting = { model: string; configuration: string };

export function AutomatedPipelineControls({
  recordingId,
  workspace,
  onRefresh,
}: {
  recordingId: string;
  workspace: PipelineWorkspace;
  onRefresh: () => Promise<void>;
}) {
  const client = useMemo(
    () => ({
      ...createRecordingsClient(),
      ...createPipelineProcessingClient(),
    }),
    [],
  );
  const { refresh: refreshJobs } = useJobState();
  const [recording, setRecording] = useState<RecordingDetail | null>(null);
  const [facts, setFacts] = useState<RoundFacts>({
    gameId: "",
    roundId: "",
    players: "",
    dealer: "",
    firstTrickLeader: "",
  });
  const [settings, setSettings] = useState<Record<string, StageSetting>>(() =>
    Object.fromEntries(
      STAGES.map(([key, workspaceKey, , , fallback]) => {
        const stage =
          workspaceKey === null
            ? undefined
            : workspace.stages.find((item) => item.key === workspaceKey);
        const latest = stage?.runs[0] as
          | (PipelineWorkspaceStage["runs"][number] & {
              model?: Record<string, unknown> | null;
              configuration?: Record<string, unknown>;
            })
          | undefined;
        const previous = latest?.configuration ?? latest?.request.configuration;
        return [
          key,
          {
            model: JSON.stringify(latest?.model ?? {}),
            configuration: JSON.stringify({
              ...fallback,
              ...(previous && typeof previous === "object" ? previous : {}),
            }),
          },
        ];
      }),
    ),
  );
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const pendingRequest = useRef<AutomatedPipelineStartRequest | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [acceptedRun, setAcceptedRun] = useState<AutomatedPipelineRun | null>(
    null,
  );

  useEffect(() => {
    let cancelled = false;
    void client
      .getRecording(recordingId)
      .then((value) => {
        if (cancelled) return;
        setRecording(value);
        setFacts((current) => ({
          ...current,
          roundId: current.roundId || value.round_id || "",
        }));
      })
      .catch((reason: unknown) => {
        if (!cancelled)
          setMessage(
            reason instanceof Error
              ? reason.message
              : "Recording context could not be loaded.",
          );
      });
    return () => {
      cancelled = true;
    };
  }, [client, recordingId]);

  const parsedSettings = useMemo(
    () =>
      Object.fromEntries(
        STAGES.map(([key]) => {
          const current = settings[key] ?? { model: "{}", configuration: "{}" };
          try {
            const model = JSON.parse(current.model) as unknown;
            const configuration = JSON.parse(current.configuration) as unknown;
            if (!isObject(model) || !isObject(configuration)) throw new Error();
            return [key, { model, configuration }];
          } catch {
            return [key, null];
          }
        }),
      ),
    [settings],
  );

  const inputErrors = [
    ...(!recording
      ? ["Load the recording source context before starting."]
      : []),
    ...(recording && !recording.video
      ? ["An accepted source video is required."]
      : []),
    ...(!facts.gameId.trim() ? ["Enter the game ID."] : []),
    ...(!facts.roundId.trim() ? ["Enter the round ID."] : []),
    ...(facts.players
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean).length !== 4
      ? ["Enter four active player IDs, separated by commas."]
      : []),
    ...(!facts.dealer.trim() ? ["Enter the dealer ID."] : []),
    ...(!facts.firstTrickLeader.trim()
      ? ["Enter the first-trick leader ID."]
      : []),
    ...STAGES.filter(([key]) => parsedSettings[key] === null).map(
      ([, , , label]) =>
        `${label}: model and configuration must be JSON objects.`,
    ),
  ];
  const errors = [...(message ? [message] : []), ...inputErrors];

  const updateFact = (key: keyof RoundFacts, value: string) => {
    if (!uncertain) setMessage(null);
    setFacts((current) => ({ ...current, [key]: value }));
  };
  const updateSetting = (
    stage: string,
    key: keyof StageSetting,
    value: string,
  ) => {
    if (!uncertain) setMessage(null);
    setSettings((current) => ({
      ...current,
      [stage]: { ...current[stage], [key]: value },
    }));
  };

  const action: JobStartAction = {
    id: "automated-pipeline",
    label: "Run complete pipeline",
    description:
      "Run all six supported stages against the accepted source video. The server preflight freezes the video, round facts, providers, models, configuration, and search limits before it starts the parent job.",
    expectedOutput:
      "Fresh event, visible-card, card-scene, identity, observation, and round-analysis results, linked to one parent job in Jobs.",
    sections: [
      {
        title: "Source context",
        content: recording ? (
          <dl>
            <div>
              <dt>Recording</dt>
              <dd>{recording.recording_id}</dd>
            </div>
            <div>
              <dt>Accepted video</dt>
              <dd>
                {workspace.video?.relative_path ??
                  recording.video?.url ??
                  "Missing"}
              </dd>
            </div>
            <div>
              <dt>Video digest</dt>
              <dd>
                {workspace.video?.video_sha256 ?? recording.source_sha256}
              </dd>
            </div>
            <div>
              <dt>Session</dt>
              <dd>{recording.session_id}</dd>
            </div>
          </dl>
        ) : (
          <p>Loading exact source context…</p>
        ),
      },
      {
        title: "Round facts",
        content: (
          <fieldset disabled={busy || uncertain}>
            <label>
              Game ID
              <input
                value={facts.gameId}
                onChange={(event) => updateFact("gameId", event.target.value)}
              />
            </label>
            <label>
              Round ID
              <input
                value={facts.roundId}
                onChange={(event) => updateFact("roundId", event.target.value)}
              />
            </label>
            <label>
              Four active player IDs
              <input
                value={facts.players}
                onChange={(event) => updateFact("players", event.target.value)}
                placeholder="player-a, player-b, player-c, player-d"
              />
            </label>
            <label>
              Dealer ID
              <input
                value={facts.dealer}
                onChange={(event) => updateFact("dealer", event.target.value)}
              />
            </label>
            <label>
              First-trick leader ID
              <input
                value={facts.firstTrickLeader}
                onChange={(event) =>
                  updateFact("firstTrickLeader", event.target.value)
                }
              />
            </label>
          </fieldset>
        ),
      },
      {
        title: "Stage models and configuration",
        content: (
          <div className={styles.pipelineRunControls}>
            {STAGES.map(([key, , , label]) => (
              <fieldset key={key} disabled={busy || uncertain}>
                <legend>{label}</legend>
                <label>
                  Model JSON
                  <textarea
                    value={settings[key]?.model ?? "{}"}
                    onChange={(event) =>
                      updateSetting(key, "model", event.target.value)
                    }
                  />
                </label>
                <label>
                  Configuration JSON
                  <textarea
                    value={settings[key]?.configuration ?? "{}"}
                    onChange={(event) =>
                      updateSetting(key, "configuration", event.target.value)
                    }
                  />
                </label>
              </fieldset>
            ))}
          </div>
        ),
      },
      {
        title: "Rules and search limits",
        content: (
          <dl>
            <div>
              <dt>Rules</dt>
              <dd>doko-normal v1</dd>
            </div>
            <div>
              <dt>Maximum missing plays</dt>
              <dd>1</dd>
            </div>
            <div>
              <dt>Maximum hypotheses</dt>
              <dd>256</dd>
            </div>
            <div>
              <dt>Maximum search nodes</dt>
              <dd>250000</dd>
            </div>
          </dl>
        ),
      },
    ],
  };

  const start = useCallback(async () => {
    if (inputErrors.length > 0 || !recording) return false;
    setBusy(true);
    setMessage(null);
    const roundPlayers = facts.players.split(",").map((value) => value.trim());
    const stage_requests = Object.fromEntries(
      STAGES.map(([key]) => {
        const stage = parsedSettings[key];
        if (stage === null || stage === undefined)
          throw new Error(`Invalid ${key} settings.`);
        return [key, stage];
      }),
    );
    const payload: AutomatedPipelineStartRequest = pendingRequest.current ?? {
      idempotency_key: crypto.randomUUID(),
      session_id: recording.session_id,
      round_context: {
        game_id: facts.gameId.trim(),
        round_id: facts.roundId.trim(),
        active_players: roundPlayers,
        dealer: facts.dealer.trim(),
        first_trick_leader: facts.firstTrickLeader.trim(),
      },
      rules_version: "v1",
      search: {
        max_missing_plays: 1,
        max_hypotheses: 256,
        max_search_nodes: 250000,
      },
      stage_requests,
    };
    pendingRequest.current = payload;
    try {
      const accepted = await client.startAutomatedPipelineRun(
        recordingId,
        payload,
      );
      if (!accepted.job_id)
        throw new Error(
          "The pipeline preflight accepted a run without a parent job ID.",
        );
      pendingRequest.current = null;
      setUncertain(false);
      setAcceptedRun(accepted);
      await refreshJobs();
      void onRefresh().catch(() => undefined);
      return true;
    } catch (reason) {
      const rejected =
        reason instanceof ApiError &&
        reason.status >= 400 &&
        reason.status < 500;
      if (rejected) pendingRequest.current = null;
      setUncertain(!rejected);
      setMessage(
        rejected
          ? describePreflightError(reason)
          : `Acceptance is uncertain. Retry to reconcile the same pipeline request. ${describePreflightError(reason)}`,
      );
      return false;
    } finally {
      setBusy(false);
    }
  }, [
    client,
    inputErrors.length,
    facts,
    onRefresh,
    parsedSettings,
    recording,
    recordingId,
    refreshJobs,
  ]);

  return (
    <section
      className={styles.pipelineRunControls}
      aria-label="Complete pipeline actions"
    >
      <JobStartActions
        actions={[action]}
        loading={!recording}
        submitting={busy}
        validationErrors={errors}
        canSubmit={inputErrors.length === 0}
        onStart={start}
      />
      {message ? (
        <p role="alert" className={styles.pipelineRunMessage}>
          {message}
        </p>
      ) : null}
      {acceptedRun ? (
        <div role="status">
          <p>
            Fresh pipeline run {acceptedRun.run_id} · {acceptedRun.status} ·{" "}
            <a
              href={`/jobs/${encodeURIComponent(acceptedRun.job_id ?? acceptedRun.run_id)}`}
            >
              View parent job in Jobs
            </a>
          </p>
          <ol>
            {acceptedRun.stages.map((stage) => {
              const definition = STAGES.find(([name]) => name === stage.name);
              if (!definition) return null;
              const [, , routeStage, label] = definition;
              const analysisId =
                stage.name === "reconstruction"
                  ? stage.output_revision_ids[0]
                  : null;
              return (
                <li key={stage.name}>
                  {label}: {stage.status}
                  {stage.child_job_id
                    ? ` · child job ${stage.child_job_id}`
                    : ""}
                  {stage.input_revision_ids.length
                    ? ` · inputs ${stage.input_revision_ids.join(", ")}`
                    : ""}
                  {stage.output_revision_ids.length
                    ? ` · outputs ${stage.output_revision_ids.join(", ")}`
                    : ""}{" "}
                  —{" "}
                  <a
                    href={recordingPipelinePath(
                      recordingId,
                      routeStage,
                      analysisId ? { analysis: analysisId } : {},
                    )}
                  >
                    Open results
                  </a>
                </li>
              );
            })}
          </ol>
        </div>
      ) : null}
    </section>
  );
}

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function describePreflightError(reason: unknown): string {
  if (!(reason instanceof ApiError)) {
    return reason instanceof Error
      ? reason.message
      : "Pipeline preflight failed.";
  }
  if (isObject(reason.body) && isObject(reason.body.error)) {
    const details = reason.body.error.details;
    if (Array.isArray(details)) {
      const messages = details
        .filter(isObject)
        .map((detail) => detail.message)
        .filter((message): message is string => typeof message === "string");
      if (messages.length) return messages.join(" ");
    }
    if (typeof reason.body.error.message === "string")
      return reason.body.error.message;
  }
  return reason.message;
}
