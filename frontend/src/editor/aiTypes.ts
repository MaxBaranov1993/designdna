export type AssistAction = "adapt" | "overflow" | "content-fit" | "align" | "style" | "custom";
export type AssistScopeMode = "single" | "selection" | "document";
export type AssistStage = "prepare" | "provider" | "validate";

export interface AssistProgress {
  stage: AssistStage;
  label: string;
  startedAt: number;
}

export interface AssistConstraints {
  allowContent: boolean;
  allowStyle: boolean;
  allowFrame: boolean;
  allowColor: boolean;
}

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
  validation: { schema: boolean; overflow: unknown[]; constraints: unknown[] };
}

export interface AssistRequest {
  prompt: string;
  action: AssistAction;
  scopeMode: AssistScopeMode;
  constraints: AssistConstraints;
  provider?: "openai";
  effort?: "medium" | "high" | "max";
  designSystemSelection?: string;
  designSystemUsageMode?: string;
}
