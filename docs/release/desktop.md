# Desktop release runbook

DesignDNA uses Electron Forge to produce these artifacts:

- Windows x64: Squirrel installer (`.exe`) and package (`.nupkg`);
- macOS: application archive (`.zip`) and disk image (`.dmg`).

Run a local unsigned build after the frontend and Repo Canvas dependencies are installed:

```bash
npm run desktop:make
```

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

## Current release boundary

The Forge layout includes the React bundle, DesignDNA Python application source, Repo Canvas runtime and internal workers. The current `0.3.x` artifact expects a compatible Python installation on the machine. Do not call it a standalone public release until the Python runtime, native dependencies and required browser assets are bundled and verified on clean Windows and macOS machines.
