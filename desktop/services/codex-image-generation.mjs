// Native Codex imageGeneration items contain raster bytes, not assistant prose.
// This runs on the same authorized subscription as the rest of the desktop.
export async function generateCodexImage(codex, input, { signal, cwd, model = null, timeoutMs = 240_000 } = {}) {
  if (signal?.aborted) throw new Error("Image generation cancelled");
  return new Promise((resolve, reject) => {
    let threadId = "", turnId = "", settled = false, mustInterrupt = false, interrupted = false;
    let image = null, failure = null;
    const interrupt = () => {
      if (threadId && turnId && !interrupted) {
        interrupted = true;
        void codex.request("turn/interrupt", { threadId, turnId }).catch(() => {});
      }
    };
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      codex.removeListener("notification", notification);
      codex.removeListener("serverError", serverError);
      if (threadId) void codex.request("thread/unsubscribe", { threadId }).catch(() => {});
      error ? reject(error) : resolve(value);
    };
    const cancel = (message) => { mustInterrupt = true; interrupt(); finish(new Error(message)); };
    const abort = () => cancel("Image generation cancelled");
    const serverError = error => finish(error);
    const timer = setTimeout(() => cancel("GPT Image did not finish within 4 minutes"), timeoutMs);
    const notification = ({ method, params = {} }) => {
      if (String(params.threadId || "") !== threadId || !threadId) return;
      const eventTurn = String(params.turnId || params.turn?.id || "");
      if (turnId && eventTurn && eventTurn !== turnId) return;
      if (!turnId && eventTurn) turnId = eventTurn;
      if (method === "item/completed" && params.item?.type === "imageGeneration") {
        const item = params.item;
        if (item.status !== "completed" || item.failure) {
          failure = new Error(item.failure?.message || "GPT Image could not create an image");
          return;
        }
        const result = item.result;
        if (typeof result !== "string" || result.length > 28_000_000
          || !/^[A-Za-z0-9+/]+={0,2}$/.test(result)) {
          failure = new Error("GPT Image returned invalid image data");
          return;
        }
        const bytes = Buffer.from(result, "base64");
        const mime = bytes.subarray(0, 8).equals(Buffer.from("89504e470d0a1a0a", "hex")) ? "image/png"
          : bytes.subarray(0, 3).equals(Buffer.from([255, 216, 255])) ? "image/jpeg" : null;
        if (!mime || bytes.toString("base64").replace(/=+$/, "") !== result.replace(/=+$/, "")) {
          failure = new Error("GPT Image returned neither PNG nor JPEG");
          return;
        }
        image = { image: `data:${mime};base64,${result}`, transparent: item.transparentBackground === true };
      }
      if (method === "turn/completed") {
        const turn = params.turn;
        if (turn?.status !== "completed") return finish(new Error(turn?.error?.message || "Image generation interrupted"));
        finish(failure || (!image ? new Error("Codex returned no image. Check GPT Image availability in the connected account") : null), image);
      }
    };
    codex.on("notification", notification);
    codex.on("serverError", serverError);
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) { abort(); return; }
    void (async () => {
      await codex.start();
      if (settled) return;
      const account = await codex.account();
      if (settled) return;
      if (account?.account?.type !== "chatgpt") throw new Error("For GPT Image, sign in to ChatGPT through Agents → Connections → Codex");
      const thread = await codex.startThread({
        ...(model ? { model } : {}),
        modelProvider: "openai", cwd, approvalPolicy: "never", sandbox: "read-only", ephemeral: true,
        serviceName: "designdna-image",
        config: { "features.image_generation": true, "features.shell_tool": false, "features.unified_exec": false, web_search: "disabled" },
        developerInstructions: "Use only the built-in image generation tool for this request. Generate or edit exactly one raster image. Do not use SVG, code, shell commands, external tools, or inspect project files. Finish after generating the image.",
      });
      if (settled) {
        if (thread.thread?.id) void codex.request("thread/unsubscribe", { threadId: thread.thread.id }).catch(() => {});
        return;
      }
      threadId = String(thread.thread?.id || "");
      if (!threadId || thread.modelProvider !== "openai" || (thread.thread?.modelProvider && thread.thread.modelProvider !== "openai")) {
        throw new Error("Codex did not confirm the OpenAI connection for GPT Image");
      }
      const started = await codex.startTurn({ threadId, input });
      turnId = String(started?.turn?.id || turnId);
      if (mustInterrupt) interrupt();
    })().catch(error => finish(error));
  });
}
