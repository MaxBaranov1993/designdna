// Воркер-фикстура: на любой запрос отвечает cancelled в формате cancel_token
// desktop_worker.py ({cancelled:true, error:{code:"cancelled",...}}).
process.stdin.on("data", (chunk) => {
  for (const line of String(chunk).split("\n")) {
    if (!line.trim()) continue;
    const message = JSON.parse(line);
    if (message.method === "shutdown") {
      process.stdout.write(`${JSON.stringify({ id: message.id, result: { shutdown: true } })}\n`);
      process.exit(0);
    }
    process.stdout.write(`${JSON.stringify({
      id: message.id,
      cancelled: true,
      error: { code: "cancelled", message: "cancelled", cancelled: true, data: { cancelled: true } },
    })}\n`);
  }
});
setInterval(() => {}, 1 << 30);
