import { useEffect, useState } from "react";
import type { PipelineWorkspaceStage } from "../api/pipelineContracts";

type EventSetRow = {
  set_id: string;
  version: string;
  provenance?: {
    source_metadata?: {
      legacy_revision_id?: unknown;
    };
    source_content_sha256?: unknown;
  };
};

type EventSetList = { event_sets: EventSetRow[] };
type EventSetDetail = { content_sha256: string };
type ParentLinkResult = { href: string; label: string } | { error: string };

function selectedOutput(stage: PipelineWorkspaceStage) {
  const selected =
    stage.selected_completed_reference ?? stage.selected_generated;
  const output = stage.input_options.find(
    (option) =>
      option.node_id === selected?.node_id &&
      option.node_revision_id === selected?.revision_id,
  );
  return { selected, output };
}

export function LegacyEventParentLink({
  recordingId,
  stage,
}: {
  recordingId: string;
  stage: PipelineWorkspaceStage;
}) {
  const [result, setResult] = useState<{
    key: string;
    value: ParentLinkResult;
  } | null>(null);
  const { selected, output } = selectedOutput(stage);
  const lookupKey = JSON.stringify([
    recordingId,
    selected?.node_id ?? null,
    selected?.revision_id ?? null,
    output?.coverage.event_set_ref ?? null,
    output?.coverage.event_revision_id ?? null,
  ]);

  useEffect(() => {
    let cancelled = false;
    const setCurrentResult = (value: ParentLinkResult) => {
      if (!cancelled) setResult({ key: lookupKey, value });
    };
    const load = async () => {
      const eventSetRef = output?.coverage.event_set_ref;
      if (eventSetRef !== undefined && eventSetRef !== null) {
        if (!isEventSetRef(eventSetRef)) {
          setCurrentResult({
            error: "Exact event parent reference is invalid.",
          });
          return;
        }
        const detailResponse = await fetch(
          `/api/recordings/${encodeURIComponent(recordingId)}/event-sets/${encodeURIComponent(eventSetRef.set_id)}/versions/${encodeURIComponent(eventSetRef.version)}`,
        );
        if (!detailResponse.ok)
          throw new Error("Exact event parent could not be opened.");
        const detail = (await detailResponse.json()) as EventSetDetail;
        if (detail.content_sha256 !== eventSetRef.content_sha256) {
          setCurrentResult({
            error: "Exact event parent digest does not match.",
          });
          return;
        }
        setCurrentResult(makeEventSetLink(recordingId, eventSetRef));
        return;
      }
      const legacyId = output?.coverage.event_revision_id;
      if (selected === null) {
        setResult(null);
        return;
      }
      if (typeof legacyId !== "string" || legacyId.length === 0) {
        setCurrentResult({
          error: "Exact event parent provenance is missing.",
        });
        return;
      }
      const listResponse = await fetch(
        `/api/recordings/${encodeURIComponent(recordingId)}/event-sets`,
      );
      if (!listResponse.ok) throw new Error("Event sets could not be checked.");
      const list = (await listResponse.json()) as EventSetList;
      const candidates = list.event_sets.filter(
        (item) =>
          item.provenance?.source_metadata?.legacy_revision_id === legacyId,
      );
      if (candidates.length === 0) {
        setCurrentResult({ error: "Exact event parent is missing." });
        return;
      }
      if (candidates.length !== 1) {
        setCurrentResult({ error: "Exact event parent is ambiguous." });
        return;
      }
      const [parent] = candidates;
      const sourceDigest = parent.provenance?.source_content_sha256;
      if (typeof sourceDigest !== "string" || sourceDigest.length === 0) {
        setCurrentResult({ error: "Exact event parent has no source digest." });
        return;
      }
      const detailResponse = await fetch(
        `/api/recordings/${encodeURIComponent(recordingId)}/event-sets/${encodeURIComponent(parent.set_id)}/versions/${encodeURIComponent(parent.version)}`,
      );
      if (!detailResponse.ok)
        throw new Error("Exact event parent could not be opened.");
      const detail = (await detailResponse.json()) as EventSetDetail;
      if (detail.content_sha256 !== sourceDigest) {
        setCurrentResult({
          error: "Exact event parent digest does not match.",
        });
        return;
      }
      setCurrentResult(makeEventSetLink(recordingId, parent));
    };
    void load().catch(() => {
      setCurrentResult({ error: "Exact event parent could not be checked." });
    });
    return () => {
      cancelled = true;
    };
  }, [lookupKey, output, recordingId, selected]);

  if (result === null || result.key !== lookupKey) return null;
  if ("error" in result.value) return <p role="status">{result.value.error}</p>;
  return <a href={result.value.href}>{result.value.label}</a>;
}

function isEventSetRef(
  value: unknown,
): value is { set_id: string; version: string; content_sha256: string } {
  return (
    typeof value === "object" &&
    value !== null &&
    "set_id" in value &&
    typeof value.set_id === "string" &&
    "version" in value &&
    typeof value.version === "string" &&
    "content_sha256" in value &&
    typeof value.content_sha256 === "string"
  );
}

function makeEventSetLink(
  recordingId: string,
  reference: { set_id: string; version: string },
) {
  const query = new URLSearchParams({
    set: reference.set_id,
    version: reference.version,
  });
  return {
    href: `/recordings/${encodeURIComponent(recordingId)}/event-sets?${query}`,
    label: `Open exact event parent ${reference.set_id}@${reference.version}`,
  };
}
