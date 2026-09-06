// Local JSONL app-server fixture. It reads transported images; never invokes a provider.
import { readFileSync } from "node:fs";
import { createInterface } from "node:readline";

const mode = process.argv[2] || "success";
const send = (message) => process.stdout.write(`${JSON.stringify(message)}\n`);
const notify = (method, params) => send({ method, params });
let sequence = 0;
createInterface({ input: process.stdin }).on("line", (line) => {
  const { id, method, params } = JSON.parse(line);
  if (id == null) return;
  if (method === "initialize") {
    if (mode === "init-error") send({ id, error: { message: "fixture initialize failed" } });
    else send({ id, result: {} });
  } else if (method === "account/read") {
    notify("fixture/account", params);
    const account = mode === "logged-out" ? null
      : { type: mode === "api-key" ? "apiKey" : mode === "bedrock" ? "amazonBedrock" : "chatgpt" };
    send({ id, result: { account } });
  } else if (method === "thread/start") {
    notify("fixture/thread", params);
    if (mode === "thread-error") send({ id, error: { message: "fixture thread failed" } });
    else if (mode === "thread-hold") return;
    else send({ id, result: {
      thread: { id: mode === "missing-thread" ? "" : `thread-${++sequence}`,
        modelProvider: mode === "thread-provider-mismatch" ? "external" : "openai" },
      modelProvider: mode === "provider-mismatch" ? "external" : "openai",
      model: mode === "missing-model" ? "" : params.model || "fixture-resolved-model",
    } });
  } else if (method === "turn/start") {
    const threadId = params.threadId;
    const turnId = `turn-${threadId}`;
    const input = params.input.map((item) => item.type === "localImage"
      ? { ...item, base64: readFileSync(item.path).toString("base64") } : item);
    notify("fixture/input", { ...params, input });
    if (mode === "crash") { process.exit(2); return; }
    if (mode === "turn-error") { send({ id, error: { message: "fixture turn rejected" } }); return; }
    const acknowledge = () => send({ id, result: { turn: { id: turnId } } });
    if (mode === "late-ack") { setTimeout(acknowledge, 80); return; }
    acknowledge();
    if (mode === "hold") return;
    if (mode.startsWith("completion-")) {
      const itemId = "final-item";
      const valid = JSON.stringify({ siteBrief: { summary: "Я".repeat(3800) }, styleGuide: { tone: "precise" } });
      const text = mode === "completion-split-valid" ? valid : valid.slice(0, -1);
      const streamed = mode === "completion-disagrees" ? valid : text;
      notify("item/agentMessage/delta", { threadId, turnId, itemId, delta: streamed.slice(0, -1) });
      notify("item/agentMessage/delta", { threadId, turnId, itemId, delta: streamed.slice(-1) });
      if (mode === "completion-early-turn") {
        notify("turn/completed", { threadId, turn: { id: turnId, status: "completed" } });
        setTimeout(() => notify("item/completed", { threadId, turnId,
          item: { id: itemId, type: "agentMessage", text: valid, phase: "final_answer" } }), 20);
        return;
      }
      const bytes = Buffer.from(JSON.stringify({ method: "item/completed", params: { threadId, turnId,
        item: { id: itemId, type: "agentMessage", text, phase: "final_answer" } } }) + "\n");
      // Split a UTF-8 character and the final JSONL envelope byte across writes.
      const split = bytes.indexOf(Buffer.from("Я")) + 1;
      process.stdout.write(bytes.subarray(0, split));
      setImmediate(() => {
        process.stdout.write(bytes.subarray(split, -2));
        setImmediate(() => {
          process.stdout.write(bytes.subarray(-2));
          notify("turn/completed", { threadId, turn: { id: turnId, status: "completed" } });
        });
      });
      return;
    }
    setImmediate(() => {
      if (mode === "reroute") notify("model/rerouted", { threadId, turnId, toModel: "fixture-rerouted-model" });
      // An unscoped completion must not settle an unrelated request.
      notify("turn/completed", { turn: { status: "failed", error: { message: "unrelated" } } });
      notify("item/completed", { threadId, turnId,
        item: { type: "agentMessage", text: mode === "empty" ? "" : '{"score":92}' } });
      notify("turn/completed", { threadId, turn: { id: turnId,
        status: mode === "failed" ? "failed" : mode === "interrupted" ? "interrupted" : "completed",
        error: mode === "failed" ? { message: "fixture vision failed" } : null } });
    });
  } else if (method === "turn/interrupt") {
    notify("fixture/interrupt", params);
    send({ id, result: {} });
  }
});
