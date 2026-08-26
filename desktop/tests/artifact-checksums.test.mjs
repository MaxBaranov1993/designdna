import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { CHECKSUM_FILENAME, sha256File, writeArtifactChecksums } from "../scripts/write-artifact-checksums.mjs";

const digest = (value) => createHash("sha256").update(value).digest("hex");

test("release checksums hash complete files, use stable relative paths and exclude their own manifest", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-checksums-"));
  try {
    fs.mkdirSync(path.join(directory, "linux"), { recursive: true });
    fs.writeFileSync(path.join(directory, "z.zip"), "zip-bytes");
    fs.writeFileSync(path.join(directory, "linux", "a.deb"), "deb-bytes");
    fs.writeFileSync(path.join(directory, CHECKSUM_FILENAME), "stale\n");

    const result = await writeArtifactChecksums(directory);
    assert.equal(result.files, 2);
    assert.deepEqual(result.lines, [
      `${digest("deb-bytes")}  linux/a.deb`,
      `${digest("zip-bytes")}  z.zip`,
    ]);
    assert.equal(fs.readFileSync(result.output, "utf8"), `${result.lines.join("\n")}\n`);
    assert.equal(await sha256File(path.join(directory, "z.zip")), digest("zip-bytes"));
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("release checksum generation fails closed when the make directory is empty", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-checksums-empty-"));
  try {
    await assert.rejects(writeArtifactChecksums(directory), /No release artifacts found/);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
