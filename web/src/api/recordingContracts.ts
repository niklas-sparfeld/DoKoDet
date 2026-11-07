import type { paths } from "./openapi";

type JsonResponse<Response> = Response extends { content: infer Content }
  ? Content extends { "application/json": infer Payload }
    ? Payload
    : never
  : never;

export type RecordingListResponse = JsonResponse<
  paths["/v1/recordings"]["get"]["responses"][200]
>;
export type RecordingDetail = JsonResponse<
  paths["/v1/recordings/{recording_id}"]["get"]["responses"][200]
>;
export type RecordingSummary = RecordingListResponse["recordings"][number];
export type RecordingAnalysisSummary = RecordingSummary["analyses"][number];
