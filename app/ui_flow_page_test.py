"""Playwright-РЎвЂљР ВµРЎРѓРЎвЂљ Р Р…Р С•Р Т‘РЎвЂ№ Page (Р С”Р С•Р СР С—Р С•Р Р…Р С•Р Р†РЎвЂ°Р С‘Р С” РЎРѓРЎвЂљРЎР‚Р В°Р Р…Р С‘РЎвЂ РЎвЂ№ Р С‘Р В· Р В±Р В»Р С•Р С”Р С•Р Р†).

Р вЂР ВµР В· LLM: IR Р В·Р В°Р Т‘Р В°РЎвЂРЎвЂљРЎРѓРЎРЏ РЎвЂЎР ВµРЎР‚Р ВµР В· GraphDev.setIR Р Р…Р В° edit-Р Р…Р С•Р Т‘Р В°РЎвЂ¦-Р С‘РЎРѓРЎвЂљР С•РЎвЂЎР Р…Р С‘Р С”Р В°РЎвЂ¦.
Р СџРЎР‚Р С•Р Р†Р ВµРЎР‚РЎРЏР ВµРЎвЂљ: РЎРѓР С•Р В·Р Т‘Р В°Р Р…Р С‘Р Вµ Р С‘Р В· ctx-Р СР ВµР Р…РЎР‹, Р С—Р С•РЎР‚РЎвЂљРЎвЂ№ (tokens + Р Т‘Р С‘Р Р…Р В°Р СР С‘РЎвЂЎР ВµРЎРѓР С”Р С‘Р Вµ a/b + Р Р†РЎвЂ№РЎвЂ¦Р С•Р Т‘ ir),
РЎРѓР В±Р С•РЎР‚Р С”РЎС“ РЎРѓРЎвЂљРЎР‚Р В°Р Р…Р С‘РЎвЂ РЎвЂ№ (Р С—Р С•РЎР‚РЎРЏР Т‘Р С•Р С” Р Р†РЎвЂ¦Р С•Р Т‘Р С•Р Р† = Р С—Р С•РЎР‚РЎРЏР Т‘Р С•Р С” РЎРѓР ВµР С”РЎвЂ Р С‘Р в„–, РЎС“Р Р…Р С‘Р С”Р В°Р В»РЎРЉР Р…РЎвЂ№Р Вµ id/sourceKey,
width:"fill", Р В°РЎР‚РЎвЂљР В±Р С•РЎР‚Р Т‘ 1440), Р В»Р С•Р С” РЎвЂљР С•Р С”Р ВµР Р…Р С•Р Р† style DNA, reorder Р С”Р Р…Р С•Р С—Р С”Р С•Р в„– РІвЂ вЂњ,
Р С—РЎР‚Р С•Р Р†Р С•Р Т‘ page РІвЂ вЂ™ edit.
Р СњРЎС“Р В¶Р ВµР Р… Р В·Р В°Р С—РЎС“РЎвЂ°Р ВµР Р…Р Р…РЎвЂ№Р в„– РЎРѓР ВµРЎР‚Р Р†Р ВµРЎР‚: .venv/Scripts/python app/server.py
Р вЂ”Р В°Р С—РЎС“РЎРѓР С”: .venv/Scripts/python app/ui_flow_page_test.py
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
FAILS = []

TOKENS_A = {
    "mode": "light",
    "color": {
        "primary": "#111111",
        "background": "#ffffff",
        "surface": "#f5f5f7",
        "text": "#111111",
        "textMuted": "#666666",
        "border": "#e0e0e0",
    },
}
TOKENS_DNA = {
    "mode": "dark",
    "color": {
        "primary": "#ff6b20",
        "background": "#101010",
        "surface": "#1a1a1a",
        "text": "#f8fafc",
        "textMuted": "#b8b8c0",
        "border": "#333333",
    },
}


def make_ir(sec_id, text, tokens):
    return {
        "version": "1.0",
        "meta": {"name": sec_id},
        "tokens": tokens,
        "tree": [{
            "id": sec_id, "type": "hero",
            "props": {"heading": text, "subheading": "S",
                      "ctaPrimary": {"text": "Go", "variant": "primary"}},
            "sourceKey": "root",
            "style": {"background": "#ffffff", "borderColor": "#e0e0e0"},
            "children": [{
                "type": "text",
                "text": text,
                "sourceKey": "root/t:1",
                "style": {"color": "#111111", "background": "#f5f5f7", "borderColor": "#e0e0e0"},
            }],
        }],
    }


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" РІР‚вЂќ {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1920, "height": 1080})
        for _ in range(30):
            try:
                pg.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            print("server not ready")
            sys.exit(2)
        pg.evaluate("localStorage.clear()")
        pg.reload()
        pg.wait_for_selector(".svelte-flow__pane")
        pg.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        # изоляция от состояния в SQLite: boot мог подтянуть прошлый проект из БД
        pg.evaluate("window.GraphDev.clear()")

        # ---------- ctx-Р СР ВµР Р…РЎР‹: 14 РЎвЂљР С‘Р С—Р С•Р Р†, Р ВµРЎРѓРЎвЂљРЎРЉ Page ----------
        pg.click(".svelte-flow__pane", button="right")
        check("Р Р† Р СР ВµР Р…РЎР‹ 14 РЎвЂљР С‘Р С—Р С•Р Р† Р Р…Р С•Р Т‘",
              pg.evaluate("document.querySelectorAll('#ctx-menu .ctx-item').length === 16"))
        check("Р Р† Р СР ВµР Р…РЎР‹ Р ВµРЎРѓРЎвЂљРЎРЉ Р РЋРЎвЂљРЎР‚Р В°Р Р…Р С‘РЎвЂ Р В°",
              pg.evaluate("!!document.querySelector('#ctx-menu .ctx-item[data-type=\"page\"]')"))
        pg.click("#ctx-menu .ctx-item[data-type='page']")
        pg.wait_for_selector(".n-page")
        pg.keyboard.press("Escape")

        # ---------- Р С—Р С•РЎР‚РЎвЂљРЎвЂ№ ----------
        check("Р Р†РЎвЂ¦Р С•Р Т‘ tokens (style DNA)",
              pg.locator(".n-page .port-row.in[data-port='tokens'][data-kind='tokens']").count() == 1)
        check("Р Т‘Р С‘Р Р…Р В°Р СР С‘РЎвЂЎР ВµРЎРѓР С”Р С‘Р Вµ Р Р†РЎвЂ¦Р С•Р Т‘РЎвЂ№ a/b kind ir",
              pg.locator(".n-page .port-row.in[data-kind='ir']").count() == 2)
        check("Р Р†РЎвЂ№РЎвЂ¦Р С•Р Т‘ ir", pg.locator(".n-page .port-row.out[data-port='ir']").count() == 1)

        # ---------- Р С‘РЎРѓРЎвЂљР С•РЎвЂЎР Р…Р С‘Р С”Р С‘-Р В±Р В»Р С•Р С”Р С‘ ----------
        pg.evaluate("""(() => {
            const e1 = window.GraphDev.add('edit', 60, 60);
            const e2 = window.GraphDev.add('edit', 60, 460);
            window.__e1 = e1.id; window.__e2 = e2.id;
        })()""")
        e1 = int(pg.evaluate("window.__e1"))
        e2 = int(pg.evaluate("window.__e2"))
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % e1, make_ir("hero", "Р вЂР В»Р С•Р С” A", TOKENS_A))
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % e2, make_ir("hero", "Р вЂР В»Р С•Р С” B", TOKENS_A))
        page_id = int(pg.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'page').id"))

        check("connect edit1.ir РІвЂ вЂ™ page.a",
              pg.evaluate("([f, t]) => window.GraphDev.connect(f, 'ir', t, 'a')", [e1, page_id]))
        check("connect edit2.ir РІвЂ вЂ™ page.b",
              pg.evaluate("([f, t]) => window.GraphDev.connect(f, 'ir', t, 'b')", [e2, page_id]))

        pg.evaluate("(id) => window.GraphDev.run(id)", page_id)
        pg.wait_for_timeout(300)
        st = pg.evaluate(f"""(() => {{
            const ir = window.GraphDev.node({page_id}).data.ir;
            return {{
                sections: ir.tree.length,
                ids: ir.tree.map(s => s.id),
                texts: ir.tree.map(s => s.props.heading),
                widths: ir.tree.map(s => s.frame && s.frame.width),
                artboard: ir.frame.width,
                primary: ir.tokens.color.primary,
            }};
        }})()""")
        check("РЎРѓРЎвЂљРЎР‚Р В°Р Р…Р С‘РЎвЂ Р В° РЎРѓР С•Р В±РЎР‚Р В°Р Р…Р В° Р С‘Р В· 2 Р В±Р В»Р С•Р С”Р С•Р Р†", st["sections"] == 2, str(st))
        check("Р С—Р С•РЎР‚РЎРЏР Т‘Р С•Р С” РЎРѓР ВµР С”РЎвЂ Р С‘Р в„– = Р С—Р С•РЎР‚РЎРЏР Т‘Р С•Р С” Р Р†РЎвЂ¦Р С•Р Т‘Р С•Р Р†", st["texts"] == ["Р вЂР В»Р С•Р С” A", "Р вЂР В»Р С•Р С” B"], str(st["texts"]))
        check("id РЎРѓР ВµР С”РЎвЂ Р С‘Р в„– РЎС“Р Р…Р С‘Р С”Р В°Р В»РЎРЉР Р…РЎвЂ№", len(set(st["ids"])) == 2, str(st["ids"]))
        check("РЎРѓР ВµР С”РЎвЂ Р С‘Р С‘ width:fill, Р В°РЎР‚РЎвЂљР В±Р С•РЎР‚Р Т‘ 1440",
              all(w == "fill" for w in st["widths"]) and st["artboard"] == 1440, str(st))
        check("РЎвЂљР С•Р С”Р ВµР Р…РЎвЂ№ Р С—Р ВµРЎР‚Р Р†Р С•Р С–Р С• Р В±Р В»Р С•Р С”Р В° Р В±Р ВµР В· DNA-Р С—РЎР‚Р С•Р Р†Р С•Р Т‘Р В°", st["primary"] == "#111111", st["primary"])
        check("Р С—РЎР‚Р ВµР Р†РЎРЉРЎР‹ РЎРѓРЎвЂљРЎР‚Р В°Р Р…Р С‘РЎвЂ РЎвЂ№ Р С•РЎвЂљРЎР‚Р ВµР Р…Р Т‘Р ВµРЎР‚Р С‘Р В»Р С•РЎРѓРЎРЉ",
              pg.locator(".n-page .f-preview .ir-preview-inner div[class^='ir-']").count() > 0)

        # ---------- style DNA РЎРѓ Р С—РЎР‚Р С•Р Р†Р С•Р Т‘Р В° Р С—Р С•Р В±Р ВµР В¶Р Т‘Р В°Р ВµРЎвЂљ ----------
        pg.evaluate("""(() => {
            const sd = window.GraphDev.add('designsystem', 60, 760);
            window.__sd = sd.id;
        })()""")
        sd = int(pg.evaluate("window.__sd"))
        pg.evaluate("([id, t]) => window.GraphDev.patchData(id, { document: { styleGuide: { tokens: t } } })", [sd, TOKENS_DNA])
        check("connect styledna.tokens РІвЂ вЂ™ page.tokens",
              pg.evaluate("([f, t]) => window.GraphDev.connect(f, 'tokens', t, 'tokens')", [sd, page_id]))
        pg.evaluate("(id) => window.GraphDev.run(id)", page_id)
        pg.wait_for_timeout(300)
        dna_applied = pg.evaluate(f"""(() => {{
            const ir = window.GraphDev.node({page_id}).data.ir;
            const sec = ir.tree[0];
            const child = sec.children[0];
            return {{
                primary: ir.tokens.color.primary,
                sectionBg: sec.style.background,
                sectionBorder: sec.style.borderColor,
                childBg: child.style.background,
                childColor: child.style.color,
                childBorder: child.style.borderColor,
            }};
        }})()""")
        check("style DNA tokens are locked on page",
              dna_applied["primary"] == "#ff6b20", str(dna_applied))
        check("style DNA maps inline backgrounds instead of only root tokens",
              dna_applied["sectionBg"] == "#101010" and dna_applied["childBg"] == "#1a1a1a",
              str(dna_applied))
        check("style DNA keeps inline text readable",
              dna_applied["childColor"] == "#f8fafc" and dna_applied["childBorder"] == "#333333",
              str(dna_applied))

        # ---------- reorder Р С”Р Р…Р С•Р С—Р С”Р С•Р в„– РІвЂ вЂњ Р СР ВµР Р…РЎРЏР ВµРЎвЂљ Р С—Р С•РЎР‚РЎРЏР Т‘Р С•Р С” РЎРѓР ВµР С”РЎвЂ Р С‘Р в„– ----------
        pg.click(".n-page .page-row[data-port='a'] .page-row-ctl button:nth-child(2)")
        pg.evaluate("(id) => window.GraphDev.run(id)", page_id)
        pg.wait_for_timeout(300)
        texts = pg.evaluate(f"window.GraphDev.node({page_id}).data.ir.tree.map(s => s.props.heading)")
        check("reorder: Р вЂР В»Р С•Р С” B РЎРѓРЎвЂљР В°Р В» Р С—Р ВµРЎР‚Р Р†РЎвЂ№Р С", texts == ["Р вЂР В»Р С•Р С” B", "Р вЂР В»Р С•Р С” A"], str(texts))

        # ---------- Р Р†РЎвЂ№РЎвЂ¦Р С•Р Т‘ page РІвЂ вЂ™ edit ----------
        edit3 = int(pg.evaluate("window.GraphDev.add('edit', 700, 60).id"))
        check("connect page.ir РІвЂ вЂ™ edit.ir",
              pg.evaluate("([f, t]) => window.GraphDev.connect(f, 'ir', t, 'a')", [page_id, edit3]))
        pg.wait_for_timeout(300)
        downstream = pg.evaluate(f"(() => {{ const ir = window.GraphDev.node({edit3}).data.ir; return ir ? ir.tree.length : 0; }})()")
        check("РЎРѓРЎвЂљРЎР‚Р В°Р Р…Р С‘РЎвЂ Р В° Р С—РЎР‚Р С•РЎвЂљР ВµР С”Р В»Р В° Р Р† edit-Р Р…Р С•Р Т‘РЎС“", downstream == 2, str(downstream))

        # ---------- responsive: Р СР ВµРЎвЂљР В° Р Р†РЎРЉРЎР‹Р С—Р С•РЎР‚РЎвЂљР С•Р Р† Р С‘ Р СР В°РЎвЂљР ВµРЎР‚Р С‘Р В°Р В»Р С‘Р В·Р В°РЎвЂ Р С‘РЎРЏ ----------
        resp = pg.evaluate(f"""(() => {{
            const ir = window.GraphDev.node({page_id}).data.ir;
            return {{ vps: ir.responsive && ir.responsive.viewports
                ? Object.entries(ir.responsive.viewports).map(([k, v]) => k + ":" + v.width) : [],
                active: ir.meta && ir.meta.activeViewport }};
        }})()""")
        check("responsive viewports 1440/768/390",
              resp["vps"] == ["desktop:1440", "tablet:768", "mobile:390"], str(resp))
        check("activeViewport Р С—Р С• РЎС“Р СР С•Р В»РЎвЂЎР В°Р Р…Р С‘РЎР‹ desktop", resp["active"] == "desktop", str(resp))

        # Р СР С•Р В±Р С‘Р В»РЎРЉР Р…РЎвЂ№Р в„– РЎРѓР В»Р С•Р в„– РЎРѓР С”РЎР‚РЎвЂ№РЎвЂљ Р Р…Р В° mobile, Р Р†Р С‘Р Т‘Р ВµР Р… Р Р…Р В° desktop
        pg.evaluate("""(id) => {
            const node = window.GraphDev.node(id);
            const ir = JSON.parse(JSON.stringify(node.data.ir));
            ir.tree[0].children.push({ type: 'text', text: 'ONLY-DESKTOP-TEXT',
                sourceKey: 'root/t:9', responsive: { mobile: { visible: false } } });
            window.GraphDev.patchData(id, { ir });
        }""", e2)
        pg.evaluate("(id) => window.GraphDev.run(id)", page_id)
        pg.wait_for_timeout(300)
        mat = pg.evaluate(f"""(() => {{
            const ir = window.GraphDev.node({page_id}).data.ir;
            const find = (doc) => {{ let hit = null;
                const walk = (n) => {{ if (n.text === 'ONLY-DESKTOP-TEXT') hit = n;
                    (n.children || []).forEach(walk); }};
                (doc.tree || []).forEach(walk); return hit; }};
            const desktop = window.IRRenderer.materializeResponsiveIR(JSON.parse(JSON.stringify(ir)), 'desktop');
            const mobile = window.IRRenderer.materializeResponsiveIR(JSON.parse(JSON.stringify(ir)), 'mobile');
            return {{ d: !!find(desktop) && !find(desktop).__responsiveHidden,
                      m: !!(find(mobile) || {{}}).__responsiveHidden }};
        }})()""")
        check("desktop: РЎРѓР В»Р С•Р в„– Р СР В°РЎвЂљР ВµРЎР‚Р С‘Р В°Р В»Р С‘Р В·Р С•Р Р†Р В°Р Р… Р Р†Р С‘Р Т‘Р С‘Р СРЎвЂ№Р С", mat["d"], str(mat))
        check("mobile: РЎРѓР В»Р С•Р в„– РЎРѓ visible:false Р С—Р С•Р СР ВµРЎвЂЎР ВµР Р… РЎРѓР С”РЎР‚РЎвЂ№РЎвЂљРЎвЂ№Р С", mat["m"], str(mat))
        pg.click(".n-page .source-viewport:has-text('Mobile')")
        pg.wait_for_timeout(400)
        active_down = pg.evaluate(f"window.GraphDev.node({page_id}).data.activeViewport")
        check("Р С—Р ВµРЎР‚Р ВµР С”Р В»РЎР‹РЎвЂЎР ВµР Р…Р С‘Р Вµ Р Р†РЎРЉРЎР‹Р С—Р С•РЎР‚РЎвЂљР В° Р С•РЎвЂљРЎР‚Р В°Р В¶Р ВµР Р…Р С• Р Р† Р Р…Р С•Р Т‘Р Вµ", active_down == "mobile", str(active_down))
        edit_vp = pg.evaluate(f"window.GraphDev.node({edit3}).data.ir.meta.activeViewport")
        check("Р Р†РЎРЉРЎР‹Р С—Р С•РЎР‚РЎвЂљ Р С—РЎР‚Р С•РЎвЂљРЎвЂР С” Р Р†Р Р…Р С‘Р В· Р С—Р С• Р С–РЎР‚Р В°РЎвЂћРЎС“ (edit)", edit_vp == "mobile", str(edit_vp))

        # ---------- РЎР‚Р ВµР С–РЎР‚Р ВµРЎРѓРЎРѓР С‘Р С‘ Page РІвЂ вЂ™ DNA Editor (multi-device) ----------
        # 1) composePage РЎРѓРЎР‚Р ВµР В·Р В°Р ВµРЎвЂљ Р С—Р С•Р В·Р С‘РЎвЂ Р С‘Р С•Р Р…Р Р…РЎвЂ№Р Вµ Р С•РЎРѓРЎвЂљР В°РЎвЂљР С”Р С‘ РЎРѓР ВµР С”РЎвЂ Р С‘Р в„– (x/y/absolute Р С•РЎвЂљ Р С—РЎР‚Р В°Р Р†Р С•Р С” Р В±Р В»Р С•Р С”Р В°)
        pg.evaluate("""(id) => {
            const node = window.GraphDev.node(id);
            const ir = JSON.parse(JSON.stringify(node.data.ir));
            ir.tree[0].frame = { x: 15, y: 20, absolute: true, width: 300, height: 200 };
            window.GraphDev.patchData(id, { ir });
        }""", e1)
        pg.evaluate("(id) => window.GraphDev.run(id)", page_id)
        pg.wait_for_timeout(300)
        secf = pg.evaluate(f"""(() => {{
            const ir = window.GraphDev.node({page_id}).data.ir;
            const s = ir.tree.find(s => s.props && s.props.heading === 'Р вЂР В»Р С•Р С” A');
            return s && s.frame;
        }})()""")
        check("compose: x/y/absolute РЎРѓР ВµР С”РЎвЂ Р С‘Р С‘ РЎРѓРЎР‚Р ВµР В·Р В°Р Р…РЎвЂ№",
              secf is not None and "x" not in secf and "y" not in secf and "absolute" not in secf,
              str(secf))
        check("compose: width:fill Р С‘ height РЎРѓР ВµР С”РЎвЂ Р С‘Р С‘ РЎРѓР С•РЎвЂ¦РЎР‚Р В°Р Р…Р ВµР Р…РЎвЂ№",
              bool(secf) and secf.get("width") == "fill" and secf.get("height") == 200, str(secf))

        # 2) Р Р…Р Вµ-responsive Р В±Р В»Р С•Р С” РЎРѓ card-Р Т‘Р ВµРЎвЂљРЎРЉР СР С‘ РІР‚вЂќ Р Т‘Р В»РЎРЏ Р С—РЎР‚Р В°Р Р†Р С•Р С” Р Р…Р В° tablet/mobile
        pg.evaluate("""(id) => {
            const ir = { version: '1.0', meta: { name: 'grid' },
                tokens: { color: { primary: '#111111', background: '#ffffff' } },
                tree: [{ id: 'grid', type: 'feature-grid', sourceKey: 'g',
                    children: [
                        { type: 'card', title: 'C1', sourceKey: 'g/c:1', frame: { width: 200, height: 100 } },
                        { type: 'card', title: 'C2', sourceKey: 'g/c:2', frame: { width: 200, height: 100 } },
                    ] }] };
            window.GraphDev.patchData(id, { ir });
        }""", e2)
        pg.evaluate("(id) => window.GraphDev.run(id)", page_id)
        pg.wait_for_timeout(300)

        # 3) РЎР‚Р ВµР Т‘Р В°Р С”РЎвЂљР С•РЎР‚ Р С•РЎвЂљР С”РЎР‚РЎвЂ№Р Р†Р В°Р ВµРЎвЂљРЎРѓРЎРЏ Р Р…Р В° Р Р†РЎРЉРЎР‹Р С—Р С•РЎР‚РЎвЂљР Вµ Р С‘Р В· Р С–РЎР‚Р В°РЎвЂћР В° (Page РЎРѓР ВµР в„–РЎвЂЎР В°РЎРѓ Р Р…Р В° mobile);
        #    Р В°РЎР‚РЎвЂљР В±Р С•РЎР‚Р Т‘ Р СР В°РЎвЂљР ВµРЎР‚Р С‘Р В°Р В»Р С‘Р В·Р С•Р Р†Р В°Р Р…Р Р…Р С•Р С–Р С• Р Р†Р В°РЎР‚Р С‘Р В°Р Р…РЎвЂљР В° Р Р…Р Вµ РЎРѓР В¶Р В°РЎвЂљ fitPreview (zoom РІР‚вЂќ Р Т‘Р ВµР В»Р С• РЎР‚Р ВµР Т‘Р В°Р С”РЎвЂљР С•РЎР‚Р В°)
        pg.click(f'.svelte-flow__node[data-id="{edit3}"] .f-open-editor')
        pg.wait_for_selector('.dna-editor .fe-canvas-inner [class^="ir-"]')
        pg.wait_for_timeout(500)
        open_st = pg.evaluate("""(() => {
            const art = document.querySelector('.dna-editor .fe-canvas-inner div[class^="ir-"]');
            const active = document.querySelector('.dna-editor [data-viewport].active');
            return { vp: active && active.dataset.viewport, w: art.offsetWidth,
                     transform: art.style.transform || "" };
        })()""")
        check("РЎР‚Р ВµР Т‘Р В°Р С”РЎвЂљР С•РЎР‚ Р С•РЎвЂљР С”РЎР‚РЎвЂ№Р В»РЎРѓРЎРЏ Р Р…Р В° Р Р†РЎРЉРЎР‹Р С—Р С•РЎР‚РЎвЂљР Вµ Р С‘Р В· Р С–РЎР‚Р В°РЎвЂћР В° (mobile)", open_st["vp"] == "mobile", str(open_st))
        check("Р В°РЎР‚РЎвЂљР В±Р С•РЎР‚Р Т‘ mobile 390 Р С‘ Р Р…Р Вµ РЎРѓР В¶Р В°РЎвЂљ fitPreview",
              open_st["w"] == 390 and open_st["transform"] == "", str(open_st))

        # 4) Р С—РЎР‚Р В°Р Р†Р С”Р В° Р Р…Р В° tablet Р С—Р С‘РЎв‚¬Р ВµРЎвЂљ override Р Р† canonical, desktop Р Р…Р Вµ РЎвЂљРЎР‚Р С•Р С–Р В°Р ВµР С;
        #    undo Р Р†Р С•Р В·Р Р†РЎР‚Р В°РЎвЂ°Р В°Р ВµРЎвЂљ canonical; save Р С—РЎР‚Р С•Р С”Р С‘Р Т‘РЎвЂ№Р Р†Р В°Р ВµРЎвЂљ meta.activeViewport Р Р†Р Р…Р С‘Р В·
        pg.click('.dna-editor [data-viewport="tablet"]')
        pg.wait_for_timeout(400)
        sec_idx = pg.evaluate(f"""(() => {{
            const data = window.GraphDev.node({edit3}).data;
            const ir = data._editorDraft?.ir || data.ir;
            return ir.tree.findIndex(s => (s.id || '').startsWith('grid'));
        }})()""")
        card_pt = pg.evaluate(f"""(() => {{
            const el = document.querySelector('.dna-editor [data-ir-sec="{sec_idx}"] [data-ir-path="children.0"]');
            const r = el.getBoundingClientRect();
            return {{ x: r.left + r.width / 2, y: r.top + r.height / 2 }};
        }})()""")
        pg.mouse.click(card_pt["x"], card_pt["y"])
        pg.wait_for_timeout(250)
        pg.mouse.move(card_pt["x"], card_pt["y"])
        pg.mouse.down()
        pg.mouse.move(card_pt["x"] + 30, card_pt["y"], steps=6)
        pg.mouse.up()
        pg.wait_for_timeout(400)
        ov = pg.evaluate(f"""(() => {{
            const data = window.GraphDev.node({edit3}).data;
            const ir = data._editorDraft?.ir || data.ir;
            const card = ir.tree[{sec_idx}].children[0];
            return {{ tab: (card.responsive || {{}}).tablet || null, base: card.frame,
                      rootW: ir.frame.width }};
        }})()""")
        check("tablet: override РЎРѓР С•Р В·Р Т‘Р В°Р Р… Р Р…Р В° Р Р…Р Вµ-responsive Р В±Р В»Р С•Р С”Р Вµ (absolute Р Р† responsive.tablet)",
              bool(ov["tab"]) and ov["tab"].get("frame", {}).get("absolute") is True, str(ov))
        check("tablet: desktop-РЎвЂћРЎР‚Р ВµР в„–Р С Р С‘ Р С”Р С•РЎР‚Р ВµР Р…РЎРЉ Р Р…Р Вµ РЎвЂљРЎР‚Р С•Р Р…РЎС“РЎвЂљРЎвЂ№",
              "absolute" not in ov["base"] and "x" not in ov["base"] and ov["rootW"] == 1440, str(ov))

        pg.evaluate("document.activeElement && document.activeElement.blur()")
        pg.keyboard.press("Control+z")
        pg.wait_for_timeout(300)
        und = pg.evaluate(f"""(() => {{
            const data = window.GraphDev.node({edit3}).data;
            const ir = data._editorDraft?.ir || data.ir;
            const card = ir.tree[{sec_idx}].children[0];
            return {{ resp: card.responsive || null, rootW: ir.frame.width }};
        }})()""")
        check("undo: canonical Р В±Р ВµР В· tablet-override, Р С”Р С•РЎР‚Р ВµР Р…РЎРЉ 1440",
              (not und["resp"] or "tablet" not in und["resp"]) and und["rootW"] == 1440, str(und))

        pg.click('.dna-editor [data-act="save"]')
        pg.wait_for_timeout(400)
        fin = pg.evaluate(f"window.GraphDev.node({edit3}).data.ir")
        check("save: meta.activeViewport=tablet Р С—РЎР‚Р С•РЎвЂљРЎвЂР С” Р Р† Р Р…Р С•Р Т‘РЎС“",
              (fin.get("meta") or {}).get("activeViewport") == "tablet", str(fin.get("meta")))
        check("save: Р С”Р С•РЎР‚Р ВµР Р…РЎРЉ Р С•РЎРѓРЎвЂљР В°Р В»РЎРѓРЎРЏ Р С”Р В°Р Р…Р С•Р Р…Р С‘РЎвЂЎР ВµРЎРѓР С”Р С‘Р С (1440, auto)",
              fin["frame"].get("width") == 1440 and fin["frame"].get("layout") == "auto",
              str(fin["frame"]))

        # 5) Node preview obeys fitPreview: shrink only when the container is narrower than the design.
        pv = pg.evaluate(f"""(() => {{
            const inner = document.querySelector('.svelte-flow__node[data-id="{page_id}"] .ir-preview-inner');
            const art = inner.querySelector('div[class^="ir-"]');
            const r = art.getBoundingClientRect();
            return {{ innerW: inner.clientWidth, designW: Number(art.dataset.designWidth),
                      rectW: Math.round(r.width) }};
        }})()""")
        check("mobile Page preview uses fitPreview without upscaling",
              pv["designW"] == 390 and
              abs(pv["rectW"] - min(pv["designW"], pv["innerW"])) <= 2,
              str(pv))

        # 6) РЎР‚Р ВµР Т‘Р В°Р С”РЎвЂљР С•РЎР‚: Р С”Р Р…Р С•Р С—Р С”Р С‘ D/T/M РЎР‚Р ВµР В°Р В»РЎРЉР Р…Р С• Р СР ВµР Р…РЎРЏРЎР‹РЎвЂљ Р СР В°РЎвЂљР ВµРЎР‚Р С‘Р В°Р В»Р С‘Р В·Р В°РЎвЂ Р С‘РЎР‹ (1440/768/390)
        pg.click(f'.svelte-flow__node[data-id="{edit3}"] .f-open-editor')
        pg.wait_for_selector('.dna-editor .fe-canvas-inner [class^="ir-"]')
        pg.wait_for_timeout(500)
        open_vp = pg.evaluate("""(() => {
            const b = document.querySelector('.dna-editor [data-viewport].active');
            return b && b.dataset.viewport; })()""")
        check("РЎР‚Р ВµР Т‘Р В°Р С”РЎвЂљР С•РЎР‚ Р С•РЎвЂљР С”РЎР‚РЎвЂ№Р В»РЎРѓРЎРЏ Р Р…Р В° РЎРѓР С•РЎвЂ¦РЎР‚Р В°Р Р…РЎвЂР Р…Р Р…Р С•Р С Р Р†РЎРЉРЎР‹Р С—Р С•РЎР‚РЎвЂљР Вµ (tablet)", open_vp == "tablet", str(open_vp))
        widths = {}
        for vp in ("desktop", "tablet", "mobile"):
            pg.click(f'.dna-editor [data-viewport="{vp}"]')
            pg.wait_for_timeout(400)
            widths[vp] = pg.evaluate(
                "document.querySelector(\".dna-editor .fe-canvas-inner div[class^='ir-']\").offsetWidth")
        check("РЎР‚Р ВµР Т‘Р В°Р С”РЎвЂљР С•РЎР‚: D/T/M Р СР ВµР Р…РЎРЏРЎР‹РЎвЂљ Р В°РЎР‚РЎвЂљР В±Р С•РЎР‚Р Т‘ (1440/768/390)",
              widths == {"desktop": 1440, "tablet": 768, "mobile": 390}, str(widths))
        pg.click('.dna-editor [data-act="close"]')
        # защита черновика: редактор с правками спрашивает — закрываем без сохранения
        try:
            pg.wait_for_selector('[data-act="close-discard"]', timeout=1000).click()
        except Exception:
            pass

        browser.close()

    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL PAGE-NODE CHECKS PASSED")


if __name__ == "__main__":
    main()
