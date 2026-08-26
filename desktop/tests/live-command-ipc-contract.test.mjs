import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const main = readFileSync(new URL("../main.mjs", import.meta.url), "utf8");
const preload = readFileSync(new URL("../preload.cjs", import.meta.url), "utf8");
const desktopTypes = readFileSync(new URL("../../frontend/src/desktop.d.ts", import.meta.url), "utf8");

test("Electron creates one live command registry with explicit handlers only", () => {
  assert.match(main, /new LiveCommandRegistry\(\{ approve: requestLiveCommandApproval \}\)/);
  for (const action of ["session.get", "project.get", "pages.list", "graph.get", "command.list", "changes.since"]) {
    assert.match(main, new RegExp(`registry\\.register\\(\\"${action.replace(".", "\\.")}\\"`));
  }
  for (const action of ["graph.node.create", "graph.node.delete", "graph.node.move", "editor.style.patch", "history.undo"]) {
    assert.match(main, new RegExp(`registry\\.register\\(\\"${action.replace(".", "\\.")}\\"`));
  }
  assert.doesNotMatch(main, /registry\.register\("source\.capture"/);
});

test("project load and save responses synchronize the authoritative desktop session", () => {
  assert.match(main, /new LiveProjectApiSync/);
  assert.match(main, /liveProjects\.prepare\(validatedRequest\)/);
  assert.match(main, /liveProjects\.synchronize\(liveProjectContext, response\)/);
  assert.match(main, /error\?\.code === "STALE_REVISION"/);
});

test("Codex and provider MCP loops share the internal live command tool", () => {
  assert.match(main, /LIVE_COMMAND_TOOL_NAME = "designdna_live_command"/);
  assert.match(main, /dynamicTools: \[\.\.\.mcp\.dynamicTools\(\), liveCommandDynamicTool\(\)\]/);
  assert.match(main, /message\.params\.tool === LIVE_COMMAND_TOOL_NAME/);
  assert.match(main, /String\(name\) === LIVE_COMMAND_TOOL_NAME/);
  assert.match(main, /session\.currentRevision\(\)/);
});

test("approved graph mutations round-trip through the renderer and wait for persisted revision", () => {
  assert.match(main, /new RendererCommandBridge/);
  assert.match(main, /registry\.register\("graph\.node\.create", serializedRendererMutation\)/);
  assert.match(main, /registry\.register\("graph\.node\.delete", serializedRendererMutation\)/);
  assert.match(main, /registry\.register\("graph\.node\.move", serializedRendererMutation\)/);
  assert.match(main, /registry\.register\("editor\.style\.patch", serializedRendererMutation\)/);
  assert.match(main, /registry\.register\("history\.undo", serializedRendererMutation\)/);
  assert.match(main, /waitForPersistedRevision\(session, request\.baseRevision/);
  assert.match(main, /assertBaseRevision\(request, session\.currentRevision\(\)\)/);
  assert.match(main, /liveMutationQueue\.run/);
  assert.match(main, /live-command:response/);
  assert.match(main, /new LiveCommandRegistry\(\{ approve: requestLiveCommandApproval \}\)/);
});

test("external harness bridge uses a capability-gated local pipe", () => {
  assert.match(main, /new LiveCommandPipeServer/);
  assert.match(main, /source: "external-mcp"/);
  assert.match(main, /liveCommandPipe\.start\(\)/);
  assert.match(main, /liveCommandPipe\?\.stop\(\)/);
});

test("renderer cannot supply a trusted current revision to live command execution", () => {
  assert.match(main, /live-command:execute[^\n]+executeLiveCommandRequest\(request/);
  assert.doesNotMatch(main, /liveCommands\.execute\(request,\s*\{[^}]*currentRevision:\s*request/s);
});

test("preload and TypeScript surface expose bounded live command APIs", () => {
  for (const channel of ["live-command:list", "live-command:execute", "live-command:preview-get", "live-command:event", "live-project:event"]) {
    assert.match(preload, new RegExp(channel));
  }
  assert.match(desktopTypes, /commands:\s*\{/);
  assert.match(desktopTypes, /onEvent\(listener:\s*\(event:\s*LiveCommandEvent\)/);
  assert.match(desktopTypes, /onProjectEvent\(listener:\s*\(event:\s*LiveProjectEvent\)/);
});
