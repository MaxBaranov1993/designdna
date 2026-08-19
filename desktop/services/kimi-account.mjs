import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const TOKEN_URL = "https://auth.kimi.com/api/oauth/token";
// Public OAuth client id hardcoded in the official Kimi CLI.
const CLIENT_ID = "17e5f671-d194-4dfb-9706-5516cb48c098";
// Treat tokens as expired slightly early to avoid mid-request expiry.
const TOKEN_SKEW_MS = 60_000;

function cliCredentialsPath(kimiCodeHome) {
  const home = kimiCodeHome || process.env.KIMI_CODE_HOME || path.join(os.homedir(), ".kimi-code");
  return path.join(home, "credentials", "kimi-code.json");
}

// The kimi credential is either a plain API key or a JSON OAuth bundle
// ({access_token, refresh_token, expires_at}) imported from the Kimi CLI.
function parseBundle(raw) {
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && typeof parsed.access_token === "string") return parsed;
  } catch {
    // Not JSON — treat as a plain API key.
  }
  return null;
}

function validateBundle(parsed, source) {
  const accessToken = String(parsed?.access_token || "").trim();
  if (!accessToken) {
    throw new Error(`В файле учётных данных Kimi CLI (${source}) нет access_token. Выполните вход в Kimi CLI (команда kimi), затем повторите импорт.`);
  }
  return {
    access_token: accessToken,
    refresh_token: parsed?.refresh_token ? String(parsed.refresh_token) : null,
    expires_at: Number(parsed?.expires_at) || null,
  };
}

export function importFromCli(credentials, { kimiCodeHome } = {}) {
  const file = cliCredentialsPath(kimiCodeHome);
  let raw;
  try {
    raw = fs.readFileSync(file, "utf8");
  } catch (error) {
    if (error.code === "ENOENT") {
      throw new Error(`Файл учётных данных Kimi CLI не найден (${file}). Выполните вход в Kimi CLI (команда kimi), затем повторите импорт.`);
    }
    throw error;
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error(`Не удалось разобрать учётные данные Kimi CLI (${file}). Выполните вход в Kimi CLI (команда kimi), затем повторите импорт.`);
  }
  const bundle = validateBundle(parsed, file);
  credentials.set("kimi", JSON.stringify(bundle));
  return kimiAccountStatus(credentials);
}

export async function getValidToken(credentials, { fetchImpl = fetch } = {}) {
  const raw = credentials.get("kimi");
  if (!raw) {
    throw new Error("Kimi не подключён. Явно импортируйте аккаунт Kimi CLI или добавьте ключ в Agents → Connections.");
  }
  const bundle = parseBundle(raw);
  if (!bundle) return raw; // Plain API key entered manually — use as-is.
  if (bundle.access_token && (!bundle.expires_at || bundle.expires_at * 1000 > Date.now() + TOKEN_SKEW_MS)) {
    return bundle.access_token;
  }
  if (!bundle.refresh_token) {
    throw new Error("Токен Kimi истёк, а refresh_token отсутствует. Повторите импорт из Kimi CLI (Agents → Connections).");
  }
  // The Kimi OAuth host expects a form-encoded body (same shape as the CLI's
  // device-flow token calls).
  const response = await fetchImpl(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
    body: new URLSearchParams({ grant_type: "refresh_token", refresh_token: bundle.refresh_token, client_id: CLIENT_ID }).toString(),
    signal: AbortSignal.timeout(30_000),
  });
  const data = await response.json().catch(() => ({}));
  const accessToken = String(data?.access_token || "");
  if (!response.ok || !accessToken) {
    throw new Error(`Не удалось обновить токен Kimi (HTTP ${response.status}). Повторите импорт из Kimi CLI или выполните вход заново (команда kimi).`);
  }
  const refreshed = {
    access_token: accessToken,
    refresh_token: String(data.refresh_token || bundle.refresh_token),
    expires_at: Number(data.expires_in) ? Math.floor(Date.now() / 1000) + Number(data.expires_in) : bundle.expires_at,
  };
  // Persist the rotated tokens only in our own credential store — the Kimi CLI
  // credentials file is never written back.
  credentials.set("kimi", JSON.stringify(refreshed));
  return refreshed.access_token;
}

export function kimiAccountStatus(credentials) {
  const raw = credentials.get("kimi");
  if (!raw) return { connected: false, kind: null, expiresAt: null };
  const bundle = parseBundle(raw);
  if (!bundle) return { connected: true, kind: "api-key", expiresAt: null };
  return { connected: true, kind: "oauth", expiresAt: bundle.expires_at || null };
}
