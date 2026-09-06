"""Opt-in browser/player/export verification using the saved live GPT scenario."""
from __future__ import annotations
import copy
import argparse
import json
import subprocess
from pathlib import Path
from PIL import Image, ImageChops, ImageStat
from playwright.sync_api import sync_playwright
import imageio_ffmpeg
from timeline_render import render_timeline_video, _builtin_inter_faces, _READINESS_JS, RENDER_DOCUMENT_URL, RENDER_DOCUMENT_HTML
from timeline_assets import install_render_asset_guard

OUT = Path(__file__).resolve().parents[1] / "results/video-stage2"

def main():
    global OUT
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=OUT/'codex.json')
    parser.add_argument('--output',type=Path,default=OUT)
    args=parser.parse_args(); OUT=args.output; OUT.mkdir(parents=True,exist_ok=True)
    original = json.loads(args.source.read_text(encoding="utf-8"))["timeline"]
    doc = copy.deepcopy(original)
    faces, assets = _builtin_inter_faces()
    for page in doc["story"]["pages"]:
        page["ir"].setdefault("meta", {})["fontFaces"] = faces
    fps = doc["composition"]["fps"]
    schedule = []; clock = 0
    for action in doc["story"]["actions"]:
        schedule.append({**action, "start":clock, "end":clock + action["duration"]})
        clock += action["duration"]
    samples = {"start":0, "filled":next(a["start"] for a in schedule if a["type"] == "scroll"), "click":next(a["start"] + a["duration"] * .8 for a in schedule if a["type"] == "click" and a["target"] == "s0.children.9"), "result":doc["composition"]["duration"] - 500}
    transition=next(a for a in schedule if a["type"] == "navigate")
    samples["transition"] = transition["start"] + transition["duration"] * .5
    samples = {name: int(t * fps / 1000) for name, t in samples.items()}
    blocked = []; errors = []; states = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width":960,"height":640},device_scale_factor=1)
        install_render_asset_guard(context, assets, blocked, RENDER_DOCUMENT_URL, RENDER_DOCUMENT_HTML)
        page = context.new_page(); page.on("pageerror",lambda error:errors.append(str(error)))
        page.goto(RENDER_DOCUMENT_URL)
        page.add_script_tag(path=str(Path(__file__).parent / "static/flow/engine.js"))
        page.evaluate("doc => { window.player = new VideoStoryPlayer(document.querySelector('#host'),doc,true); window.events=[]; for(const name of ['click','submit','input','change']) document.addEventListener(name,()=>events.push(name)); }",doc)
        readiness = page.evaluate(_READINESS_JS)
        assert not readiness["errors"],readiness
        for name,index in samples.items():
            states[name] = page.evaluate("t => player.seek(t)",index*1000/fps)
            page.screenshot(path=str(OUT / (name+".png")))
        # Both fixture pages are white here; a dissolve must not dim their shared background.
        assert min(Image.open(OUT/'transition.png').convert('RGB').getpixel((940,620))) > 250
        # Transition boundaries are continuous; seeking backwards must clear page transforms.
        if transition.get('transition') != 'cut':
            page.evaluate("t => player.seek(t)",transition['start']+1)
            assert float(page.locator('[data-story-page="ir"]').evaluate("el=>el.style.opacity")) > .99
            page.evaluate("t => player.seek(t)",transition['end']-1)
            assert float(page.locator('[data-story-page="page2"]').evaluate("el=>el.style.opacity")) > .99
            page.evaluate("player.seek(0)")
            assert page.locator('[data-story-page="page2"]').evaluate("el=>el.style.transform") == 'none'
        final = page.evaluate("t => player.seek(t)",doc["composition"]["duration"])
        assert final["pageId"] == "page2"
        assert list(final["typed"].values()) == ["Диван","15000","Москва"],final
        assert states["click"]["pageId"] == "ir" and states["click"]["scrolls"]["ir"] > 0
        assert 0 < states["click"]["cursor"]["y"] < 640,states["click"]
        page.evaluate("t=>player.seek(t)",samples['click']*1000/fps)
        button_box=page.locator('[data-story-page=ir] [data-ir-path="children.9"] a').bounding_box()
        assert abs(states['click']['cursor']['x'] - button_box['x'] - button_box['width']/2) < .01
        first = next(a for a in schedule if a["type"] == "type")
        partial = page.evaluate("t => player.seek(t)",first["start"] + first["duration"]*.65)
        assert 0 < len(partial["typed"]["ir/"+first["target"]]) < len(first["text"])
        reset = page.evaluate("player.seek(0)")
        assert not reset["typed"] and not reset["scrolls"] and reset["pageId"] == "ir"
        assert page.evaluate("t => player.seek(t)",doc["composition"]["duration"]) == final
        # A child layer must animate independently and the cursor must follow it.
        button = next(layer for layer in doc["layers"] if layer["ref"] == "publish")
        changed = copy.deepcopy(doc)
        next(layer for layer in changed["layers"] if layer["id"] == button["id"])["transform"]["properties"]["x"] = {"keyframes":[{"t":0,"value":0},{"t":1000,"value":80}]}
        page.evaluate("doc => { player.destroy(); window.player=new VideoStoryPlayer(document.querySelector('#host'),doc,true); }",changed)
        geometry = "() => {const el=document.querySelector('[data-story-page=ir] [data-ir-path=\"children.9\"]'); return {x:el.getBoundingClientRect().x, parent:el.closest('[data-ir-sec]').getBoundingClientRect().x};}"
        page.evaluate("player.seek(0)"); before=page.evaluate(geometry)
        page.evaluate("player.seek(1000)"); after=page.evaluate(geometry)
        assert abs(after['x'] - before['x'] - 80) < .01,(before,after)
        assert after['parent'] == before['parent']
        # Neutral transforms retain source opacity on a nested component.
        changed['story']['pages'][0]['ir']['tree'][0]['children'][9].setdefault('style',{})['opacity']=.65
        page.evaluate("doc => {player.destroy(); window.player=new VideoStoryPlayer(document.querySelector('#host'),doc,true);}",changed)
        opacity=page.locator('[data-story-page=ir] [data-ir-path="children.9"]').evaluate_all("els=>els.reduce((v,el)=>v*Number(getComputedStyle(el).opacity),1)")
        assert abs(float(opacity)-.65) < .001,opacity
        assert page.evaluate("events") == []
        assert not errors and not blocked,(errors,blocked)
        browser.close()
    report = render_timeline_video(original,original["story"]["pages"][0]["ir"],OUT / "announcement-walkthrough.mp4",data_dir=OUT / "private-data")
    comparisons={}
    for name,index in samples.items():
        output = OUT / (name+"-mp4.png")
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-i',str(OUT/'announcement-walkthrough.mp4'),'-vf',f"select=eq(n\\,{index})",'-frames:v','1','-y',str(output)],check=True,capture_output=True)
        delta = sum(ImageStat.Stat(ImageChops.difference(Image.open(OUT/(name+'.png')).convert('RGB'),Image.open(output).convert('RGB'))).mean)/3
        comparisons[name]=round(delta,4)
        assert delta < 2.0,(name,delta)
    report.update({"states":states,"pixelMeanError":comparisons,"browserErrors":errors})
    (OUT/'render-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True),flush=True)

if __name__ == '__main__': main()
