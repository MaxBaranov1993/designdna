/** Serialization of MCP tool results for the agent history.
 *  Limits are UTF-8 BYTES, and JSON is never sliced: an oversize result becomes
 *  an explicit structured error marker the model can read, instead of silently
 *  truncated bytes that would corrupt the round-two payload. */
export const MAX_TOOL_RESULT_BYTES = 16_000;

export type ToolResultSerialization = {
  text: string;
  oversize: boolean;
  code: string | null;
};

export function serializeToolResult(result: unknown, maxBytes: number = MAX_TOOL_RESULT_BYTES): ToolResultSerialization {
  let text: string;
  try {
    text = JSON.stringify(result) ?? "null";
  } catch (error) {
    return {
      text: JSON.stringify({
        error: { code: "TOOL_RESULT_UNSERIALIZABLE", message: String((error as Error)?.message || error) },
      }),
      oversize: false,
      code: "TOOL_RESULT_UNSERIALIZABLE",
    };
  }
  const bytes = new TextEncoder().encode(text).length;
  if (bytes > maxBytes) {
    return {
      text: JSON.stringify({ error: { code: "TOOL_RESULT_OVERSIZE", bytes, limit: maxBytes } }),
      oversize: true,
      code: "TOOL_RESULT_OVERSIZE",
    };
  }
  return { text, oversize: false, code: null };
}
