export type DetectionSetVersion = {
  schema_version: "detection-set/v1";
  recording_id: string;
  set_id: string;
  version: string;
  origin: string;
  source: { source_video_sha256: string };
  producer: Record<string, unknown>;
  event_sets: Array<Record<string, string>>;
  content_sha256: string;
  content: {
    frames: Array<{
      frame_id: string;
      frame_identity: Record<string, unknown>;
      event_ids: Array<Record<string, string>>;
      detections: Array<{
        object_id: string;
        kind: string;
        side: string | null;
        segments: Array<{
          segment_id: string;
          polygon: Array<{ x: number; y: number }>;
        }>;
      }>;
    }>;
  };
};

export type DetectionGeometryReview = {
  schema_version: "detection-review/v1";
  recording_id: string;
  review_id: string;
  set_id: string;
  version: string;
  content_sha256: string;
  reviewer: { kind: "human"; id: string };
  question: string;
  decision: "accepted" | "rejected";
  covered_frame_ids: string[];
  covered_object_ids: string[];
  reviewed_at: string;
};

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    ...(body === undefined ? {} : { method: "POST" }),
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export function getDetectionSetVersion(
  recordingId: string,
  setId: string,
  version: string,
) {
  return request<DetectionSetVersion>(
    `/api/recordings/${encodeURIComponent(recordingId)}/detection-sets/${encodeURIComponent(setId)}/versions/${encodeURIComponent(version)}`,
  );
}

export function saveDetectionSetVersion(
  recordingId: string,
  version: Omit<DetectionSetVersion, "content_sha256" | "content"> & {
    content: DetectionSetVersion["content"];
  },
) {
  return request<DetectionSetVersion>(
    `/api/recordings/${encodeURIComponent(recordingId)}/detection-sets`,
    {
      set_id: version.set_id,
      version: version.version,
      origin: "corrected",
      source: version.source,
      producer: { ...version.producer, parent_version: version.version },
      event_sets: version.event_sets,
      frames: version.content.frames,
    },
  );
}

export function listDetectionSetReviews(
  recordingId: string,
  setId: string,
  version: string,
) {
  return request<{
    reviews: DetectionGeometryReview[];
  }>(
    `/api/recordings/${encodeURIComponent(recordingId)}/detection-sets/${encodeURIComponent(setId)}/versions/${encodeURIComponent(version)}/reviews`,
  );
}

export function saveDetectionSetReview(
  recordingId: string,
  setId: string,
  version: string,
  payload: {
    review_id: string;
    reviewer: { kind: "human"; id: string };
    question: string;
    decision: "accepted" | "rejected";
    covered_frame_ids: string[];
    covered_object_ids: string[];
  },
) {
  return request<DetectionGeometryReview>(
    `/api/recordings/${encodeURIComponent(recordingId)}/detection-sets/${encodeURIComponent(setId)}/versions/${encodeURIComponent(version)}/reviews`,
    payload,
  );
}
