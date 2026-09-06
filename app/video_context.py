"""Read the supplied page visually and structurally before directing its animation."""
import base64
import hashlib
import json
from io import BytesIO
from PIL import Image
import cache_store
import cancel_token
from ir_render import render_png


def prepare_context(timeline):
    result = []
    for page in timeline["story"]["pages"]:
        cancel_token.check()
        # Derived pages have the same geometry; their changed text/overlays are
        # supplied by the director context. Read every connected source visually.
        if page.get("generatedFrom"):
            continue
        ir = page["ir"]
        key = hashlib.sha256(json.dumps(ir, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        cached = cache_store.get("video-visual-context-v1", key)
        if cached is None:
            try:
                png = render_png(ir, width=1440, webfonts=False)
            except Exception as exc:
                raise ValueError("Не удалось изучить визуал страницы «" + page["name"] + "»: " + str(exc)[:350]) from exc
            picture = Image.open(BytesIO(png)).convert("RGB")
            images = []
            # Readable tiles with overlap, including the bottom of long pages.
            count = min(6, max(1, (picture.height + 999) // 1000))
            starts = [round(i * max(0, picture.height - 1200) / max(1, count - 1)) for i in range(count)]
            for top in dict.fromkeys(starts):
                tile = picture.crop((0, top, picture.width, min(picture.height, top + 1200)))
                tile.thumbnail((1440, 1200))
                output = BytesIO(); tile.save(output, format="JPEG", quality=85)
                images.append({"top": top, "url": "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode()})
            cached = {"images": images}
            cache_store.put("video-visual-context-v1", key, cached)
        result.append({"pageId": page["id"], "name": page["name"], **cached})
    return result


def structure(ir):
    nodes = []
    def visit(node, ident, parent):
        nodes.append({"id": ident, "parentId": parent, "type": node.get("type"), "sourceKey": node.get("sourceKey"),
                      "text": {k: node[k] for k in ("text", "label", "title", "placeholder", "alt", "imagePrompt") if isinstance(node.get(k), str)},
                      "frame": node.get("frame", {}), "style": node.get("style", {})})
        for i, child in enumerate(node.get("children") or []):
            visit(child, f"{ident}.children.{i}", ident)
    for i, section in enumerate(ir.get("tree", [])):
        visit(section, f"s{i}", None)
    return nodes
