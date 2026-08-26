import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { putContentAddressedBlob, readBlobBatch, readBlobObject, safeBlobName, sha256Bytes, sniffBlobMime } from "../services/blob-store.mjs";

const png = (middle) => Buffer.concat([
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  Buffer.alloc(4096, 0x31),
  Buffer.from(middle),
  Buffer.alloc(4096, 0x32),
]);

test("blob objects use the full byte SHA-256 and atomically reuse identical content", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-blobs-"));
  try {
    const firstBytes = png("middle-a");
    const secondBytes = png("middle-b");
    const first = await putContentAddressedBlob(directory, { base64: firstBytes.toString("base64"), mime: "image/png" });
    const repeated = await putContentAddressedBlob(directory, { base64: firstBytes.toString("base64"), mime: "image/png" });
    const second = await putContentAddressedBlob(directory, { base64: secondBytes.toString("base64"), mime: "image/png" });

    assert.equal(first.name, `${sha256Bytes(firstBytes)}.png`);
    assert.equal(first.stored, true);
    assert.equal(repeated.stored, false);
    assert.equal(repeated.name, first.name);
    assert.notEqual(second.name, first.name, "same head, tail and length with different middle bytes must not collide");
    assert.deepEqual((await readBlobObject(directory, first.name)).data, firstBytes);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("existing corrupt content-addressed objects fail closed instead of being overwritten", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-blobs-corrupt-"));
  try {
    const bytes = png("original");
    const stored = await putContentAddressedBlob(directory, { base64: bytes.toString("base64"), mime: "image/png" });
    fs.writeFileSync(path.join(directory, stored.name), png("corrupt!"));
    await assert.rejects(
      putContentAddressedBlob(directory, { base64: bytes.toString("base64"), mime: "image/png" }),
      (error) => error.code === "BLOB_INTEGRITY",
    );
    await assert.rejects(readBlobObject(directory, stored.name), (error) => error.code === "BLOB_INTEGRITY");
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("concurrent writers publish one immutable object without temporary-file collisions", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-blobs-race-"));
  try {
    const bytes = png("concurrent");
    const writes = await Promise.all(Array.from({ length: 24 }, () =>
      putContentAddressedBlob(directory, { base64: bytes.toString("base64"), mime: "image/png" })));
    assert.equal(writes.filter(({ stored }) => stored).length, 1);
    assert.equal(new Set(writes.map(({ name }) => name)).size, 1);
    assert.deepEqual(fs.readdirSync(directory), [writes[0].name]);
    assert.deepEqual((await readBlobObject(directory, writes[0].name)).data, bytes);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("blob objects validate base64 and sniffed MIME before persistence", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-blobs-mime-"));
  try {
    const bytes = png("payload");
    assert.equal(sniffBlobMime(bytes), "image/png");
    await assert.rejects(putContentAddressedBlob(directory, { base64: "%%%", mime: "image/png" }), /Invalid blob base64/);
    await assert.rejects(
      putContentAddressedBlob(directory, { base64: bytes.toString("base64"), mime: "image/jpeg" }),
      /MIME mismatch/,
    );
    assert.deepEqual(fs.readdirSync(directory), []);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("blob names reject path components instead of silently normalising them", () => {
  assert.equal(safeBlobName("asset.png"), "asset.png");
  assert.equal(safeBlobName("../asset.png"), null);
  assert.equal(safeBlobName("folder/asset.png"), null);
  assert.equal(safeBlobName("folder\\asset.png"), null);
  assert.equal(safeBlobName(123), null);
});

test("content-addressed reads reject MIME spoofing and legacy names when required", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-blobs-read-"));
  try {
    const bytes = png("mime-check");
    const wrongName = `${sha256Bytes(bytes)}.jpg`;
    fs.writeFileSync(path.join(directory, wrongName), bytes);
    await assert.rejects(readBlobObject(directory, wrongName), (error) => error.code === "BLOB_MIME");

    fs.writeFileSync(path.join(directory, "legacy.png"), bytes);
    await assert.rejects(
      readBlobObject(directory, "legacy.png", { requireContentAddressed: true }),
      (error) => error.code === "BLOB_NAME",
    );
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("blob reads enforce the configured byte limit", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-blobs-size-"));
  try {
    const bytes = png("too-large-for-read-limit");
    const stored = await putContentAddressedBlob(directory, { base64: bytes.toString("base64"), mime: "image/png" });
    await assert.rejects(
      readBlobObject(directory, stored.name, { maxBytes: bytes.length - 1 }),
      (error) => error.code === "BLOB_SIZE",
    );
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("blob batches fail closed on missing objects and aggregate limits", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-blobs-batch-"));
  try {
    const firstBytes = png("batch-a");
    const secondBytes = png("batch-b");
    const first = await putContentAddressedBlob(directory, { base64: firstBytes.toString("base64"), mime: "image/png" });
    const second = await putContentAddressedBlob(directory, { base64: secondBytes.toString("base64"), mime: "image/png" });
    await assert.rejects(readBlobBatch(directory, [first.name, "missing.png"]), /ENOENT/);
    await assert.rejects(
      readBlobBatch(directory, [first.name, second.name], { maxTotalBytes: firstBytes.length }),
      /batch exceeds/,
    );
    const batch = await readBlobBatch(directory, [first.name, first.name]);
    assert.equal(Object.keys(batch.objects).length, 1);
    assert.equal(batch.totalBytes, firstBytes.length);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
