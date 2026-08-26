import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const CHECKSUM_FILENAME = "SHA256SUMS.txt";

async function artifactFiles(root, directory = root) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await artifactFiles(root, absolute));
    else if (entry.isFile() && entry.name !== CHECKSUM_FILENAME) files.push(absolute);
  }
  return files.sort((left, right) => left.localeCompare(right, "en"));
}

export async function sha256File(filename) {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(filename)) hash.update(chunk);
  return hash.digest("hex");
}

export async function writeArtifactChecksums(root) {
  const absoluteRoot = path.resolve(root);
  const files = await artifactFiles(absoluteRoot);
  if (!files.length) throw new Error(`No release artifacts found under ${absoluteRoot}`);
  const lines = [];
  for (const filename of files) {
    const relative = path.relative(absoluteRoot, filename).split(path.sep).join("/");
    lines.push(`${await sha256File(filename)}  ${relative}`);
  }
  const output = path.join(absoluteRoot, CHECKSUM_FILENAME);
  await writeFile(output, `${lines.join("\n")}\n`, { encoding: "utf8", flag: "w" });
  return { output, files: files.length, lines };
}

const invoked = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invoked) {
  const root = process.argv[2] || path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "out", "make");
  const result = await writeArtifactChecksums(root);
  console.log(`Wrote ${result.files} SHA-256 checksums to ${result.output}`);
}
