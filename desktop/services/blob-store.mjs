import { createHash, randomUUID } from "node:crypto";
import path from "node:path";
import { link, lstat, mkdir, open, readFile, unlink } from "node:fs/promises";

export const BLOB_MIME = Object.freeze({
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".svg": "image/svg+xml",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
});

const EXTENSION = Object.freeze({
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/gif": "gif",
  "image/webp": "webp",
  "image/svg+xml": "svg",
  "video/mp4": "mp4",
  "video/webm": "webm",
});

export const DEFAULT_MAX_BYTES = 256 * 1024 * 1024;
const HASHED_NAME = /^([a-f0-9]{64})\.(png|jpg|gif|webp|svg|mp4|webm)$/;

export function safeBlobName(raw) {
  if (typeof raw !== "string") return null;
  const value = raw;
  const name = path.basename(value);
  return value === name && /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(name) ? name : null;
}

export function sha256Bytes(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function normalizedMime(value) {
  const mime = String(value || "").split(";", 1)[0].trim().toLowerCase();
  return mime === "image/jpg" ? "image/jpeg" : mime;
}

export function sniffBlobMime(bytes) {
  const data = Buffer.from(bytes);
  if (data.length >= 8 && data.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return "image/png";
  if (data.length >= 3 && data[0] === 0xff && data[1] === 0xd8 && data[2] === 0xff) return "image/jpeg";
  if (data.length >= 6 && ["GIF87a", "GIF89a"].includes(data.subarray(0, 6).toString("ascii"))) return "image/gif";
  if (data.length >= 12 && data.subarray(0, 4).toString("ascii") === "RIFF" && data.subarray(8, 12).toString("ascii") === "WEBP") return "image/webp";
  if (data.length >= 12 && data.subarray(4, 8).toString("ascii") === "ftyp") return "video/mp4";
  if (data.length >= 4 && data.subarray(0, 4).equals(Buffer.from([0x1a, 0x45, 0xdf, 0xa3]))) return "video/webm";
  const prefix = data.subarray(0, Math.min(data.length, 4096)).toString("utf8").replace(/^\uFEFF?\s*/, "");
  if (/^(?:<\?xml[^>]*>\s*)?<svg(?:\s|>)/i.test(prefix)) return "image/svg+xml";
  return null;
}

function decodeBase64(value, maxBytes) {
  const source = String(value || "").replace(/\s+/g, "");
  if (!source || !/^[A-Za-z0-9+/]*={0,2}$/.test(source) || source.length % 4 === 1) {
    throw new Error("Invalid blob base64");
  }
  const data = Buffer.from(source, "base64");
  if (data.toString("base64").replace(/=+$/, "") !== source.replace(/=+$/, "")) throw new Error("Invalid blob base64");
  if (!data.length) throw new Error("Blob is empty");
  if (data.length > maxBytes) throw new Error(`Blob exceeds ${maxBytes} bytes`);
  return data;
}

async function verifyExisting(filename, expectedHash) {
  const existing = await readFile(filename);
  const actualHash = sha256Bytes(existing);
  if (actualHash !== expectedHash) {
    const error = new Error(`Blob integrity mismatch for ${path.basename(filename)}`);
    error.code = "BLOB_INTEGRITY";
    throw error;
  }
}

export async function putContentAddressedBlob(root, { base64, mime, maxBytes = DEFAULT_MAX_BYTES }) {
  const data = decodeBase64(base64, maxBytes);
  const detectedMime = sniffBlobMime(data);
  const requestedMime = normalizedMime(mime);
  if (!detectedMime || !EXTENSION[detectedMime]) throw new Error("Unsupported or unrecognised blob content");
  if (requestedMime && requestedMime !== detectedMime) {
    throw new Error(`Blob MIME mismatch: declared ${requestedMime}, detected ${detectedMime}`);
  }

  const sha256 = sha256Bytes(data);
  const name = `${sha256}.${EXTENSION[detectedMime]}`;
  const directory = path.resolve(root);
  const target = path.join(directory, name);
  await mkdir(directory, { recursive: true });

  // Publish a fully written immutable object. link() is create-if-absent and
  // does not replace an existing path; a crash cannot expose a partial target.
  const temporary = path.join(directory, `${name}.${process.pid}.${randomUUID()}.tmp`);
  let stored = false;
  try {
    const handle = await open(temporary, "wx", 0o600);
    try {
      await handle.writeFile(data);
      await handle.sync();
    } finally {
      await handle.close();
    }
    try {
      await link(temporary, target);
      stored = true;
    } catch (error) {
      if (error.code !== "EEXIST") throw error;
      await verifyExisting(target, sha256);
    }
  } finally {
    await unlink(temporary).catch((error) => {
      if (error.code !== "ENOENT") throw error;
    });
  }
  return { stored, name, sha256, mime: detectedMime, bytes: data.length };
}

export async function readBlobObject(root, rawName, {
  verify = true,
  requireContentAddressed = false,
  maxBytes = DEFAULT_MAX_BYTES,
} = {}) {
  const name = safeBlobName(rawName);
  if (!name) throw new Error("Invalid blob name");
  const filename = path.join(path.resolve(root), name);
  const metadata = await lstat(filename);
  if (!metadata.isFile() || metadata.isSymbolicLink()) {
    const error = new Error(`Blob is not a regular file: ${name}`);
    error.code = "BLOB_TYPE";
    throw error;
  }
  if (metadata.size <= 0 || metadata.size > maxBytes) {
    const error = new Error(`Blob size is outside the allowed range: ${name}`);
    error.code = "BLOB_SIZE";
    throw error;
  }
  const data = await readFile(filename);
  const match = HASHED_NAME.exec(name);
  if (requireContentAddressed && !match) {
    const error = new Error(`Blob is not content addressed: ${name}`);
    error.code = "BLOB_NAME";
    throw error;
  }
  if (verify && match && sha256Bytes(data) !== match[1]) {
    const error = new Error(`Blob integrity mismatch for ${name}`);
    error.code = "BLOB_INTEGRITY";
    throw error;
  }
  const mime = BLOB_MIME[path.extname(name).toLowerCase()] || "application/octet-stream";
  if (match && sniffBlobMime(data) !== mime) {
    const error = new Error(`Blob MIME does not match its extension: ${name}`);
    error.code = "BLOB_MIME";
    throw error;
  }
  return { name, data, mime, contentAddressed: Boolean(match) };
}

export async function readBlobBatch(root, names, {
  maxItems = 500,
  maxTotalBytes = DEFAULT_MAX_BYTES,
} = {}) {
  if (!Array.isArray(names)) throw new Error("Blob names must be an array");
  if (names.length > maxItems) throw new Error("Too many blob names");
  const objects = {};
  let totalBytes = 0;
  for (const raw of new Set(names)) {
    const name = safeBlobName(raw);
    if (!name) throw new Error("Invalid blob name");
    const object = await readBlobObject(root, name);
    totalBytes += object.data.length;
    if (totalBytes > maxTotalBytes) throw new Error("Blob batch exceeds the allowed byte limit");
    objects[name] = object;
  }
  return { objects, totalBytes };
}
