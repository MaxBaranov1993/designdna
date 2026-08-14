# Repo Canvas inside DesignDNA

Repo Canvas is part of this repository as a development tool. It gives DesignDNA a
local semantic project map, live Codex/Claude/Kimi work cards, and navigation back to
the corresponding agent session.

## Provenance

- Imported from: https://github.com/MaxBaranov1993/repo-canvas
- Upstream: https://github.com/m0ast-git/repo-canvas
- Imported commit: `ca1575fa7447cc556e7b2052602e3a0329d32c46`
- License: MIT; the original license and package documentation are preserved in
  `tools/repo-canvas/`.

The imported source is intentionally isolated under `tools/repo-canvas`. DesignDNA's
FastAPI backend and React/Vite application keep their existing dependency graphs,
while the repository map runs as a local Node.js development service.

## Install

Requirements: Node.js 22+, npm, Git, and a locally authenticated Codex installation.

From the DesignDNA repository root:

```bash
npm run repo-canvas:install
npm run repo-canvas:setup
npm run repo-canvas:start
```

The CLI resolves the enclosing Git root, so it maps the complete DesignDNA repository,
not only the `tools/repo-canvas` directory. Runtime state is stored in the ignored
root directory `.repo-canvas/`.

## Commands

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

Repo Canvas uses port 4173 by default. DesignDNA continues to use port 8420, so both
local services can run together without a port conflict.
