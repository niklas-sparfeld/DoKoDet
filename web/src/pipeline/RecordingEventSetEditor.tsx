import { useCallback, useEffect, useState } from "react";

type EventRecord = {
  event_id: string;
  event_type: string;
  start_us: number;
  end_us: number;
};
type EventSet = {
  set_id: string;
  version: string;
  events: Array<{ event_id: string; relative_path: string }>;
  origin: string;
};
type EventSetList = {
  recording_version: number;
  head: Record<string, { set_id: string; version: string } | null>;
  event_sets: EventSet[];
};
type EventReview = {
  review_id: string;
  kind: string;
  decision: string | null;
  question: string;
};

export function RecordingEventSetEditor({
  recordingId,
}: {
  recordingId: string;
}) {
  const [data, setData] = useState<EventSetList | null>(null);
  const [selected, setSelected] = useState<{
    set_id: string;
    version: string;
  } | null>(null);
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [reviews, setReviews] = useState<EventReview[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const response = await fetch(
      `/api/recordings/${encodeURIComponent(recordingId)}/event-sets`,
    );
    if (!response.ok) throw new Error("Event sets could not be loaded.");
    const result = (await response.json()) as EventSetList;
    return result;
  }, [recordingId]);

  const open = useCallback(
    async (reference: { set_id: string; version: string }) => {
      const response = await fetch(
        `/api/recordings/${encodeURIComponent(recordingId)}/event-sets/${encodeURIComponent(reference.set_id)}/versions/${encodeURIComponent(reference.version)}`,
      );
      if (!response.ok)
        throw new Error("The selected event set could not be opened.");
      const saved = (await response.json()) as {
        content: { events: EventRecord[] };
      };
      setSelected({ set_id: reference.set_id, version: reference.version });
      setEvents(saved.content.events);
      const reviewsResponse = await fetch(
        `/api/recordings/${encodeURIComponent(recordingId)}/event-sets/${encodeURIComponent(reference.set_id)}/versions/${encodeURIComponent(reference.version)}/reviews`,
      );
      if (!reviewsResponse.ok)
        throw new Error("Event reviews could not be loaded.");
      const savedReviews = (await reviewsResponse.json()) as {
        reviews: EventReview[];
      };
      setReviews(savedReviews.reviews);
      setNotice(`Opened ${reference.set_id} version ${reference.version}.`);
    },
    [recordingId],
  );

  useEffect(() => {
    void load()
      .then((result) => {
        setData(result);
        const query = new URLSearchParams(window.location.search);
        const setId = query.get("set");
        const version = query.get("version");
        if (
          setId !== null &&
          version !== null &&
          result.event_sets.some(
            (item) => item.set_id === setId && item.version === version,
          )
        ) {
          void open({ set_id: setId, version }).catch(() =>
            setNotice("The exact event parent could not be opened."),
          );
        }
      })
      .catch(() => setNotice("Event sets could not be loaded."));
  }, [load, open]);

  const save = async (newAlternative: boolean) => {
    if (data === null) return;
    setBusy(true);
    try {
      const setId =
        newAlternative || selected === null
          ? `manual-${crypto.randomUUID()}`
          : selected.set_id;
      const version =
        newAlternative || selected === null
          ? "1"
          : String(Number(selected.version) + 1);
      const response = await fetch(
        `/api/recordings/${encodeURIComponent(recordingId)}/event-sets`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            set_id: setId,
            version,
            content: { schema_version: "event-data/v1", events },
            origin: "manual",
            provenance:
              selected === null ? { source: null } : { source: selected },
          }),
        },
      );
      if (!response.ok) throw new Error("The event set could not be saved.");
      setSelected({ set_id: setId, version });
      setData(await load());
      setReviews([]);
      setNotice(`Saved ${setId} version ${version}.`);
    } catch {
      setNotice("The event set could not be saved.");
    } finally {
      setBusy(false);
    }
  };

  const review = async (decision: "accepted" | "rejected") => {
    if (selected === null) return;
    const reviewId = `review-${crypto.randomUUID()}`;
    const response = await fetch(
      `/api/recordings/${encodeURIComponent(recordingId)}/event-sets/${encodeURIComponent(selected.set_id)}/reviews`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          review_id: reviewId,
          set_id: selected.set_id,
          version: selected.version,
          kind: "overall",
          question: "Is this event set correct?",
          decision,
          reviewer: { id: "operator" },
          evidence: { policy: "event-review/v1", source: "event-set-editor" },
        }),
      },
    );
    if (!response.ok) {
      setNotice("The event-set review could not be saved.");
      return;
    }
    const review = (await response.json()) as EventReview;
    setReviews((items) => [...items, review]);
    setNotice(
      `Saved ${decision} review for ${selected.set_id} version ${selected.version}.`,
    );
  };

  const select = async (choice: "generated" | "reference") => {
    if (data === null || selected === null) return;
    try {
      const response = await fetch(
        `/api/recordings/${encodeURIComponent(recordingId)}/event-sets/selection`,
        {
          method: "PUT",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            choice,
            reference: { set_id: selected.set_id, version: selected.version },
            expected_recording_version: data.recording_version,
          }),
        },
      );
      if (!response.ok) throw new Error("Selection failed");
      setData(await load());
      setNotice(`Selected this event set as the ${choice} choice.`);
    } catch {
      setNotice(
        "The event-set selection changed elsewhere. Reload and try again.",
      );
      setData(await load());
    }
  };

  const addEvent = () =>
    setEvents((items) => [
      ...items,
      {
        event_id: crypto.randomUUID(),
        event_type: "card_state_changed",
        start_us: 0,
        end_us: 0,
      },
    ]);

  return (
    <section aria-label="Event sets">
      <h2>Event sets</h2>
      <p>
        Each saved version is immutable. Choose a saved version to inspect or
        edit.
      </p>
      <ul aria-label="Saved event-set versions">
        {(data?.event_sets ?? []).map((item) => (
          <li key={`${item.set_id}:${item.version}`}>
            <button
              type="button"
              onClick={() =>
                void open(item).catch(() =>
                  setNotice("Event set could not be opened."),
                )
              }
            >
              Open {item.set_id} version {item.version}
            </button>
            {data?.head.generated?.set_id === item.set_id &&
            data.head.generated.version === item.version
              ? " · generated"
              : ""}
            {data?.head.reference?.set_id === item.set_id &&
            data.head.reference.version === item.version
              ? " · reference"
              : ""}
          </li>
        ))}
      </ul>
      <ol aria-label="Events to save">
        {events.map((event, index) => (
          <li key={event.event_id}>
            <label>
              Event type{" "}
              <input
                value={event.event_type}
                onChange={(change) =>
                  setEvents((items) =>
                    items.map((item, row) =>
                      row === index
                        ? { ...item, event_type: change.target.value }
                        : item,
                    ),
                  )
                }
              />
            </label>
            <label>
              Start (µs){" "}
              <input
                type="number"
                value={event.start_us}
                onChange={(change) =>
                  setEvents((items) =>
                    items.map((item, row) =>
                      row === index
                        ? { ...item, start_us: Number(change.target.value) }
                        : item,
                    ),
                  )
                }
              />
            </label>
            <label>
              End (µs){" "}
              <input
                type="number"
                value={event.end_us}
                onChange={(change) =>
                  setEvents((items) =>
                    items.map((item, row) =>
                      row === index
                        ? { ...item, end_us: Number(change.target.value) }
                        : item,
                    ),
                  )
                }
              />
            </label>
          </li>
        ))}
      </ol>
      <button type="button" onClick={addEvent}>
        Add event
      </button>
      <button type="button" disabled={busy} onClick={() => void save(false)}>
        Save event set
      </button>
      <button type="button" disabled={busy} onClick={() => void save(true)}>
        Save as alternative
      </button>
      <button
        type="button"
        disabled={selected === null}
        onClick={() => void select("generated")}
      >
        Select generated
      </button>
      <button
        type="button"
        disabled={selected === null}
        onClick={() => void select("reference")}
      >
        Select reference
      </button>
      <button
        type="button"
        disabled={selected === null}
        onClick={() => void review("accepted")}
      >
        Review as accepted
      </button>
      <button
        type="button"
        disabled={selected === null}
        onClick={() => void review("rejected")}
      >
        Review as rejected
      </button>
      <ul aria-label="Saved event-set reviews">
        {reviews.map((item) => (
          <li key={item.review_id}>
            {item.kind}: {item.decision ?? "coverage"} · {item.question}
          </li>
        ))}
      </ul>
      {notice ? <p role="status">{notice}</p> : null}
    </section>
  );
}
