import styles from "../App.module.css";
import type { JobStartAction } from "../jobs/JobStartActions";
import type { PipelineRunStartRequest } from "../api/pipelineContracts";

function formatValue(value: unknown): string {
  if (value == null) return "None";
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  )
    return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return "Unavailable";
  }
}

export function buildEventLaunchFields({
  recordingId,
  blockers,
  request,
}: {
  recordingId: string;
  blockers: string[];
  request: PipelineRunStartRequest["request"];
}): JobStartAction {
  return {
    id: "event-processing",
    label: "Detect events",
    description:
      "Create a fresh event result from the accepted recording video. This starts queued processing and does not change review decisions.",
    expectedOutput:
      "A new event data revision that remains available for inspection and review.",
    sections: [
      {
        title: "Source",
        content: (
          <>
            <p>Recording: {recordingId}</p>
            <p>Source: accepted recording video</p>
            {blockers.map((blocker) => (
              <p className={styles.detailBlocker} key={blocker} role="alert">
                {blocker}
              </p>
            ))}
          </>
        ),
      },
      {
        title: "Processor",
        content: (
          <dl>
            <div>
              <dt>Implementation</dt>
              <dd>
                {request.implementation?.name ?? "cardeventnet"} ·{" "}
                {request.implementation?.version ?? "file-v1"}
              </dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd>{formatValue(request.model ?? null)}</dd>
            </div>
            <div>
              <dt>Configuration</dt>
              <dd>{formatValue(request.configuration)}</dd>
            </div>
            <div>
              <dt>Extraction policy</dt>
              <dd>{formatValue(request.extraction_policy)}</dd>
            </div>
          </dl>
        ),
      },
    ],
  };
}
