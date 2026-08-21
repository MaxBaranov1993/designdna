# Repo Canvas inside DesignDNA

Repo Canvas is the semantic **Project Map** surface of DesignDNA. It is no longer a
separate product runtime: Electron starts it as an internal JSONL/stdio worker and
renders its data in the same SvelteKit application as the Design IR editor.

## Provenance

- Imported from: https://github.com/MaxBaranov1993/repo-canvas
- Upstream: https://github.com/m0ast-git/repo-canvas
- Imported commit: `ca1575fa7447cc556e7b2052602e3a0329d32c46`
- License: MIT; the original license and package documentation remain in
  `tools/repo-canvas/`.

The imported directory is an implementation boundary, not a user-facing application
boundary. The desktop host imports its event store and architect directly; it never
starts Repo Canvas's standalone HTTP server in production.

## Install and start

Requirements: Node.js 22+, npm, Git, Python, and a locally authenticated Codex
installation for architecture refreshes.

```bash
npm run frontend:install
npm run repo-canvas:install
npm run desktop:install
npm run repo-canvas:setup
npm run desktop:start
```

Runtime state stays in the ignored root directory `.repo-canvas/`. The Project Map
button in the DesignDNA window reads the same store.

## Maintenance commands

```bash
npm run repo-canvas -- doctor
npm run repo-canvas -- architect --refresh
npm run repo-canvas -- observer status
npm run repo-canvas -- observer disable
npm run repo-canvas -- observer enable
npm run repo-canvas -- snapshot
npm run repo-canvas:check
npm run repo-canvas:test
```

The legacy standalone server remains in the imported upstream source only for
compatibility and upstream maintenance. The supported desktop topology uses no
loopback HTTP ports; see [desktop-runtime.md](architecture/desktop-runtime.md).
