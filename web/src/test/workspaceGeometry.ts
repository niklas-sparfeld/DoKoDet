export type ViewportFixture = {
  name: string;
  width: number;
  height: number;
};

export const RECORDING_WORKSPACE_VIEWPORTS = {
  desktop: { name: "desktop", width: 1440, height: 900 },
  compactDesktop: { name: "compact desktop", width: 1280, height: 800 },
  narrow: { name: "narrow", width: 390, height: 844 },
} as const;

export type WorkspaceGeometry = {
  inspectorMinWidth: number;
  inspectorMaxWidth: number;
  topBarMaxHeight: number;
  railMinHeight: number;
  sourceBeforeInspectorOnNarrow: boolean;
};

export const WORKSPACE_GEOMETRY_LIMITS: WorkspaceGeometry = {
  inspectorMinWidth: 18 * 16,
  inspectorMaxWidth: 23 * 16,
  topBarMaxHeight: 7 * 16,
  railMinHeight: 6 * 16,
  sourceBeforeInspectorOnNarrow: true,
};

export function expectedWorkspaceGeometry(
  viewport: ViewportFixture,
): WorkspaceGeometry & { desktop: boolean } {
  return {
    ...WORKSPACE_GEOMETRY_LIMITS,
    desktop: viewport.width >= 1024,
  };
}

export function isDesktopWorkspaceViewport(viewport: ViewportFixture): boolean {
  return viewport.width >= 1024;
}
