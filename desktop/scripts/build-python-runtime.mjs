import { rmSync, mkdirSync, existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const desktopDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const projectRoot = path.resolve(desktopDirectory, "..");
const runtimeRoot = path.join(desktopDirectory, "runtime");
const outputRoot = path.join(runtimeRoot, "python");
const browserRoot = path.join(runtimeRoot, "playwright");
const workRoot = path.join(desktopDirectory, ".runtime-build");
const workerEntry = path.join(projectRoot, "app", "desktop_worker.py");
const python = process.env.DESIGNDNA_BUILD_PYTHON || (process.platform === "win32" ? "python" : "python3");
const buildEnvironment = {
  ...process.env,
  PLAYWRIGHT_BROWSERS_PATH: browserRoot,
  PLAYWRIGHT_SKIP_BROWSER_GC: "1",
};

function run(args) {
  const result = spawnSync(python, args, {
    cwd: projectRoot,
    env: buildEnvironment,
    stdio: "inherit",
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${python} ${args.join(" ")} exited with ${result.status}`);
}

rmSync(outputRoot, { recursive: true, force: true });
rmSync(browserRoot, { recursive: true, force: true });
rmSync(workRoot, { recursive: true, force: true });
mkdirSync(outputRoot, { recursive: true });
mkdirSync(browserRoot, { recursive: true });
mkdirSync(workRoot, { recursive: true });

run(["-m", "playwright", "install", "--only-shell", "chromium"]);
run([
  "-m", "PyInstaller",
  "--name", "designdna-python",
  "--onedir",
  "--clean",
  "--noconfirm",
  "--specpath", workRoot,
  "--distpath", outputRoot,
  "--workpath", workRoot,
  "--paths", path.join(projectRoot, "app"),
  "--hidden-import", "server",
  "--collect-submodules", "ir",
  "--collect-submodules", "config",
  "--collect-all", "playwright",
  "--collect-all", "imageio_ffmpeg",
  "--exclude-module", "pytest",
  workerEntry,
]);

const executable = path.join(
  outputRoot,
  "designdna-python",
  process.platform === "win32" ? "designdna-python.exe" : "designdna-python",
);
if (!existsSync(executable)) throw new Error(`Python runtime executable was not created: ${executable}`);
console.log(`DesignDNA Python runtime: ${executable}`);
