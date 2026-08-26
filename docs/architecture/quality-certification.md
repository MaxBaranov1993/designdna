# Quality Certificate architecture

Verified implementation: 2026-08-25.

## Purpose and current integration

`POST /api/quality/certify` converts completed DesignDNA QA reports into a
deterministic certificate and an enforcement decision. The route calls
`certify_from_reports` in `app/quality_certification_adapter.py`, which maps
named evidence into the canonical `certify_quality` contract in
`app/quality_certificate.py`.

This API is implemented and tested. The live command Apply path, code export
and motion export do not yet call it as a mandatory gate. Until those call sites
are wired, describe it as the Quality Certificate foundation, not universal
Quality Certified enforcement.

## Required request evidence

The adapter accepts only these top-level fields:

- `designIrHash`: lowercase `sha256:` digest;
- `designSystem`: exact id, revision and lowercase content hash;
- `assetHashes`: bounded lowercase SHA-256 references;
- `qualityGate`: deterministic `passed` plus `violations`;
- `visualJudge`: score, critical subscores, verdict and issues;
- `lockReport`: checked state, violations and preserved locks;
- `scopeReport`: checked state, violations, structural mutations, changed
  facets and `styleOnly`;
- `viewportReport`: required viewports and per-viewport score,
  violations/warnings;
- `evidence`: explicit arrays for every required evidence gate;
- optional `override`: `{ "requested": true, "reason": "..." }`.

Missing reports and missing evidence do not disappear: they create named
`evidence.missing.*` blockers. Raw Design IR, assets, prompts, credentials,
authorization/cookie fields and common credential-key aliases are rejected.
Input size, depth, node count, strings, collections, assets and viewports are
bounded.

## Blocking decision

A certificate can be `certified`, `certified_with_warnings` or `blocked`.
Certification requires:

- overall score `>= 85`;
- every critical subscore `>= 75`;
- every required viewport present and scored `>= 75`;
- no schema, lock, scope, source-key, component-identity, hierarchy, overflow,
  clipping, collision, asset, placeholder, forbidden-token/component/font/color,
  contrast or accessibility blocker;
- no structural mutation when `styleOnly` is true.

Warnings are explicit non-blocking records and can produce
`certified_with_warnings`; they never silently raise a score or erase a blocker.

## Integrity and privacy

The result binds its `inputHash` and `certificateHash` to normalized evidence,
Design IR hash, Design System identity/revision/content hash, asset hashes and
`quality-certificate/1.0.0`. Set-like fields and issue lists are sorted before
hashing, so equivalent evidence is deterministic.

The certificate never returns the raw report, prompt, Design IR, assets or
credentials. Malformed input produces a stable blocked certificate without
hashing or echoing sensitive values.

## Override semantics

An override reason must contain 8 to 500 non-whitespace characters. A valid
override can make `applyAllowed` and `exportAllowed` true for a well-formed but
blocked artifact, while the certificate itself remains `blocked`. The decision
records the normalized reason and its SHA-256 reason hash. Malformed input is
never overrideable.

## Remaining production work

1. Call the adapter from live Apply immediately before canonical commit.
2. Require `decision.exportAllowed` for code and motion export.
3. Persist the certificate hash and override audit beside the exported artifact.
4. Re-certify when the Design IR, Design System revision, asset set, viewport
   evidence or engine version changes.
