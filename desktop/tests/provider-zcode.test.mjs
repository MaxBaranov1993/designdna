import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import { mkdir, mkdtemp, readFile, writeFile, rm } from "node:fs/promises";
import { readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { chatWithZcode, zcodeCliPath, zcodeEnsureConfig } from "../services/provider-chat.mjs";

function fakeChild({ code = 0, stdout = "", stderr = "" } = {}) {
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.kill = () => {};
  process.nextTick(() => {
    child.stdout.emit("data", Buffer.from(stdout, "utf-8"));
    child.stderr.emit("data", Buffer.from(stderr, "utf-8"));
    child.emit("close", code);
  });
  return child;
}

test("chatWithZcode renders messages into TASK.md and returns CLI stdout", async () => {
  const spawned = [];
  const environment = { ZCODE_CLI: "C:/fake/zcode.cjs", ZCODE_NODE: "node" };
  const content = await chatWithZcode({
    messages: [
      { role: "system", content: "SYSTEM RULES" },
      { role: "user", content: "Сгенерируй лендинг" },
    ],
    environment,
    ensureConfig: () => "C:/fake/zcode.cjs",
    spawnImpl: (node, args, options) => {
      spawned.push({ node, args, options, task: readFileSync(path.join(options.cwd, "TASK.md"), "utf-8") });
      return fakeChild({ stdout: '{"ok":true}' });
    },
  });
  assert.equal(content, '{"ok":true}');
  assert.equal(spawned.length, 1);
  assert.equal(spawned[0].node, "node");
  assert.equal(spawned[0].args[0], "C:/fake/zcode.cjs");
  const args = spawned[0].args;
  assert.ok(args.includes("--prompt"));
  assert.ok(args.includes("--disallowed-tools"));
  const task = spawned[0].task;
  const cwd = spawned[0].options.cwd;
  assert.ok(task.includes("### SYSTEM"));
  assert.ok(task.includes("SYSTEM RULES"));
  assert.ok(task.includes("Сгенерируй лендинг"));
  // временная папка задачи удаляется после вызова
  await assert.rejects(readFile(path.join(cwd, "TASK.md"), "utf-8"));
});

test("chatWithZcode surfaces CLI failures instead of empty content", async () => {
  const environment = { ZCODE_CLI: "C:/fake/zcode.cjs" };
  await assert.rejects(
    chatWithZcode({
      messages: [{ role: "user", content: "x" }],
      environment,
      ensureConfig: () => "C:/fake/zcode.cjs",
      spawnImpl: () => fakeChild({ code: 1, stderr: "boom" }),
    }),
    /zcode: exit 1/,
  );
});

test("zcodeCliPath honours the ZCODE_CLI override and rejects missing files", () => {
  assert.equal(zcodeCliPath({ ZCODE_CLI: "C:/definitely/missing.cjs" }), null);
});

test("zcodeEnsureConfig bootstraps cli config from v2 with the coding-plan model", async () => {
  const home = await mkdtemp(path.join(os.tmpdir(), "zcode-js-test-"));
  await mkdir(path.join(home, "bin"), { recursive: true });
  const fakeCli = path.join(home, "bin", "zcode.cjs");
  await writeFile(fakeCli, "// fake cli", "utf-8");
  const environment = {
    ZCODE_CLI: fakeCli,
    LOCALAPPDATA: "",
    USERPROFILE: home,
    HOME: home,
  };
  await mkdir(path.join(home, ".zcode", "v2"), { recursive: true });
  await writeFile(path.join(home, ".zcode", "v2", "config.json"), JSON.stringify({
    provider: {
      "56ce6-plain": {
        options: { baseURL: "https://api.moonshot.cn/anthropic", apiKey: "k" },
        models: { "kimi-k3": {} },
      },
      "builtin:zai-coding-plan": {
        enabled: true,
        options: { baseURL: "https://api.z.ai/api/anthropic", apiKey: "k" },
        models: { "GLM-5.2": {}, "GLM-5.3": {} },
      },
    },
  }), "utf-8");
  await writeFile(path.join(home, ".zcode", "v2", "credentials.json"), "{}", "utf-8");
  try {
    const cli = zcodeEnsureConfig(environment);
    assert.equal(cli, fakeCli);
    const config = JSON.parse(await readFile(path.join(home, ".zcode", "cli", "config.json"), "utf-8"));
    assert.equal(config.model.main, "builtin:zai-coding-plan/GLM-5.3");
    assert.ok(config.provider["builtin:zai-coding-plan"]);

    // без login Z.AI CLI считается недоступным, конфиг не создаётся
    await rm(path.join(home, ".zcode", "v2", "credentials.json"));
    await rm(path.join(home, ".zcode", "cli"), { recursive: true, force: true });
    assert.equal(zcodeEnsureConfig(environment), null);
  } finally {
    await rm(home, { recursive: true, force: true }).catch(() => {});
  }
});
