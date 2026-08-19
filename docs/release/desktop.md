# Desktop release runbook

DesignDNA uses Electron Forge to produce these artifacts:

- Windows x64: Squirrel installer (`.exe`) and package (`.nupkg`);
- macOS: application archive (`.zip`) and disk image (`.dmg`).

Run a local unsigned build after installing the frontend, Repo Canvas and desktop dependencies plus the Python build requirements:

```bash
npm --prefix frontend ci
npm --prefix tools/repo-canvas ci
npm --prefix desktop ci
python -m pip install -r requirements.txt -r requirements-desktop-build.txt
npm --prefix frontend run build:desktop
npm --prefix desktop test
python -m pytest -q app
python app/ui_smoke.py
npm --prefix desktop run runtime:build
npm --prefix desktop run runtime:smoke
npm run desktop:make
```

`runtime:build` automatically prefers the repository `.venv` when it exists.
Set `DESIGNDNA_BUILD_PYTHON` only when a different build interpreter is required.

Artifacts are written to `desktop/out/make/`. GitHub Actions can run the same pipeline from **Desktop release artifacts** or automatically for tags matching `desktop-v*`.

## Signing secrets

macOS signing/notarization is enabled when all three secrets exist:

- `APPLE_ID`
- `APPLE_APP_PASSWORD`
- `APPLE_TEAM_ID`

Windows installer signing is enabled when both secrets exist:

- `WINDOWS_CERTIFICATE_FILE`
- `WINDOWS_CERTIFICATE_PASSWORD`

Unsigned artifacts are suitable only for internal testing: Windows SmartScreen and macOS Gatekeeper will warn users. Never commit certificates or passwords.

## Standalone runtime

The `0.4.x` Forge layout includes the React bundle, Repo Canvas worker, a platform-native PyInstaller `onedir` Python sidecar and the matching Playwright Chromium headless shell as a sibling resource. Every browser call in DesignDNA is headless, so the full browser is intentionally omitted. Keeping Chromium outside PyInstaller preserves its native macOS bundle structure for Electron signing. Installed applications do not use a system Python. The release workflow starts the bundled sidecar and verifies its JSONL health response before creating an installer.

Application code and schema assets are read from the signed resource bundle. Projects remain user-selected workspaces; databases, captured fonts and rendered media are written below Electron's per-user `userData/data` directory.
