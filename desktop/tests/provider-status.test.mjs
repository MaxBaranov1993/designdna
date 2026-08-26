import assert from "node:assert/strict";
import test from "node:test";

import { providerCommand } from "../services/provider-status.mjs";

test("provider status resolves Windows CLI shims through cmd.exe", () => {
  const spec = providerCommand(
    { command: "codex", args: ["--version"] },
    { platform: "win32", environment: { ComSpec: "C:\\Windows\\System32\\cmd.exe" } },
  );
  assert.equal(spec.command, "C:\\Windows\\System32\\cmd.exe");
  assert.deepEqual(spec.args.slice(0, 3), ["/d", "/s", "/c"]);
  assert.match(spec.args[3], /codex --version$/);
});

test("provider status keeps direct execution on non-Windows", () => {
  assert.deepEqual(
    providerCommand({ command: "codex", args: ["--version"] }, { platform: "linux", environment: {} }),
    { command: "codex", args: ["--version"] },
  );
});
