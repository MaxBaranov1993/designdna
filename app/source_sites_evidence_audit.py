"""Read-only QA evidence audit; run only after the fresh DS rebuild is confirmed.

Example (pass the exact freshly captured/refined snapshot files):
  python app/source_sites_evidence_audit.py --source slsbmb=results/source-sites-qa/slsbmb-capture.json \
      --source rsale=results/source-sites-qa/rsale-capture.json

Only the output JSON is written. SQLite is opened mode=ro + query_only; no DS
store/migration/canonicalization functions, browser, network or provider calls.
Exit 0 means evidence integrity passed, not that visual fidelity was reviewed.
Exit 1 means failed checks; exit 2 means invalid invocation. Duplicate assets
are read once. Node performs one actual JSON.parse/stringify round trip.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
import re
import shutil
import sqlite3
import subprocess
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote_to_bytes

from PIL import Image

from design_system.document import content_hash

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "tmp/sites-source-qa-profile/data"
DEFAULT_OUTPUT = ROOT / "results/source-sites-qa/evidence-audit.json"
SYSTEMS = {"slsbmb": "ds-f41b4f58294b", "rsale": "ds-c8da7439eb41"}
VIEWPORTS = ("desktop", "tablet", "mobile")
BLOB = re.compile(r"ddna://blobs/([a-f0-9]{64})\.(png|jpe?g|webp|gif|avif|bmp)", re.I)
MIMES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
         "gif": "image/gif", "avif": "image/avif", "bmp": "image/bmp"}
FONT_MAGIC = {b"wOF2": "woff2", b"wOFF": "woff", b"OTTO": "otf", b"\x00\x01\x00\x00": "ttf"}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def walk(value, path="$", in_ir=False):
    """Visit canonical slots without changing any values or expanding assets."""
    yield path, value, in_ir
    if isinstance(value, dict):
        for key, child in value.items():
            child_ir = in_ir or (key in ("ir", "masterIr", "templateIr", "before")
                                 and isinstance(child, dict) and "tree" in child)
            yield from walk(child, f"{path}[{json.dumps(str(key), ensure_ascii=False)}]", child_ir)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]", in_ir)


def size_valid(value):
    return isinstance(value, dict) and all(type(value.get(k)) in (int, float)
        and math.isfinite(value[k]) and value[k] > 0 for k in ("width", "height"))


class Audit:
    def __init__(self, data_root: Path):
        self.data_root = data_root
        self.assets = {}
        self.fonts = {}
        self.vectors = {}
        self.errors = []
        self.warnings = []

    def error(self, code, path, message):
        self.errors.append({"code": code, "path": path, "message": str(message)[:500]})

    def vector(self, node, path):
        reference = node['src']
        key = sha(reference.encode('utf-8'))
        if key not in self.vectors:
            record = self.vectors[key] = {'reference':'inline:'+key, 'ok':False, 'usages':0}
            try:
                header, payload = reference.split(',', 1)
                raw = base64.b64decode(payload, validate=True) if ';base64' in header else unquote_to_bytes(payload)
                text = raw.decode('utf-8-sig')
                if len(raw) > 8_000_000 or re.search(r'<!\s*(?:DOCTYPE|ENTITY)', text, re.I):
                    raise ValueError('SVG is oversized or contains entity declarations')
                root = ET.fromstring(text)
                if root.tag not in {'svg', '{http://www.w3.org/2000/svg}svg'}:
                    raise ValueError('Vector does not have an SVG root')
                record.update(ok=True, bytes=len(raw), sha256=sha(raw))
            except Exception as exc:
                record['error'] = str(exc)
        record = self.vectors[key]
        record['usages'] += 1
        if not record['ok']:
            self.error('invalid-vector', path, record['error'])
        expected = (node.get('sourceMeta') or {}).get('objectSha256')
        if expected and expected != record.get('sha256'):
            self.error('vector-hash-mismatch', path, 'SVG bytes differ from captured original hash')

    def raster(self, reference, path, *, in_ir=False):
        if not isinstance(reference, str):
            self.error("missing-raster-reference", path, "Expected a raster reference")
            return None
        inline = reference.startswith("data:")
        key = "inline:" + sha(reference.encode("utf-8")) if inline else reference
        if key not in self.assets:
            record = {"reference": key, "ok": False, "usages": 0}
            self.assets[key] = record
            try:
                match = BLOB.fullmatch(reference)
                if match:
                    digest, extension = match.groups()
                    file = self.data_root / "blobs" / f"{digest}.{extension}"
                    raw = file.read_bytes()
                    record.update(file=str(file), expectedSha256=digest, expectedMime=MIMES[extension.lower()])
                    if sha(raw) != digest.lower():
                        raise ValueError("Blob bytes do not match the filename SHA256")
                elif inline:
                    header, payload = reference.split(",", 1)
                    mime = header[5:].split(";", 1)[0].lower()
                    raw = base64.b64decode(payload, validate=True) if ";base64" in header else unquote_to_bytes(payload)
                    record["expectedMime"] = "image/jpeg" if mime == "image/jpg" else mime
                else:
                    raise ValueError("Not a content-addressed local raster or an inline evidence image; no fetch attempted")
                with Image.open(io.BytesIO(raw)) as image:
                    mime = Image.MIME.get(image.format, "unknown")
                    dimensions = {"width": image.width, "height": image.height}
                    image.verify()
                record.update(bytes=len(raw), sha256=sha(raw), actualMime=mime, **dimensions)
                if record["expectedMime"] != mime:
                    raise ValueError(f"MIME mismatch: {record['expectedMime']} vs decoded {mime}")
                record["ok"] = True
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"[:500]
        record = self.assets[key]
        record["usages"] += 1
        if not record["ok"]:
            self.error("invalid-raster", path, record["error"])
        if in_ir and inline:
            self.error("noncanonical-raster-in-ir", path, "Canonical IR must retain blob references, not expanded raster data URLs")
        return record

    def font(self, face, path):
        url = str(face.get("url") or "")
        if url not in self.fonts:
            record = {"url": url, "ok": False, "usages": 0}
            self.fonts[url] = record
            try:
                if not re.fullmatch(r"/fonts/[A-Za-z0-9][A-Za-z0-9._-]{0,127}", url):
                    raise ValueError("Captured font must have a local /fonts/ filename; no fetch attempted")
                file = self.data_root / "fonts" / url.rsplit("/", 1)[-1]
                raw = file.read_bytes()
                kind = FONT_MAGIC.get(raw[:4])
                record.update(file=str(file), bytes=len(raw), sha256=sha(raw), format=kind)
                if kind is None or file.suffix.lower() != "." + kind:
                    raise ValueError("Font magic does not match its filename format")
                record["ok"] = True
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"[:500]
        record = self.fonts[url]
        record["usages"] += 1
        if not record["ok"]:
            self.error("invalid-captured-font", path, record["error"])
        expected = str(face.get("sha256") or "").removeprefix("sha256:")
        if expected and record.get("sha256") != expected:
            self.error("font-hash-mismatch", path, "Font bytes differ from captured font manifest")

    def resources(self, value, label):
        before_assets, before_fonts = set(), set()
        for path, item, in_ir in walk(value, label):
            if isinstance(item, str):
                if item.startswith("ddna://blobs/") or re.match(r"data:image/(png|jpe?g|webp|gif|avif|bmp)\b", item, re.I):
                    record = self.raster(item, path, in_ir=in_ir)
                    before_assets.add(record["reference"])
                elif "ddna://blobs/" in item:
                    for match in BLOB.finditer(item):
                        self.raster(match.group(0), path, in_ir=in_ir)
                        before_assets.add(match.group(0))
            elif isinstance(item, dict):
                faces = (item.get("meta") or {}).get("fontFaces") if isinstance(item.get("meta"), dict) else None
                if isinstance(faces, list):
                    for i, face in enumerate(faces):
                        if isinstance(face, dict):
                            self.font(face, f'{path}["meta"]["fontFaces"][{i}]')
                            before_fonts.add(str(face.get("url") or ""))
                        else:
                            self.error("bad-font-face", path, "Captured font face is not an object")
                if isinstance(item.get("url"), str) and item["url"].startswith("/fonts/") and item.get("sha256"):
                    self.font(item, path)
                    before_fonts.add(item["url"])
                if item.get("type") == "image" and isinstance(item.get("src"), str):
                    src = item["src"]
                    if src.startswith('data:image/svg+xml'):
                        self.vector(item, path + '["src"]')
                    if not src.startswith(("ddna://blobs/", "data:image/")):
                        self.error("nonlocal-image", path + '["src"]', "Image is not self-contained; no fetch attempted")
        return {"uniqueRasters": len(before_assets), "uniqueCapturedFonts": len(before_fonts)}

    def evidence(self, previews, sizes, path):
        checks = {}
        for viewport in VIEWPORTS:
            reference = previews.get(viewport) if isinstance(previews, dict) else None
            size = sizes.get(viewport) if isinstance(sizes, dict) else None
            image = self.raster(reference, f"{path}.previews.{viewport}")
            valid_size = size_valid(size)
            if not valid_size:
                self.error("missing-viewport-size", f"{path}.sizes.{viewport}", "Positive measured viewport size required")
            checks[viewport] = {"imageValid": bool(image and image["ok"]), "sizeValid": valid_size,
                                "size": size, "sha256": image.get("sha256") if image else None}
        return checks

    def master_viewports(self, document, component, path):
        ref = component.get("sourceRef") or {}
        evidence = (document.get("referenceAssets") or {}).get(ref.get("evidenceKey"))
        if not isinstance(evidence, dict):
            self.error("missing-master-evidence", path, "Source evidenceKey has no reference asset")
            return {vp: {"status": "unsupported"} for vp in VIEWPORTS}
        master = component["masterIr"]
        roots = master.get("tree") or []
        root = roots[0] if len(roots) == 1 and isinstance(roots[0], dict) else {}
        bounds_by = ref.get("boundsByViewport") or {}
        revisions = {r.get("revisionHash") for r in document.get("sourceRefs") or [] if isinstance(r, dict)}
        pinned = ref.get("masterHash") == content_hash(master)
        checks = {}
        for viewport in VIEWPORTS:
            bounds = bounds_by.get(viewport)
            block = (evidence.get("blockSizes") or {}).get(viewport)
            image = self.raster((evidence.get("referencePreviews") or {}).get(viewport), f"{path}.evidence.{viewport}")
            explicit_hidden = ((root.get("responsive") or {}).get(viewport) or {}).get("visible") is False
            hidden = (explicit_hidden and viewport not in bounds_by and pinned
                      and ref.get("sourceKey") and ref["sourceKey"] == root.get("sourceKey")
                      and ref.get("sourceRevisionHash") in revisions and bool(ref.get("sourceRevisionHash"))
                      and size_valid(((master.get("responsive") or {}).get("viewports") or {}).get(viewport)))
            if image and image["ok"] and size_valid(block) and hidden:
                checks[viewport] = {"status": "source-hidden", "basis": "pinned-responsive-visible-false"}
                continue
            bounded = size_valid(bounds) and size_valid(block) and all(
                type(bounds.get(k)) in (int, float) and math.isfinite(bounds[k]) and bounds[k] >= 0 for k in ("x", "y"))
            bounded = bounded and bounds["x"] + bounds["width"] <= block["width"] + .5 and bounds["y"] + bounds["height"] <= block["height"] + .5
            visible = root.get("visible") is not False and not explicit_hidden
            valid = bool(image and image["ok"] and bounded and visible)
            checks[viewport] = {"status": "evidence-present" if valid else "unsupported", "bounds": bounds}
            if not valid:
                self.error("unsupported-master-viewport", f"{path}.{viewport}", "Missing/conflicting Source crop bounds or visibility evidence")
        return checks


def source_blocks(value):
    if isinstance(value, dict) and isinstance(value.get("blocks"), list):
        return value["blocks"], value
    for key in ("node", "data", "result"):
        child = value.get(key) if isinstance(value, dict) else None
        if isinstance(child, dict):
            found = source_blocks(child)
            if found is not None:
                return found
    return None


def run(args):
    started = time.monotonic()
    audit = Audit(args.data_root.resolve())
    report = {"schemaVersion": 1, "generatedAt": datetime.now(timezone.utc).isoformat(),
              "readOnlyInputs": True, "dataRoot": str(audit.data_root), "visualFidelityExecuted": False,
              "scope": {"sites": list(args.sources), "pendingSites": [site for site in SYSTEMS if site not in args.sources]},
              "sources": [], "drafts": [], "errors": audit.errors, "warnings": audit.warnings}
    documents = {}
    database = audit.data_root / "design_systems.db"
    try:
        # No store.get_revision(): it migrates documents and may heal registry tables.
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=5) as con:
            con.execute("PRAGMA query_only=ON")
            con.execute("BEGIN")
            for site, system_id in SYSTEMS.items():
                if site not in args.sources:
                    continue
                row = con.execute("SELECT document,content_hash,created_at FROM design_system_revisions WHERE system_id=? AND revision=0",
                                  (system_id,)).fetchone()
                if not row:
                    audit.error("missing-draft", system_id, "No revision-0 snapshot found")
                    continue
                document = json.loads(row[0])
                documents[site] = document
                report["drafts"].append({"site": site, "systemId": system_id, "name": document.get("name"),
                    "savedAt": row[2], "storedContentHash": row[1], "computedContentHash": content_hash(document),
                    "status": document.get("status"), "sourceRefs": document.get("sourceRefs"),
                    "statusCounts": {pool: dict(Counter(str(c.get("status") or "unknown") for c in (document.get(pool) or {}).values()
                        if isinstance(c, dict))) for pool in ("components", "reviewComponents", "suggestions")}})
    except Exception as exc:
        audit.error("database-read-failed", str(database), f"{type(exc).__name__}: {exc}")

    for site, file in args.sources.items():
        try:
            raw = file.read_bytes()
            found = source_blocks(json.loads(raw.decode("utf-8-sig")))
            if found is None or not found[0]:
                raise ValueError("Snapshot contains no Source blocks")
            blocks, payload = found
            entry = {"site": site, "path": str(file), "sha256": sha(raw),
                     "modifiedAt": datetime.fromtimestamp(file.stat().st_mtime, timezone.utc).isoformat(),
                     "blockCount": len(blocks), "resources": audit.resources(payload, f"source.{site}"), "blocks": []}
            for i, block in enumerate(blocks):
                if not isinstance(block, dict):
                    audit.error("invalid-source-block", f"source.{site}[{i}]", "Block is not an object")
                    continue
                entry["blocks"].append({"name": block.get("name"), "selector": block.get("selector"),
                    "viewports": audit.evidence(block.get("previews"), block.get("sizes"), f"source.{site}[{i}]"),
                    "storedFidelity": block.get("fidelity"),
                    "storedGate": (block.get("fidelityReport") or {}).get("gate")})
            report["sources"].append(entry)
        except Exception as exc:
            audit.error("source-read-failed", str(file), f"{type(exc).__name__}: {exc}")

    master_inputs, master_results = [], []
    for entry in report["drafts"]:
        site = entry["site"]
        document = documents[site]
        entry["resources"] = audit.resources(document, f"draft.{site}")
        entry["masters"] = []
        entry["referenceViewports"] = {key: audit.evidence(ev.get("referencePreviews"), ev.get("blockSizes"),
            f"draft.{site}.referenceAssets.{key}") for key, ev in (document.get("referenceAssets") or {}).items() if isinstance(ev, dict)}
        if entry["computedContentHash"] != entry["storedContentHash"]:
            audit.error("draft-content-hash-mismatch", entry["systemId"], "Saved document differs from revision-row hash")
        for path, value, _ in walk(document, f"draft.{site}"):
            if not isinstance(value, dict) or not isinstance(value.get("masterIr"), dict):
                continue
            pin = (value.get("sourceRef") or {}).get("masterHash")
            if not pin and value.get("origin") not in ("observed",):
                continue
            actual = content_hash(value["masterIr"])
            result = {"path": path, "pin": pin, "computedHash": actual, "pinValid": pin == actual,
                      "status": value.get("status"), "roundtripStable": None}
            entry["masters"].append(result)
            if pin != actual:
                audit.error("master-pin-mismatch", path, "Observed master is unpinned or differs from pinned Source content")
            result["viewports"] = audit.master_viewports(document, value, path)
            master_inputs.append(value["masterIr"])
            master_results.append(result)
        if not entry["masters"]:
            audit.error("no-pinned-masters", entry["systemId"], "No exact masters to audit")

    try:
        node = args.node or shutil.which("node")
        if not node:
            raise RuntimeError("Node unavailable; actual JS round trip was NOT verified")
        js = 'process.stdout.write(JSON.stringify(JSON.parse(require("node:fs").readFileSync(0,"utf8"))))'
        process = subprocess.run([str(node), "-e", js], input=json.dumps(master_inputs, allow_nan=False),
                                 encoding="utf-8", capture_output=True, check=True, timeout=30)
        roundtripped = json.loads(process.stdout)
        if not isinstance(roundtripped, list) or len(roundtripped) != len(master_results):
            raise ValueError("Node returned an unexpected number of masters")
        for result, master in zip(master_results, roundtripped):
            result["roundtripHash"] = content_hash(master)
            result["roundtripStable"] = result["roundtripHash"] == result["computedHash"] == result["pin"]
            if not result["roundtripStable"]:
                audit.error("javascript-roundtrip-pin-mismatch", result["path"], "Pin did not survive Node JSON.parse/stringify")
        report["javascriptRoundtrip"] = {"executed": True, "node": str(node), "masters": len(master_results)}
    except Exception as exc:
        report["javascriptRoundtrip"] = {"executed": False}
        audit.error("javascript-roundtrip-failed", "Node", f"{type(exc).__name__}: {exc}")
    report["assets"] = list(audit.assets.values())
    report["fonts"] = list(audit.fonts.values())
    report['vectors'] = list(audit.vectors.values())
    # De-duplicate exact findings from repeated canonical/master/suggestion references.
    report["errors"] = list({json.dumps(e, sort_keys=True): e for e in audit.errors}.values())
    report["ok"] = not report["errors"]
    report["elapsedSeconds"] = round(time.monotonic() - started, 3)
    report["summary"] = {"drafts": len(report["drafts"]), "sources": len(report["sources"]),
        "masters": len(master_results), "uniqueRasters": len(audit.assets), "uniqueFonts": len(audit.fonts),
        "uniqueVectors": len(audit.vectors),
        "errors": len(report["errors"]), "warnings": len(report["warnings"])}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--node", help="Explicit Node executable (e.g. for packaged-runtime audit)")
    parser.add_argument("--site", choices=["all", *SYSTEMS], default="all", help="Audit only a confirmed-fresh site; others remain pending")
    parser.add_argument("--source", action="append", required=True, metavar="SITE=PATH",
                        help="Exact fresh snapshot, once each for slsbmb and rsale; no automatic latest-file guessing")
    args = parser.parse_args()
    args.sources = {}
    for item in args.source:
        site, sep, filename = item.partition("=")
        if not sep or site not in SYSTEMS or site in args.sources:
            parser.error("--source requires unique slsbmb=PATH and rsale=PATH")
        args.sources[site] = Path(filename).resolve()
    required = set(SYSTEMS) if args.site == "all" else {args.site}
    if set(args.sources) != required:
        parser.error("Supply exactly one --source SITE=PATH for each selected site")
    output = args.output.resolve()
    # The report may not overwrite a database, asset or input snapshot.
    if output == Path(__file__).resolve() or output in args.sources.values() or args.data_root.resolve() in output.parents:
        parser.error("Output must be outside the read-only data root and cannot overwrite an input")
    if output.suffix.lower() != ".json":
        parser.error("Output must be a .json report")
    report = run(args)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "output": str(output), **report["summary"]}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
