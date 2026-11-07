import { createPortal } from "react-dom";
import { useEffect, useState } from "react";
import type { PipelineWorkspaceStage } from "../api/pipelineContracts";
import {
  GeometrySurface,
  type GeometryFrameIdentity,
  type GeometryOverlay,
} from "../workingArea/GeometrySurface";
import { useWorkingAreaFrame } from "../workingArea/workingAreaFrame";
import {
  getPipelineNodeRevision,
  type PipelineNodeRevision,
} from "./pipelineNodeClient";
import type { PipelineLineageGraph } from "./pipelineLineageSelection";

type RawRecord = Record<string, unknown>;
type SourceRevision = { nodeId: string; revisionId: string; label: string };

export function PipelineObservationWorkbench({
  recordingId,
  sourceSha256,
  stage,
  selectedItemId,
  selectedTimeUs,
  selectedNode,
  lineageGraph,
  onSelectNodeObservation,
}: {
  recordingId: string;
  sourceSha256: string;
  stage: PipelineWorkspaceStage;
  selectedItemId: string | null;
  selectedTimeUs: number | null;
  selectedNode?: { nodeId: string; revisionId: string } | null;
  lineageGraph?: PipelineLineageGraph | null;
  onSelectNodeObservation?: (itemId: string, timeUs: number | null) => void;
}) {
  const [loadedData, setLoadedData] = useState<{
    key: string;
    revision: PipelineNodeRevision | null;
    visibleRevisions: Array<{
      source: SourceRevision;
      revision: PipelineNodeRevision;
    }>;
    sourceErrors: string[];
    error: string | null;
  } | null>(null);
  const [selectedSource, setSelectedSource] = useState<string>("");
  const [selectedCard, setSelectedCard] = useState<{
    itemId: string;
    cardId: string;
  } | null>(null);
  const [portalTargets, setPortalTargets] = useState<{
    inspector: Element | null;
    rail: Element | null;
  }>({ inspector: null, rail: null });

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setPortalTargets({
        inspector: document.querySelector("[data-observation-inspector-slot]"),
        rail: document.querySelector("[data-observation-rail-slot]"),
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (selectedNode == null) return;
    let cancelled = false;
    const sourceReferences = visibleCardSources(
      selectedNode.nodeId,
      selectedNode.revisionId,
      lineageGraph ?? null,
    );
    const key = `${selectedNode.nodeId}:${selectedNode.revisionId}:${sourceReferences
      .map(sourceKey)
      .sort()
      .join(",")}`;
    void getPipelineNodeRevision(selectedNode.nodeId, selectedNode.revisionId)
      .then(async (loaded) => {
        if (
          loaded.content_type !== "table_observations" ||
          !Array.isArray(loaded.content.observations)
        )
          throw new Error(
            "The selected node does not contain table observations.",
          );
        const loadedSources = await Promise.all(
          sourceReferences.map(async (source) => ({
            source,
            result: await getPipelineNodeRevision(
              source.nodeId,
              source.revisionId,
            ).then(
              (revision) => ({ revision, error: null }),
              (reason: unknown) => ({
                revision: null,
                error:
                  reason instanceof Error ? reason.message : String(reason),
              }),
            ),
          })),
        );
        if (cancelled) return;
        setLoadedData({
          key,
          revision: loaded,
          visibleRevisions: loadedSources.flatMap((item) =>
            item.result.revision?.content_type === "visible_cards" &&
            Array.isArray(item.result.revision.content.outcomes)
              ? [{ source: item.source, revision: item.result.revision }]
              : [],
          ),
          sourceErrors: loadedSources.flatMap((item) =>
            item.result.error === null
              ? []
              : [
                  `${item.source.label} (${sourceKey(item.source)}): ${item.result.error}`,
                ],
          ),
          error: null,
        });
      })
      .catch((reason: unknown) => {
        if (!cancelled)
          setLoadedData({
            key,
            revision: null,
            visibleRevisions: [],
            sourceErrors: [],
            error: reason instanceof Error ? reason.message : String(reason),
          });
      });
    return () => {
      cancelled = true;
    };
  }, [lineageGraph, selectedNode]);

  const selectedRevisionKey =
    selectedNode == null
      ? null
      : `${selectedNode.nodeId}:${selectedNode.revisionId}:${visibleCardSources(
          selectedNode.nodeId,
          selectedNode.revisionId,
          lineageGraph ?? null,
        )
          .map(sourceKey)
          .sort()
          .join(",")}`;
  const revision =
    loadedData?.key === selectedRevisionKey ? loadedData.revision : null;
  const visibleRevisions =
    loadedData?.key === selectedRevisionKey ? loadedData.visibleRevisions : [];
  const sourceErrors =
    loadedData?.key === selectedRevisionKey ? loadedData.sourceErrors : [];
  const error =
    loadedData?.key === selectedRevisionKey ? loadedData.error : null;
  const failedRuns = stage.runs.filter(
    (run) => run.status === "failed" || run.status === "partial",
  );

  const observations =
    selectedNode === null || selectedNode === undefined
      ? legacyObservations(stage)
      : Array.isArray(revision?.content.observations)
        ? revision.content.observations.filter(isRecord)
        : [];
  const selected = observations.find(
    (value) => value.observation_id === selectedItemId,
  );
  const sources = visibleRevisions.map(
    ({ source, revision: sourceRevision }) => ({
      source,
      revision: sourceRevision,
    }),
  );
  const chosenSource =
    sources.find((item) => sourceKey(item.source) === selectedSource) ??
    sources[0];
  const linkedOutcome =
    selected === undefined || chosenSource === undefined
      ? undefined
      : linkedVisibleOutcome(selected, chosenSource.revision);
  const frameIdentity = asRecord(linkedOutcome?.frame_identity);
  const requestTimeUs =
    readNumber(frameIdentity, "requested_time_us") ?? selectedTimeUs ?? null;
  const frameState = useWorkingAreaFrame({
    recordingId,
    sourceId: recordingId,
    sourceSha256,
    requestedTimeUs: requestTimeUs ?? 0,
    mode: "exact",
    ...(readNumber(frameIdentity, "frame_index") !== null
      ? { frameIndex: readNumber(frameIdentity, "frame_index") as number }
      : {}),
  });
  const frameMatches =
    frameState.state === "ready" &&
    linkedOutcome !== undefined &&
    frameMatchesOutcome(
      frameState.frame.identity,
      frameState.frame.resolvedTimeUs,
      frameState.frame.requestedTimeUs,
      linkedOutcome,
    );
  const overlays =
    frameMatches && selected !== undefined && linkedOutcome !== undefined
      ? observedCardOverlays(selected, linkedOutcome, frameState.frame.identity)
      : [];

  const inspector = (
    <section aria-label="Selected table observation">
      <h2>{revision?.name ?? "Table observations"}</h2>
      <p>
        {selectedNode == null
          ? "No exact node revision selected · "
          : `Revision ${selectedNode.revisionId} · `}
        {observations.length} observation
        {observations.length === 1 ? "" : "s"}
      </p>
      {error !== null ? (
        <p role="alert">Observation data unavailable: {error}</p>
      ) : null}
      {selected === undefined ? (
        <p>
          {selectedItemId === null
            ? "Select an observation interval from the Timeline Rail."
            : selectedNode == null
              ? "The selected observation result is missing."
              : "The selected observation is missing from this exact revision."}
        </p>
      ) : (
        <>
          <dl>
            <div>
              <dt>Observation</dt>
              <dd>{String(selected.observation_id)}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>{String(selected.status ?? "Unavailable")}</dd>
            </div>
            <div>
              <dt>Observed cards</dt>
              <dd>{cardsOf(selected).length}</dd>
            </div>
            <div>
              <dt>Capabilities</dt>
              <dd>{stringList(selected.capabilities) || "Unavailable"}</dd>
            </div>
            <div>
              <dt>Source time</dt>
              <dd>{formatTime(readNumber(selected, "observed_at_ms"))}</dd>
            </div>
          </dl>
          {cardsOf(selected).length === 0 ? (
            <p>
              {selected.status === "observed"
                ? "This observation has zero observed cards."
                : selected.status === "insufficient_evidence"
                  ? "This observation had insufficient evidence; zero cards is not reported."
                  : selected.status === "failed"
                    ? "This observation failed; zero cards is not reported."
                    : `This observation has status ${String(selected.status ?? "unavailable")}; zero cards is not reported.`}
            </p>
          ) : (
            <ul aria-label="Observed cards">
              {cardsOf(selected).map((card) => (
                <li key={String(card.observed_card_id)}>
                  <button
                    type="button"
                    aria-pressed={
                      selectedCard?.itemId === selectedItemId &&
                      card.observed_card_id === selectedCard.cardId
                    }
                    onClick={() =>
                      setSelectedCard(
                        typeof card.observed_card_id === "string"
                          ? {
                              itemId: selectedItemId ?? "",
                              cardId: card.observed_card_id,
                            }
                          : null,
                      )
                    }
                  >
                    {String(card.observed_card_id)}
                  </button>{" "}
                  · {String(card.side)} · {String(card.identity_status)}
                  {Array.isArray(card.identity_candidates)
                    ? ` · ${card.identity_candidates
                        .map((candidate) =>
                          isRecord(candidate)
                            ? `${String(candidate.card)} (${String(candidate.probability)})`
                            : "",
                        )
                        .filter(Boolean)
                        .join(", ")}`
                    : ""}
                </li>
              ))}
            </ul>
          )}
          {sources.length > 1 ? (
            <label>
              Spatial source
              <select
                aria-label="Spatial source"
                value={sourceKey(chosenSource?.source)}
                onChange={(event) => setSelectedSource(event.target.value)}
              >
                {sources.map(({ source }) => (
                  <option key={sourceKey(source)} value={sourceKey(source)}>
                    {source.label}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {sources.length === 0 ? (
            <p>
              {sourceErrors.length > 0
                ? `The linked visible-card source could not be loaded: ${sourceErrors.join("; ")}`
                : "No exact visible-card source revision is linked. Geometry is unavailable."}
            </p>
          ) : linkedOutcome === undefined ? (
            <p>
              No visible-card outcome matches this observation's exact event
              source. Geometry is unavailable.
            </p>
          ) : asRecord(linkedOutcome.frame_identity) === null ? (
            <p>
              This observation is interval evidence only. It has no exact source
              frame geometry.
            </p>
          ) : !frameMatches ? (
            <p>
              Linked geometry is hidden because the source frame identity does
              not match.
            </p>
          ) : overlays.length < cardsOf(selected).length ? (
            <p>
              Some observed cards have no exact spatial match. No geometry was
              drawn for those cards.
            </p>
          ) : null}
          {sources.length > 0 && sourceErrors.length > 0 ? (
            <p role="status">
              Some linked visible-card sources could not be loaded:{" "}
              {sourceErrors.join("; ")}
            </p>
          ) : null}
          <details>
            <summary>Exact spatial source links</summary>
            {sources.length === 0 ? (
              <p>No exact spatial source links are recorded.</p>
            ) : (
              <ul>
                {sources.map(({ source }) => (
                  <li key={sourceKey(source)}>
                    {source.label} ({source.nodeId} / {source.revisionId})
                  </li>
                ))}
              </ul>
            )}
          </details>
          <details>
            <summary>Observation details</summary>
            <pre>{JSON.stringify(selected, null, 2)}</pre>
          </details>
        </>
      )}
      {failedRuns.length > 0 ? (
        <section aria-label="Failed observation attempts">
          <h3>Failed and partial attempts</h3>
          <ul>
            {failedRuns.map((run) => (
              <li key={run.run_id}>
                {run.run_id} · {run.status} · inputs{" "}
                {run.input_revision_ids.join(", ") || "none"}
                {run.failure?.message ? ` · ${run.failure.message}` : ""}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {frameState.state === "failed" ? (
        <p role="alert">Source frame unavailable: {frameState.reason}</p>
      ) : null}
    </section>
  );

  const rail = (
    <nav aria-label="Table observation intervals">
      {selectedNode == null ? (
        <p>Select an observation interval in the Timeline Rail.</p>
      ) : observations.length === 0 ? (
        <p>This revision has no observations.</p>
      ) : (
        <ul>
          {observations.map((observation) => {
            const id =
              typeof observation.observation_id === "string"
                ? observation.observation_id
                : "";
            const sourceOutcome =
              chosenSource === undefined
                ? undefined
                : linkedVisibleOutcome(observation, chosenSource.revision);
            const timeUs = readNumber(
              asRecord(sourceOutcome?.frame_identity),
              "requested_time_us",
            );
            return (
              <li key={id}>
                <button
                  type="button"
                  aria-pressed={id === selectedItemId}
                  onClick={() => onSelectNodeObservation?.(id, timeUs)}
                >
                  {id} · {formatTime(readNumber(observation, "observed_at_ms"))}{" "}
                  · {String(observation.status ?? "unknown")} ·{" "}
                  {cardsOf(observation).length} cards
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );

  return (
    <>
      <section aria-label="Table observation source frame">
        {frameState.state === "ready" ? (
          <GeometrySurface
            frame={frameState.frame.identity}
            imageUrl={frameState.frame.imageUrl}
            overlays={overlays}
            selectedId={
              selectedCard?.itemId === selectedItemId
                ? selectedCard.cardId
                : null
            }
            onSelect={(cardId) =>
              setSelectedCard({ itemId: selectedItemId ?? "", cardId })
            }
          />
        ) : null}
      </section>
      {portalTargets.inspector !== null && frameState.state !== "ready"
        ? createPortal(
            <p role={frameState.state === "failed" ? "alert" : "status"}>
              {frameState.state === "failed"
                ? `Source frame unavailable: ${frameState.reason}`
                : "Loading exact source frame…"}
            </p>,
            portalTargets.inspector,
          )
        : null}
      {portalTargets.inspector === null
        ? null
        : createPortal(inspector, portalTargets.inspector)}
      {portalTargets.rail === null
        ? null
        : createPortal(rail, portalTargets.rail)}
    </>
  );
}

function visibleCardSources(
  nodeId: string,
  revisionId: string,
  graph: PipelineLineageGraph | null,
): SourceRevision[] {
  if (graph === null) return [];
  const target = JSON.stringify(["revision", nodeId, revisionId]);
  const producer = graph.edges.find(
    (edge) => edge.kind === "produced" && JSON.stringify(edge.to) === target,
  );
  if (producer === undefined) return [];
  const inputEdges = graph.edges.filter(
    (edge) =>
      edge.kind === "used" &&
      JSON.stringify(edge.to) === JSON.stringify(producer.from),
  );
  const nodes = new Map(graph.nodes.map((node) => [node.node_id, node]));
  return inputEdges.flatMap((edge) => {
    if (
      edge.from[0] !== "revision" ||
      edge.from[1] === undefined ||
      edge.from[2] === undefined
    )
      return [];
    const node = nodes.get(edge.from[1]);
    if (node?.content_type !== "visible_cards") return [];
    return [
      { nodeId: edge.from[1], revisionId: edge.from[2], label: node.name },
    ];
  });
}

function linkedVisibleOutcome(
  observation: RawRecord,
  revision: PipelineNodeRevision,
): RawRecord | undefined {
  const eventId = asRecord(asRecord(observation.diagnostics)?.assembly);
  const exactEventId = readString(eventId, "event_id");
  if (exactEventId === null) return undefined;
  return (
    Array.isArray(revision.content.outcomes) ? revision.content.outcomes : []
  )
    .filter(isRecord)
    .find((outcome) => outcome.event_id === exactEventId);
}

function legacyObservations(stage: PipelineWorkspaceStage): RawRecord[] {
  return stage.runs.flatMap((run) => {
    const items = Array.isArray(run.state.items) ? run.state.items : [];
    return items.flatMap((item) => {
      if (!isRecord(item) || !isRecord(item.result)) return [];
      return [{ ...item.result, observation_id: item.item_id }];
    });
  });
}

function observedCardOverlays(
  observation: RawRecord,
  outcome: RawRecord,
  frame: GeometryFrameIdentity,
): GeometryOverlay[] {
  const ids = new Set(
    cardsOf(observation)
      .map((card) => card.observed_card_id)
      .filter((id): id is string => typeof id === "string"),
  );
  const frameIdentity = asRecord(outcome.frame_identity);
  if (frameIdentity === null || !Array.isArray(outcome.candidates)) return [];
  return outcome.candidates.filter(isRecord).flatMap((candidate) => {
    if (typeof candidate.card_id !== "string" || !ids.has(candidate.card_id))
      return [];
    const geometry = asRecord(candidate.geometry);
    const polygons = geometry?.polygons;
    if (!Array.isArray(polygons) || !Array.isArray(polygons[0])) return [];
    const points = polygons[0].flatMap((point) => {
      if (
        !isRecord(point) ||
        typeof point.x !== "number" ||
        typeof point.y !== "number"
      )
        return [];
      return [
        [
          (point.x / 1000) * frame.width,
          (point.y / 1000) * frame.height,
        ] as const,
      ];
    });
    if (points.length < 3) return [];
    return [
      {
        id: candidate.card_id,
        label: "Observed card source",
        pattern: "dashed",
        frame,
        calibration: null,
        geometry: { kind: "polygon" as const, points },
      },
    ];
  });
}

function frameMatchesOutcome(
  frame: GeometryFrameIdentity,
  resolvedTimeUs: number,
  requestedTimeUs: number,
  outcome: RawRecord,
): boolean {
  const source = asRecord(outcome.frame_identity);
  return (
    source !== null &&
    source.source_video_sha256 === frame.sourceId.split(":").at(-1) &&
    source.requested_time_us === requestedTimeUs &&
    source.frame_index === Number(frame.frameId.split("@")[0]) &&
    source.presentation_timestamp_us === resolvedTimeUs &&
    source.width === frame.width &&
    source.height === frame.height &&
    source.image_sha256 === frame.contentSha256
  );
}

function sourceKey(source: SourceRevision | undefined): string {
  return source === undefined ? "" : `${source.nodeId}:${source.revisionId}`;
}
function cardsOf(observation: RawRecord): RawRecord[] {
  return Array.isArray(observation.cards)
    ? observation.cards.filter(isRecord)
    : [];
}
function asRecord(value: unknown): RawRecord | null {
  return isRecord(value) ? value : null;
}
function isRecord(value: unknown): value is RawRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function readNumber(value: RawRecord | null, key: string): number | null {
  return typeof value?.[key] === "number" && Number.isFinite(value[key])
    ? (value[key] as number)
    : null;
}
function readString(value: RawRecord | null, key: string): string | null {
  return typeof value?.[key] === "string" ? (value[key] as string) : null;
}
function stringList(value: unknown): string {
  return Array.isArray(value)
    ? value
        .filter((item): item is string => typeof item === "string")
        .join(", ")
    : "";
}
function formatTime(timeMs: number | null): string {
  return timeMs === null ? "Unavailable" : `${(timeMs / 1_000).toFixed(2)} s`;
}
