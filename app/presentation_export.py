"""Native DrawingML text/geometry plus isolated images, using only stdlib OOXML.

The blank package was authored with Artifact Tool; runtime export does not depend
on Office, Codex's private runtime, a provider, or an additional Python library.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from config import settings
from ir_render import _neutralize_links
from presentation_scene import capture_scene
from timeline_assets import materialize_render_assets

NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
      "ct": "http://schemas.openxmlformats.org/package/2006/content-types"}
for prefix in ("p", "a", "r"):
    ET.register_namespace(prefix, NS[prefix])
BASE = settings.app_dir() / "static" / "export" / "presentation-base.pptx"


def tag(name: str) -> str:
    prefix, local = name.split(":")
    return "{" + NS[prefix] + "}" + local


def sub(parent, element_name: str, **attrs):
    return ET.SubElement(parent, tag(element_name), {key: str(value) for key, value in attrs.items()})


def xml(root) -> bytes:
    result = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    # OPC consumers require the package parts' default namespace, unlike
    # DrawingML's prefixed namespace. Do not change ElementTree's process-wide
    # namespace registry while concurrent exports may be running.
    if root.tag.startswith(("{" + NS["ct"] + "}", "{" + NS["rel"] + "}")):
        match = re.search(rb"<([A-Za-z0-9_]+):", result)
        if match:
            prefix = match.group(1)
            result = result.replace(b"xmlns:" + prefix + b"=", b"xmlns=", 1)
            result = result.replace(b"<" + prefix + b":", b"<").replace(b"</" + prefix + b":", b"</")
    return result


def paint(parent, value: dict | None):
    if not value or value.get("alpha", 0) <= 0:
        sub(parent, "a:noFill")
        return
    color = sub(sub(parent, "a:solidFill"), "a:srgbClr", val=value["hex"])
    if value["alpha"] < 1:
        sub(color, "a:alpha", val=round(value["alpha"] * 100000))


def build_pptx(scene: dict, source_ir: dict) -> tuple[bytes, dict]:
    """One IR artboard is one fixed-size slide; preserve its source and assets."""
    items = scene["items"]
    if len(items) > 4000:
        raise ValueError("Слишком много объектов для одного слайда")
    width, height = scene["width"], scene["height"]
    if not (1 <= width <= 16000 and 1 <= height <= 16000):
        raise ValueError("Неверный размер слайда")
    scale = min(1, 5376 / max(width, height))  # PowerPoint's 56-inch canvas limit.

    def emu(value):
        return round(float(value) * 9525 * scale)

    with ZipFile(BASE) as archive:
        package = {name: archive.read(name) for name in archive.namelist()}
    slide = ET.fromstring(package["ppt/slides/slide1.xml"])
    tree = slide.find("p:cSld/p:spTree", NS)
    rels = ET.fromstring(package["ppt/slides/_rels/slide1.xml.rels"])
    types = ET.fromstring(package["[Content_Types].xml"])
    pres = ET.fromstring(package["ppt/presentation.xml"])
    pres.find("p:sldSz", NS).attrib.update(cx=str(emu(width)), cy=str(emu(height)))
    media_by_hash = {}
    fonts = set()
    counts = {"text": 0, "shapes": 0, "images": 0, "links": 0}
    for index, item in enumerate(items, 2):
        kind = item["kind"]
        if kind not in {"text", "shape", "image"}:
            raise ValueError("Неизвестный объект экспортируемой сцены")
        is_picture = kind == "image"
        node = sub(tree, "p:pic" if is_picture else "p:sp")
        nv = sub(node, "p:nvPicPr" if is_picture else "p:nvSpPr")
        name = str(item.get("text") or item.get("path") or kind)[:120]
        sub(nv, "p:cNvPr", id=index, name=f"{kind} {index}: {name}", descr=item.get("path", ""))
        sub(nv, "p:cNvPicPr" if is_picture else "p:cNvSpPr", **({"txBox": 1} if kind == "text" else {}))
        sub(nv, "p:nvPr")
        if is_picture:
            raw = base64.b64decode(item["png"], validate=True)
            sha = hashlib.sha256(raw).hexdigest()
            if sha not in media_by_hash:
                image_name = f"image{len(media_by_hash) + 1}.png"
                rid = "ddnaImage" + str(len(media_by_hash) + 1)
                media_by_hash[sha] = rid
                package["ppt/media/" + image_name] = raw
                sub(rels, "rel:Relationship", Id=rid, Type=NS["r"] + "/image", Target="../media/" + image_name)
            fill = sub(node, "p:blipFill")
            sub(fill, "a:blip", **{tag("r:embed"): media_by_hash[sha]})
            sub(sub(fill, "a:stretch"), "a:fillRect")
            counts["images"] += 1
        props = sub(node, "p:spPr")
        transform = sub(props, "a:xfrm")
        sub(transform, "a:off", x=emu(item["x"]), y=emu(item["y"]))
        # Browser text is already broken into visual lines. A little spare width
        # allows Office's glyph rounding without changing the measured origin.
        spare = item.get("size", 0) * 0.25 if kind == "text" else 0
        sub(transform, "a:ext", cx=max(1, emu(item["w"] + spare)), cy=max(1, emu(item["h"])))
        radius = item.get("radius", 0) if kind == "shape" else 0
        geom = sub(props, "a:prstGeom", prst="roundRect" if radius else "rect")
        adjustments = sub(geom, "a:avLst")
        if radius:
            sub(adjustments, "a:gd", name="adj", fmla="val " + str(round(100000 * radius / max(1, min(item["w"], item["h"])))))
        if not is_picture:
            paint(props, item.get("fill") if kind == "shape" else None)
            line = sub(props, "a:ln", w=emu(item.get("strokeWidth", 0)))
            paint(line, item.get("stroke") if item.get("strokeWidth", 0) else None)
            if item.get("dash") in {"dashed", "dotted"}:
                sub(line, "a:prstDash", val="dash" if item["dash"] == "dashed" else "dot")
        if kind == "shape":
            counts["shapes"] += 1
        if kind != "text":
            continue
        counts["text"] += 1
        family = item["family"]
        fonts.add(family)
        body = sub(node, "p:txBody")
        body_props = sub(body, "a:bodyPr", wrap="none", lIns=0, tIns=0, rIns=0, bIns=0, anchor="t")
        sub(body_props, "a:noAutofit")
        sub(body, "a:lstStyle")
        para = sub(body, "a:p")
        ppr = sub(para, "a:pPr", marL=0, marR=0, indent=0)
        sub(sub(ppr, "a:lnSpc"), "a:spcPct", val=100000)
        sub(ppr, "a:buNone")
        run = sub(para, "a:r")
        rpr = sub(run, "a:rPr", lang="ru-RU", sz=max(100, round(item["size"] * 75 * scale)),
                  b=int(item["bold"]), i=int(item["italic"]), u="sng" if item["underline"] else "none",
                  spc=round(item.get("spacing", 0) * 75 * scale), dirty=0)
        paint(rpr, item["color"])
        for script in ("latin", "ea", "cs"):
            sub(rpr, "a:" + script, typeface=family)
        href = item.get("href", "")
        if urlsplit(href).scheme.lower() in {"https", "http", "mailto", "tel"}:
            rid = "ddnaLink" + str(index)
            sub(rels, "rel:Relationship", Id=rid, Type=NS["r"] + "/hyperlink", Target=href, TargetMode="External")
            sub(rpr, "a:hlinkClick", **{tag("r:id"): rid})
            counts["links"] += 1
        sub(run, "a:t").text = item["text"]

    if media_by_hash and not any(el.attrib.get("Extension") == "png" for el in types):
        sub(types, "ct:Default", Extension="png", ContentType="image/png")
    source_json = json.dumps(source_ir, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    report = {"version": "design-pptx/1.0", "slides": 1, "width": width, "height": height, "viewport": scene.get("viewport", "desktop"),
              "scale": scale, **counts, "fonts": sorted(fonts), "fontsEmbedded": False,
              "rasterFallbacks": scene.get("warnings", []), "sourceHash": hashlib.sha256(source_json.encode()).hexdigest()}
    assets, errors = materialize_render_assets(_neutralize_links(source_ir))
    if errors:
        raise ValueError("Исходные ресурсы не сохранены: " + "; ".join(errors[:3]))
    if sum(len(a.data) for a in assets.values()) > 48_000_000:
        raise ValueError("Исходные ресурсы превышают 48 MB")
    envelope = {"version": "design-pptx-source/1.0", "ir": source_ir, "report": report,
                "assets": {url: "data:" + asset.mime + ";base64," + base64.b64encode(asset.data).decode()
                           for url, asset in assets.items()}}
    source = ET.Element("designDNA", {"xmlns": "urn:designdna:presentation-source:1"})
    source.text = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    package["customXml/designDNA.xml"] = xml(source)
    sub(rels, "rel:Relationship", Id="ddnaSource", Type=NS["r"] + "/customXml", Target="../../customXml/designDNA.xml")
    sub(types, "ct:Override", PartName="/customXml/designDNA.xml", ContentType="application/xml")
    package.update({"ppt/slides/slide1.xml": xml(slide), "ppt/presentation.xml": xml(pres),
                    "ppt/slides/_rels/slide1.xml.rels": xml(rels), "[Content_Types].xml": xml(types)})
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in package.items():
            archive.writestr(name, content)
    return output.getvalue(), report


def export_presentation(ir: dict, *, width: int = 1280, viewport: str = "desktop") -> dict:
    scene, source = capture_scene(ir, width=width, viewport=viewport)
    content, report = build_pptx(scene, source)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", str((ir.get("meta") or {}).get("name") or "DesignDNA"))[:80].strip(" .") or "DesignDNA"
    return {"filename": name + ".pptx", "base64": base64.b64encode(content).decode(), "report": report}
