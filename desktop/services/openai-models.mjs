// Product choices share one OpenAI credential and Responses transport.
// `astra` is a persisted UI route, not a separate credential/provider.
export const SOL_MODEL = "gpt-5.6-sol";
export const ASTRA_MODEL = "gpt-6-astra";
export const OPENAI_MODELS = Object.freeze([SOL_MODEL, ASTRA_MODEL]);

export function openaiModel(provider, model) {
  if (provider === "astra") return ASTRA_MODEL;
  const bare = String(model || "").replace(/^openai\//, "");
  return OPENAI_MODELS.includes(bare) ? bare : SOL_MODEL;
}
