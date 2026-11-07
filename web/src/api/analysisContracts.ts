import type { components, paths } from "./openapi";

type JsonResponse<Response> = Response extends { content: infer Content }
  ? Content extends { "application/json": infer Payload }
    ? Payload
    : never
  : never;

export type RoundAnalysisStatus = JsonResponse<
  paths["/v1/round-analyses/{analysis_id}"]["get"]["responses"][200]
>;
export type RoundAnalysisCreateRequest =
  components["schemas"]["RoundAnalysisCreateRequest"];
export type RoundAnalysisTimeline = JsonResponse<
  paths["/v1/round-analyses/{analysis_id}/timeline"]["get"]["responses"][200]
>;
export type RoundCounterfactualCreateRequest =
  components["schemas"]["RoundCounterfactualCreateRequest"];
export type RoundCounterfactualResponse = JsonResponse<
  paths["/v1/round-analyses/{analysis_id}/counterfactuals/{counterfactual_id}"]["get"]["responses"][200]
>;
