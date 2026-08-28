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

function isLiveCapacityError(error) {
  return error?.code === "STATE_TOO_LARGE";
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
      try {
        // Канонизация проекта считается один раз и переиспользуется в
        // synchronize() — раньше 8-МБ проект канонизировался дважды на сейв.
        context.canonicalProject = session.validateProject(payload.project);
      } catch (error) {
        // The live-command bridge deliberately has a bounded in-memory state,
        // while the canonical SQLite project may be larger. Capacity of the
        // optional bridge must never block the ordinary project save path.
        if (!isLiveCapacityError(error)) throw error;
        this.#resetSession(userId, projectId);
        return { ...context, session: null, wasHydrated: false, bypassReason: error.code };
      }
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
    if (context.bypassReason) return null;
    const body = responseJson(response);
    if (!body) return null;
    if (context.path === PROJECT_LOAD_PATH) {
      const project = body.project && typeof body.project === "object" && !Array.isArray(body.project) ? body.project : {};
      try {
        return context.session.hydrateFromLoad(project, body.revision, strictUtc(body.updated_at));
      } catch (error) {
        // A large canonical project remains fully usable in the editor; only
        // bounded live commands are unavailable until the state fits again.
        if (!isLiveCapacityError(error)) throw error;
        this.#resetSession(context.userId, context.projectId);
        return null;
      }
    }
    if (body.ok !== true) return null;
    const updatedAt = strictUtc(body.updated_at);
    if (context.wasHydrated) {
      return context.session.notePersistedSave(
        context.payload.project,
        context.expectedRevision,
        body.revision,
        updatedAt,
        { precomputed: context.canonicalProject || null },
      );
    }
    return context.session.hydrateFromLoad(context.payload.project, body.revision, updatedAt, {
      precomputed: context.canonicalProject || null,
    });
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

  #resetSession(userId, projectId) {
    const key = `${userId}:${projectId}`;
    const session = this.sessions.get(key);
    if (session) session.dispose();
    this.sessions.delete(key);
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
