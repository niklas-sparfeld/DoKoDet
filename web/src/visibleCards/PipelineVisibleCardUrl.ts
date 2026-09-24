export function readPipelineEditorUrlState(): {
  item: string | null;
  tUs: number | null;
} {
  const params = new URLSearchParams(window.location.search);
  const raw = params.get("t_us");
  return {
    item: params.get("item"),
    tUs: raw !== null && /^\d+$/.test(raw) ? Number(raw) : null,
  };
}
export function updatePipelineUrl(values: {
  item?: string | null;
  t_us?: number | null;
}): void {
  const params = new URLSearchParams(window.location.search);
  for (const [key, value] of Object.entries(values)) {
    if (value === null || value === undefined) params.delete(key);
    else params.set(key, String(value));
  }
  const query = params.toString();
  window.history.replaceState(
    {},
    "",
    `${window.location.pathname}${query === "" ? "" : `?${query}`}`,
  );
  window.dispatchEvent(new PopStateEvent("popstate"));
}
