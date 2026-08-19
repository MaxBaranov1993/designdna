import { getValidToken } from "./kimi-account.mjs";

const KIMI_URL = "https://api.kimi.com/coding/v1/chat/completions";
const OPENAI_URL = "https://api.openai.com/v1/chat/completions";

function cleanMessages(messages) {
  if (!Array.isArray(messages) || !messages.length) throw new Error("Provider messages are required");
  return messages.map((message) => {
    const role = String(message?.role || "");
    const content = String(message?.content || "");
    if (!new Set(["system", "user", "assistant"]).has(role) || !content.trim()) {
      throw new Error("Invalid provider message");
    }
    return { role, content };
  });
}

export async function chatWithKimi({ credentials, messages, temperature = 0.8, fetchImpl = fetch, environment = process.env }) {
  // Resolves a plain API key as-is or a fresh OAuth access token (refreshing
  // and persisting rotated tokens when needed).
  const token = await getValidToken(credentials, { fetchImpl });
  const payload = {
    model: environment.DESIGNDNA_KIMI_MODEL || "k3",
    messages: cleanMessages(messages),
    // K3 on the managed coding endpoint rejects any temperature other than 1
    // ("only 1 is allowed for this model") — let the server default apply.
    response_format: { type: "json_object" },
  };
  const url = environment.DESIGNDNA_KIMI_URL || KIMI_URL;
  const post = (body) => fetchImpl(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(180_000),
  });
  let response = await post(payload);
  if (response.status === 400) {
    // Some models reject response_format — retry once without it.
    const { response_format, ...withoutFormat } = payload;
    response = await post(withoutFormat);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`Kimi HTTP ${response.status}: ${data.error?.message || data.message || "request failed"}`);
  const content = String(data.choices?.[0]?.message?.content || "");
  if (!content.trim()) throw new Error("Kimi вернул пустой ответ");
  return content;
}

export async function chatWithOpenAI({ credentials, messages, temperature = 0.8, fetchImpl = fetch, environment = process.env }) {
  const key = credentials.get("openai");
  if (!key) throw new Error("Нет OpenAI API key: добавьте его в Agents → Connections");
  const payload = {
    model: environment.DESIGNDNA_OPENAI_MODEL || "gpt-5.6-sol",
    messages: cleanMessages(messages),
    temperature: Math.max(0, Math.min(1, Number(temperature) || 0)),
    response_format: { type: "json_object" },
  };
  const response = await fetchImpl(environment.DESIGNDNA_OPENAI_URL || OPENAI_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(180_000),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`OpenAI HTTP ${response.status}: ${data.error?.message || data.message || "request failed"}`);
  const content = String(data.choices?.[0]?.message?.content || "");
  if (!content.trim()) throw new Error("OpenAI вернул пустой ответ");
  return content;
}
