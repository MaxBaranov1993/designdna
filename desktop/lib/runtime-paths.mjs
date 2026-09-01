import path from "node:path";

export function pythonWorkerSpec({
  isPackaged,
  platform = process.platform,
  resourcesPath,
  sourceRoot,
  pythonOverride,
}) {
  const targetPath = platform === "win32" ? path.win32 : path.posix;
  if (isPackaged) {
    const executable = platform === "win32" ? "designdna-python.exe" : "designdna-python";
    return {
      command: targetPath.join(resourcesPath, "runtime", "python", "designdna-python", executable),
      args: [],
    };
  }
  const projectPython = platform === "win32"
    ? targetPath.join(sourceRoot, ".venv", "Scripts", "python.exe")
    : targetPath.join(sourceRoot, ".venv", "bin", "python");
  return {
    command: pythonOverride || projectPython,
    args: [targetPath.join(sourceRoot, "app", "desktop_worker.py")],
  };
}

export function pythonWorkerEnvironment({ isPackaged, runtimeRoot, userDataPath }) {
  return {
    PYTHONUNBUFFERED: "1",
    PYTHONUTF8: "1",
    DESIGNDNA_RUNTIME_ROOT: runtimeRoot,
    DESIGNDNA_APP_DIR: path.join(runtimeRoot, "app"),
    DESIGNDNA_DATA_DIR: path.join(userDataPath, "data"),
    // pid Electron для вотчдога: воркеры обязаны умирать вместе с хостом.
    // Прямой родитель воркера — venv-шим python.exe, он переживает жёсткое
    // убийство Electron и держит унаследованный write-конец stdin-пайпа,
    // поэтому EOF не приходит и пары «шим+воркер» оставались зомби.
    DESIGNDNA_HOST_PID: String(process.pid),
    ...(isPackaged ? {
      PLAYWRIGHT_BROWSERS_PATH: path.join(runtimeRoot, "runtime", "playwright"),
      PLAYWRIGHT_SKIP_BROWSER_GC: "1",
    } : {}),
  };
}
