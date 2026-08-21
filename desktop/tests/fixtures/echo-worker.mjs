// echo-воркер протокола v2: header-строка JSON + опциональные bodyLen сырые
// байты. Бинарные тела эхом возвращаются сырым куском фрейма, строковые —
// как есть. Чистый JSONL (v1) тоже работает.
let chunks = [];
let waiter = null;

const buffer = () => Buffer.concat(chunks);
const waitData = () => new Promise((resolve) => { waiter = resolve; });

process.stdin.on("data", (chunk) => {
  chunks.push(chunk);
  if (waiter) { waiter(); waiter = null; }
});
process.stdin.on("end", () => process.exit(0));
setInterval(() => {}, 1 << 30); // держим event loop живым

(async () => {
  let offset = 0;
  while (true) {
    let newline = -1;
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const buf = buffer();
      newline = buf.indexOf(0x0a, offset);
      if (newline >= 0) break;
      offset = buf.length;
      await waitData();
    }
    const buf = buffer();
    const line = buf.subarray(offset, newline).toString("utf-8");
    offset = newline + 1;
    if (!line.trim()) continue;
    const message = JSON.parse(line);
    const params = { ...(message.params || {}) };
    const bodyLen = Number(params.bodyLen || 0);
    if (bodyLen > 0) {
      while (buffer().length < offset + bodyLen) await waitData();
      params.bodyBytes = new Uint8Array(buffer().subarray(offset, offset + bodyLen));
      delete params.bodyLen;
      offset += bodyLen;
    }
    if (message.method === "shutdown") {
      process.stdout.write(`${JSON.stringify({ id: message.id, result: { shutdown: true } })}\n`);
      process.exit(0);
    }
    const result = { method: message.method, params };
    if (params.bodyBytes instanceof Uint8Array) {
      const bytes = Buffer.from(params.bodyBytes);
      delete result.params.bodyBytes;
      result.bodyLen = bytes.length;
      process.stdout.write(`${JSON.stringify({ id: message.id, result })}\n`);
      process.stdout.write(bytes);
    } else {
      process.stdout.write(`${JSON.stringify({ id: message.id, result })}\n`);
    }
  }
})();
