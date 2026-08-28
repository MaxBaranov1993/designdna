import fs from "node:fs";
import path from "node:path";

const PROVIDERS = new Set(["openai"]);

export class CredentialStore {
  /* Расшифрованные креды кэшируются в памяти main-процесса: get() вызывается
   * на каждом API-запросе (fingerprint конфигурации воркера), и readFileSync +
   * decrypt на горячем пути стоили заметной латентности. Инвалидация — любой
   * #write (set/delete/миграция). */
  #cache = null;

  constructor({ userDataPath, safeStorage }) {
    this.file = path.join(userDataPath, "credentials.bin");
    this.safeStorage = safeStorage;
  }

  available() {
    return this.safeStorage.isEncryptionAvailable();
  }

  has(provider) {
    this.#assertProvider(provider);
    return Boolean(this.#read()[provider]);
  }

  set(provider, value) {
    this.#assertProvider(provider);
    if (!this.available()) throw new Error("OS credential encryption is unavailable");
    const clean = String(value || "").trim();
    if (!clean) throw new Error("Credential cannot be empty");
    const data = this.#read();
    data[provider] = clean;
    this.#write(data);
    return { provider, configured: true };
  }

  get(provider) {
    this.#assertProvider(provider);
    return this.#read()[provider] || null;
  }

  delete(provider) {
    this.#assertProvider(provider);
    const data = this.#read();
    delete data[provider];
    this.#write(data);
    return { provider, configured: false };
  }

  status() {
    return Object.fromEntries([...PROVIDERS].map((provider) => [provider, this.has(provider)]));
  }

  #assertProvider(provider) {
    if (!PROVIDERS.has(provider)) throw new Error(`Unsupported provider: ${provider}`);
  }

  #read() {
    if (this.#cache) return this.#cache;
    if (!fs.existsSync(this.file)) return {};
    if (!this.available()) throw new Error("OS credential encryption is unavailable");
    const encrypted = fs.readFileSync(this.file);
    const data = JSON.parse(this.safeStorage.decryptString(encrypted));
    // One-way credential migration: retired provider secrets are removed from
    // encrypted storage, not merely hidden from the picker.
    const clean = Object.fromEntries(Object.entries(data).filter(([provider]) => PROVIDERS.has(provider)));
    if (Object.keys(clean).length !== Object.keys(data).length) this.#write(clean);
    this.#cache = clean;
    return clean;
  }

  #write(value) {
    if (!this.available()) throw new Error("OS credential encryption is unavailable");
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    fs.writeFileSync(this.file, this.safeStorage.encryptString(JSON.stringify(value)), { mode: 0o600 });
    this.#cache = value;
  }
}
