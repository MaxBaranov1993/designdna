/** Compact deterministic change marker; not a security/content-authentication hash. */
export function inputFingerprint(value: unknown): string {
  const text = JSON.stringify(value);
  let first = 0x811c9dc5, second = 0x9e3779b9;
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    first = Math.imul(first ^ code, 0x01000193);
    second = Math.imul(second ^ code, 0x5bd1e995);
    second ^= second >>> 13;
  }
  return `${text.length}:${first >>> 0}:${second >>> 0}`;
}
