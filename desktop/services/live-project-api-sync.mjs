import { LiveProjectSession, assertSha256Revision } from "./live-project-session.mjs";

const PROJECT_LOAD_PATH = "/api/project/load";
const PROJECT_SAVE_PATH = "/api/project/save";
const DEFAULT_USER_ID = "local-user";
const DEFAULT_PROJECT_ID = "default";
const EMPTY_UPDATED_AT = "1970-01-01T00:00:00.000Z";

function decodeRequestBody(request) {
  const body = request?.body;
  if (body instanceof Uint8Array) return new TextDecoder("utf-8", { fatal: true }).decode(body);
  if (typeof body === "string") return body;
  throw new TypeError("Project API request body must be UTF-8 JSON");
}

function parseObject(text, label) {
  const value = JSON.parse(text);
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${label} must be a JSON object`);
  }
  return value;
}

function responseJson(response) {
  if (!response || response.status < 200 || response.status >= 300) return null;
  let text;
  if (typeof response.body === "string") {
    text = response.encoding === "base64"
      ? Buffer.from(response.body, "base64").toString("utf8")
      : response.body;
  } else if (response.bodyBytes instanceof Uint8Array) {
    text = Buffer.from(response.bodyBytes).toString("utf8");
  } else if (response.body instanceof Uint8Array) {
    text = Buffer.from(response.body).toString("utf8");
  } else {
    return null;
  }
  return parseObject(text, "Project API response");
}

function strictUtc(value, fallback = EMPTY_UPDATED_AT) {
  if (value == null || value === "") return fallback;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) throw new TypeError("Project timestamp is invalid");
  return date.toISOString();
}

export class LiveProjectApiSync {
  constructor({ registry = null, onEvent = null, maxProjectBytes } = {}) {
    this.registry = registry;
    this.onEvent = typeof onEvent === "function" ? onEvent : null;
    this.maxProjectBytes = maxProjectBytes;
    this.sessions = new Map();
  }

  prepare(request) {
    const path = String(request?.path || "").split("?", 1)[0];
    if (path !== PROJECT_LOAD_PATH && path !== PROJECT_SAVE_PATH) return null;
    const payload = parseObject(decodeRequestBody(request), "Project API request");
    const userId = String(payload.user_id || DEFAULT_USER_ID);
    const projectId = String(payload.project_id || DEFAULT_PROJECT_ID);
    const session = this.#session(userId, projectId);
    const context = { path, payload, session, userId, projectId, wasHydrated: this.#isHydrated(session) };
    if (path === PROJECT_SAVE_PATH) {
      if (payload.project === null || typeof payload.project !== "object" || Array.isArray(payload.project)) {
        throw new TypeError("project must be a JSON object");
      }
      session.validateProject(payload.project);
      const expectedRevision = assertSha256Revision(payload.expectedRevision, "expectedRevision");
      if (context.wasHydrated && expectedRevision !== session.currentRevision()) {
        const error = new Error("Project save does not match the authoritative desktop revision");
        error.code = "STALE_REVISION";
        error.currentRevision = session.currentRevision();
        throw error;
      }
      context.expectedRevision = expectedRevision;
    }
    return context;
  }

  synchronize(context, response) {
    if (!context) return null;
    const body = responseJson(response);
    if (!body) return null;
    if (context.path === PROJECT_LOAD_PATH) {
      const project = body.project && typeof body.project === "object" && !Array.isArray(body.project) ? body.project : {};
      return context.session.hydrateFromLoad(project, body.revision, strictUtc(body.updated_at));
    }
    if (body.ok !== true) return null;
    const updatedAt = strictUtc(body.updated_at);
    if (context.wasHydrated) {
      return context.session.notePersistedSave(
        context.payload.project,
        context.expectedRevision,
        body.revision,
        updatedAt,
      );
    }
    return context.session.hydrateFromLoad(context.payload.project, body.revision, updatedAt);
  }

  get(userId = DEFAULT_USER_ID, projectId = DEFAULT_PROJECT_ID) {
    return this.sessions.get(`${userId}:${projectId}`) || null;
  }

  getSnapshot(userId = DEFAULT_USER_ID, projectId = DEFAULT_PROJECT_ID) {
    const session = this.get(userId, projectId);
    if (!session || !this.#isHydrated(session)) return null;
    return session.getSnapshot();
  }

  dispose() {
    for (const session of this.sessions.values()) session.dispose();
    this.sessions.clear();
  }

  #session(userId, projectId) {
    const key = `${userId}:${projectId}`;
    let session = this.sessions.get(key);
    if (session) return session;
    session = new LiveProjectSession({
      userId,
      projectId,
      registry: this.registry,
      ...(this.maxProjectBytes ? { maxProjectBytes: this.maxProjectBytes } : {}),
    });
    if (this.onEvent) session.subscribe(this.onEvent);
    this.sessions.set(key, session);
    return session;
  }

  #isHydrated(session) {
    try {
      session.currentRevision();
      return true;
    } catch (error) {
      if (error?.code === "SESSION_NOT_HYDRATED") return false;
      throw error;
    }
  }
}
