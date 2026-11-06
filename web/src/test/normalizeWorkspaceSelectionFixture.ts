export function normalizeWorkspaceSelectionFixture(
  overrides: Record<string, unknown>,
): Record<string, unknown> {
  const options = Array.isArray(overrides.input_options)
    ? overrides.input_options.filter(
        (value): value is Record<string, unknown> =>
          typeof value === "object" && value !== null,
      )
    : [];
  const exactRef = (id: string) => {
    const option = options.find(
      (candidate) =>
        candidate.revision_id === id || candidate.node_revision_id === id,
    );
    if (
      typeof option?.node_id === "string" &&
      typeof option.node_revision_id === "string"
    ) {
      return { node_id: option.node_id, revision_id: option.node_revision_id };
    }
    return { node_id: `node-${id}`, revision_id: `node-revision-${id}` };
  };
  const {
    selected_generated_revision_id: generatedId,
    selected_completed_reference_revision_id: referenceId,
    selected_generated: generated,
    selected_completed_reference: reference,
    ...rest
  } = overrides;
  const selectedGenerated =
    typeof generatedId === "string"
      ? exactRef(generatedId)
      : (generated ?? null);
  const selectedReference =
    typeof referenceId === "string"
      ? exactRef(referenceId)
      : (reference ?? null);
  return {
    ...rest,
    selected_generated: selectedGenerated,
    selected_completed_reference: selectedReference,
  };
}
