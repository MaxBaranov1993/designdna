import crypto from "node:crypto";

/* Canonical-spec approval for executable MCP config.
 *
 * Saving or refreshing MCP servers spawns local processes (stdio command/args).
 * That activation must be gated by a NATIVE main-process approval — never by a
 * renderer prompt, because a compromised renderer is exactly the actor we are
 * defending against. The approval is computed over a canonical serialization of
 * the executable spec (no secret values, credential variable names only), so
 * what the user approves is byte-identical to what gets persisted and spawned:
 * any later config change produces a different hash and re-prompts. */

/** Executable part of the config, normalized: enabled servers only, sorted,
 *  credential ENV variable names (never resolved secret values). */
export function canonicalMcpSpec(servers) {
  return (Array.isArray(servers) ? servers : [])
    .filter((server) => server && server.enabled !== false)
    .map((server) => ({
      id: String(server.id || ""),
      name: String(server.name || ""),
      transport: String(server.transport || ""),
      command: String(server.command || ""),
      args: (Array.isArray(server.args) ? server.args : []).map(String),
      credentialEnv: Object.entries(server.credentialEnv || {})
        .map(([variable, provider]) => [String(variable), String(provider)])
        .sort(([left], [right]) => left.localeCompare(right)),
    }))
    .sort((a, b) => a.id.localeCompare(b.id));
}

export function mcpSpecHash(spec) {
  return crypto.createHash("sha256").update(JSON.stringify(spec), "utf8").digest("hex");
}

/** Human-readable spec shown in the native approval dialog. */
export function summarizeMcpSpec(spec) {
  return spec
    .map((server) => {
      const commandLine = [server.command, ...server.args].filter(Boolean).join(" ");
      const credentials = server.credentialEnv.length
        ? `\n    credentials → ${server.credentialEnv.map(([variable, provider]) => `${variable}:${provider}`).join(", ")}`
        : "";
      return `• ${server.name} (${server.transport})\n    ${commandLine}${credentials}`;
    })
    .join("\n");
}

/** Approver with per-session cache: a canonical spec is approved once; any
 *  config change (new hash) requires a fresh native approval. `showMessageBox`
 *  is injected so tests can stub the native dialog. */
export function createMcpActivationApprover({ showMessageBox }) {
  if (typeof showMessageBox !== "function") throw new Error("showMessageBox is required");
  const approvedHashes = new Set();
  return {
    /** Returns true when the spec may be activated (approved now or earlier). */
    async ensureApproved(spec) {
      const hash = mcpSpecHash(spec);
      if (approvedHashes.has(hash)) return true;
      if (!spec.length) {
        // Nothing executable — persisting/refreshing an empty config spawns nothing.
        approvedHashes.add(hash);
        return true;
      }
      const result = await showMessageBox({
        type: "warning",
        title: "Запуск MCP-серверов",
        message: "DesignDNA запустит локальные процессы MCP-серверов.",
        detail: `Проверьте команды — они выполняются на этом компьютере с вашими правами:\n\n${summarizeMcpSpec(spec)}`,
        buttons: ["Разрешить запуск", "Отмена"],
        defaultId: 1,
        cancelId: 1,
        noLink: true,
      });
      if (result && result.response === 0) {
        approvedHashes.add(hash);
        return true;
      }
      return false;
    },
  };
}
