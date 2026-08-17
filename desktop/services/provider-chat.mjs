const KIMI_URL = "https://api.moonshot.ai/v1/chat/completions";

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

export async function chatWithKimi({ apiKey, messages, temperature = 0.8, fetchImpl = fetch, environment = process.env }) {
  if (!apiKey) throw new Error("Ключ Kimi не сохранён. Откройте Agents → Connections.");
  const payload = {
    model: environment.DESIGNDNA_KIMI_MODEL || "kimi-k2.5",
    messages: cleanMessages(messages),
    temperature: Math.max(0, Math.min(1, Number(temperature) || 0)),
    response_format: { type: "json_object" },
  };
  const response = await fetchImpl(environment.DESIGNDNA_KIMI_URL || KIMI_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(180_000),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`Kimi HTTP ${response.status}: ${data.error?.message || data.message || "request failed"}`);
  const content = String(data.choices?.[0]?.message?.content || "");
  if (!content.trim()) throw new Error("Kimi вернул пустой ответ");
  return content;
}
