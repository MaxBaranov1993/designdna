import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

/* Пакет инструкций агентов (app/prompts/agent-contract): единый источник
 * текстов ролей для Claude Code, Codex и Python-пути. Адаптеры не хранят
 * собственных копий профилей — они собирают «роль + правило инструментов +
 * правило вывода» из пакета одинаково, а различается только транспорт.
 * Версия пакета уходит в transport-метаданные ответа, чтобы результат ноды
 * можно было сопоставить с версией инструкций. */

const moduleDirectory = path.dirname(fileURLToPath(import.meta.url));
/* В dev — <repo>/app/prompts/agent-contract; в упакованном приложении app/
 * лежит рядом с desktop-пакетом в resources (см. forge extraResource), и
 * main.mjs передаёт каталог явно через runtimeRoot. */
export const DEFAULT_AGENT_CONTRACT_DIR = path.resolve(moduleDirectory, "..", "..", "app", "prompts", "agent-contract");

const cache = new Map();

function requireObject(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`agent-contract: ${field} must be an object`);
  return value;
}

function buildContract(dir, raw, readFile) {
  const version = String(raw.version || "").trim();
  if (!/^agent-contract\/\d+\.\d+$/.test(version)) throw new Error(`agent-contract: unsupported version "${version}"`);
  const toolRules = Object.freeze({ ...requireObject(raw.toolRules, "toolRules") });
  const outputRules = Object.freeze({ ...requireObject(raw.outputRules, "outputRules") });
  const reminders = Object.freeze({ ...requireObject(raw.reminders, "reminders") });
  const roles = {};
  for (const [name, spec] of Object.entries(requireObject(raw.roles, "roles"))) {
    if (!/^[a-z_]{1,32}$/.test(name)) throw new Error(`agent-contract: invalid role name "${name}"`);
    const output = String(spec?.output || "");
    if (!Object.hasOwn(outputRules, output)) throw new Error(`agent-contract: role ${name} has unknown output "${output}"`);
    const file = String(spec?.file || "");
    if (!file || file.includes("..") || path.isAbsolute(file)) throw new Error(`agent-contract: role ${name} has an invalid file path`);
    const instructions = String(readFile(path.join(dir, file), "utf8")).replace(/\r\n/g, "\n").trim();
    if (!instructions) throw new Error(`agent-contract: role ${name} has empty instructions`);
    roles[name] = Object.freeze({ name, output, instructions });
  }
  const effort = Object.freeze({
    levels: Object.freeze([...(raw.effort?.levels || ["medium", "high", "max"])]),
    default: String(raw.effort?.default || "medium"),
  });
  return Object.freeze({
    version,
    dir,
    roles: Object.freeze(roles),
    toolRules,
    outputRules,
    reminders,
    effort,
    hasRole(name) { return Object.hasOwn(roles, String(name)); },
    role(name) {
      const role = roles[String(name)];
      if (!role) throw new Error(`Unsupported agent role: ${name}`);
      return role;
    },
    /** «Роль + правило инструментов + правило вывода» — одинаково для всех провайдеров. */
    composeInstructions(name, toolRule) {
      const role = this.role(name);
      if (!Object.hasOwn(toolRules, String(toolRule))) throw new Error(`Unsupported tool rule: ${toolRule}`);
      return [role.instructions, toolRules[toolRule], outputRules[role.output]].filter(Boolean).join(" ");
    },
    /** Напоминание в конце пользовательского ввода (пусто для текстовых ролей). */
    reminder(name) {
      return reminders[this.role(name).output] || "";
    },
  });
}

export function loadAgentContract(dir = DEFAULT_AGENT_CONTRACT_DIR, { readFile = readFileSync, reload = false } = {}) {
  const key = path.resolve(dir);
  if (!reload && cache.has(key)) return cache.get(key);
  const raw = JSON.parse(String(readFile(path.join(key, "contract.json"), "utf8")));
  const contract = buildContract(key, raw, readFile);
  cache.set(key, contract);
  return contract;
}
