import type { ReactNode } from "react";

export type ExactRevisionChoice = {
  nodeId: string;
  revisionId: string;
  label: string;
  provenance?: string;
  compatible: boolean;
};

export function ExactRevisionField({
  label,
  choices,
  value,
  onChange,
  required = true,
}: {
  label: string;
  choices: ExactRevisionChoice[];
  value: string;
  onChange: (revisionId: string) => void;
  required?: boolean;
}) {
  const usable = choices.filter((choice) => choice.compatible);
  return (
    <label>
      {label}
      <select
        aria-label={label}
        value={value}
        required={required}
        onChange={(event) => onChange(event.currentTarget.value)}
      >
        <option value="">Choose an exact revision</option>
        {usable.map((choice) => (
          <option
            key={`${choice.nodeId}:${choice.revisionId}`}
            value={`${choice.nodeId}:${choice.revisionId}`}
          >
            {choice.label} · {choice.revisionId}
            {choice.provenance ? ` · ${choice.provenance}` : ""}
          </option>
        ))}
      </select>
      {usable.length === 0 ? (
        <span role="status">No compatible revisions are available.</span>
      ) : null}
    </label>
  );
}

export type JobModelChoice = {
  id: string;
  label: string;
  available: boolean;
  reason?: string;
};

export function JobModelField({
  label,
  choices,
  value,
  onChange,
}: {
  label: string;
  choices: JobModelChoice[];
  value: string;
  onChange: (modelId: string) => void;
}) {
  const available = choices.filter((choice) => choice.available);
  const unavailable = choices.filter((choice) => !choice.available);
  return (
    <label>
      {label}
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.currentTarget.value)}
      >
        <option value="">Choose an available model</option>
        {available.map((choice) => (
          <option key={choice.id} value={choice.id}>
            {choice.label}
          </option>
        ))}
      </select>
      {unavailable.map((choice) => (
        <span key={choice.id}>
          {choice.label} unavailable{choice.reason ? `: ${choice.reason}` : ""}
        </span>
      ))}
      {available.length === 0 ? (
        <span role="status">No compatible models are available.</span>
      ) : null}
    </label>
  );
}

export function JobStartFieldGroup({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return <fieldset aria-label={label}>{children}</fieldset>;
}
