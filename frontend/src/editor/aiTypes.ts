export type AssistAction =
  | "adapt"
  | "overflow"
  | "content-fit"
  | "align"
  | "accessibility"
  | "rename-layers"
  | "style"
  | "custom";

export type AssistViewport = "current" | "desktop" | "tablet" | "mobile" | "all";

export interface AssistOp {
  op: "add" | "remove" | "replace";
  path: string;
  before?: unknown;
  after?: unknown;
  reason?: string;
}

export interface AssistPreview {
  summary: string;
  ops: AssistOp[];
  previewIr: any;
  changedViewports: string[];
  warnings: { code?: string; message: string; path?: string }[];
  validation: {
    schema: boolean;
    overflow: unknown[];
    constraints: unknown[];
  };
  action?: AssistAction;
}

export interface AssistRequest {
  prompt: string;
  action: AssistAction;
  viewport: AssistViewport;
}
