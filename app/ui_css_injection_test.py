"""CSS-инъекции из IR: токены/шрифты/align санятся (контент от LLM недоверенный).
Ретаргетинг после снятия legacy /nodes: edit-нода живёт в новом React Flow UI на /flow.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_css_injection_test.py
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

EVIL = "red !important; } body { background: red !important; } .x { content: '"

IR = {
    "version": "1.0",
    "meta": {"name": "css-injection", "description": "тест", "styleTags": ["test"]},
    "frame": {"width": 960, "height": 600},
    "tokens": {
        "mode": "light",
        "color": {"primary": f"#0E7A5F; {EVIL}", "secondary": "#134E48",
                  "accent": "#E85D26", "background": "#FFFFFF", "surface": "#F6F7F8",
                  "text": "#17201D", "textMuted": f"#5D6B66'; {EVIL}", "border": "#E2E7E5"},
        "font": {"display": {"family": "Manrope', 'x'; @import url('http://evil.example/css')",
                             "weight": "800; } body { background: red }"},
                 "body": {"family": "Inter", "weight": 400}, "scale": "default"},
        "radius": {"card": "lg", "button": "full", "input": "md"},
        "spacing": {"section": "md", "container": "default"},
        "shadow": "sm",
    },
    "tree": [
        {
            "id": "inj-sec", "type": "feature-grid",
            "frame": {"width": "fill", "padding": 40},
            "props": {"heading": "Инъекции", "subheading": "не проходят"},
            "children": [
                {"type": "heading", "text": "Злой align", "level": 2,
                 "align": f"center; background:url('http://evil.example/x')"},
                {"type": "text", "text": "Ещё злой", "align": 'left" onmouseover="alert(1)'},
                {"type": "text", "text": "Добрый", "align": "center"},
            ],
        },
    ],
}


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1700, "height": 1000})
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
        pg.wait_for_selector(".react-flow__pane")
        pg.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        pg.evaluate("window.GraphDev.add('edit', 60, 40)")
        nid = int(pg.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id"))
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, IR)
        pg.wait_for_timeout(700)

        # 1) в <style> нет инъекций из токенов
        leaked = pg.evaluate("""(() => {
            const bad = ["background: red", "@import", "evil.example"];
            const styles = Array.from(document.querySelectorAll("style")).map(s => s.textContent).join("\\n");
            return bad.filter(b => styles.includes(b));
        })()""")
        check("токены не ломают <style>", not leaked, str(leaked))

        # 2) битый цвет отброшен к дефолту, валидные работают
        varz = pg.evaluate("""(() => {
            const el = document.querySelector(".n-edit .ir-preview-inner div[class^='ir-']");
            const cs = getComputedStyle(el);
            return { primary: cs.getPropertyValue("--c-primary").trim(),
                     muted: cs.getPropertyValue("--c-muted").trim() };
        })()""")
        check("битый primary → дефолт #5B5BD6", varz["primary"] == "#5B5BD6", str(varz))
        check("битый textMuted → дефолт #666666", varz["muted"] == "#666666", str(varz))

        # 3) шрифт: кавычки/инъекции вырезаны из CSS и из URL Google Fonts
        font = pg.evaluate("""(() => {
            const el = document.querySelector(".n-edit .ir-preview-inner div[class^='ir-']");
            const fam = getComputedStyle(el).getPropertyValue("--font-display").trim();
            const link = document.getElementById("ir-fonts");
            return { fam, href: link ? link.href : "" };
        })()""")
        # кавычки — только две обрамляющие от cssVars; внутри имени — ни одной
        body = font["fam"].replace("'", "", 2)
        check("font-family без кавычек/инъекций",
              font["fam"].count("'") == 2 and "@" not in body and ";" not in body,
              str(font))
        check("Google Fonts URL без инъекций",
              "'" not in font["href"] and "evil.example" not in font["href"]
              and " " not in font["href"].split("?")[1],
              font["href"])

        # 4) align: злой отброшен, добрый применён (align стоит на внутреннем h/p,
        #    data-ir-path может быть на span-обёртке)
        al = pg.evaluate("""(() => {
            const out = [];
            for (let i = 0; i < 3; i++) {
                const w = document.querySelector('.n-edit [data-ir-path="children.' + i + '"]');
                const h = (w && (w.matches("h1,h2,h3,h4,p") ? w : w.querySelector("h1,h2,h3,h4,p"))) || w;
                out.push({ attr: (h && h.getAttribute("style")) || "", ta: h ? getComputedStyle(h).textAlign : "" });
            }
            return out;
        })()""")
        check("злой align (heading) отброшен",
              "background" not in al[0]["attr"] and "url(" not in al[0]["attr"], str(al[0]))
        check("злой align (text) отброшен",
              "onmouseover" not in al[1]["attr"] and '"' not in al[1]["attr"], str(al[1]))
        check("валидный align применён", al[2]["ta"] == "center", str(al[2]))

        browser.close()

    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL CSS-INJECTION CHECKS PASSED")


if __name__ == "__main__":
    main()
