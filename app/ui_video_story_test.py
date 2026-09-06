"""Isolated browser test; AI is stubbed here, live accounts checked separately."""
import json
import os
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from video_story import direct_story
from ir.timeline import build
from video_story_fixtures import pages_fixture, plan_fixture, PROMPT

BASE = os.environ.get("DESIGNAI_UI_BASE", "http://127.0.0.1:8437")
OUT = Path(__file__).resolve().parents[1] / "results/video-stage2"

def main():
    saved=None; errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(viewport={"width":1600,"height":1000})
        page.on('pageerror',lambda error:errors.append(str(error)))
        def save(route):
            nonlocal saved
            saved=route.request.post_data_json['project'];route.fulfill(json={'ok':True,'revision':'story-test'})
        def assist(route):
            body=route.request.post_data_json
            assert body['provider'] in ('codex','claude') and body['require_llm']
            plan=plan_fixture() if not body['timeline']['story']['actions'] else {'summary':'Пауза дольше','edits':[{'op':'update','id':'end','changes':{'duration':2000}}]}
            with patch('video_story.llm.chat',return_value=json.dumps(plan)):
                timeline,changes,meta=direct_story(body['timeline'],body['prompt'],body['provider'],'medium')
            route.fulfill(json={'timeline':timeline,'changeSet':changes,'preview':True,**meta})
        page.route('**/api/project/load',lambda route:route.fulfill(json={'project':saved,'revision':'story-test'}))
        page.route('**/api/project/save',save)
        page.route('**/api/timeline/assist',assist)
        page.goto(BASE+'/flow');page.wait_for_function('window.GraphDev')
        page.evaluate('GraphDev.clear()')
        ids=page.evaluate("() => [GraphDev.add('page',80,100).id,GraphDev.add('page',80,430).id,GraphDev.add('timeline',600,150).id]")
        node=page.locator(f'.svelte-flow__node[data-id="{ids[2]}"]')
        page.evaluate("v => {GraphDev.patchData(v.ids[0],{ir:v.pages[0].ir});GraphDev.patchData(v.ids[1],{ir:v.pages[1].ir});GraphDev.patchData(v.ids[2],{settings:{width:960,height:640,fps:12,duration:8000}});GraphDev.connect(v.ids[0],'ir',v.ids[2],'ir');GraphDev.fit();}",{'ids':ids,'pages':pages_fixture()})
        node.get_by_role('button',name='+ Страница',exact=True).click()
        page.evaluate("ids=>GraphDev.connect(ids[1],'ir',ids[2],'page2')",ids)
        node.get_by_label('Название страницы 1').fill('Форма');node.get_by_label('Название страницы 1').press('Tab')
        node.get_by_label('Название страницы 2').fill('Готово');node.get_by_label('Название страницы 2').press('Tab')
        node.get_by_label('Промпт видео').fill(PROMPT)
        page.screenshot(path=str(OUT/'two-page-node.png'))
        node.get_by_role('button',name='Создать по промпту').click()
        page.locator('[data-act="ai-preview"]').wait_for()
        expect(page.locator('[data-act="story-action"]')).to_have_count(8)
        page.locator('[data-act="ai-apply"]').click()
        page.wait_for_function('id=>GraphDev.node(id).data.revisions?.length===2',arg=ids[2])
        if os.environ.get('TEST_STORY_MOTION'):
            before_motion=page.evaluate('id=>GraphDev.node(id).data.timeline',ids[2])
            page.locator('[data-act="story-soften"]').click()
            page.wait_for_function('id=>GraphDev.node(id).data.timeline.composition.fps===60',arg=ids[2])
            softened=page.evaluate('id=>GraphDev.node(id).data.timeline',ids[2])
            assert softened['story']['actions'][6]['transition']=='motion'
            assert softened['story']['actions'][4]['duration']>=1400
            page.locator('[data-act="story-action"]').nth(4).click()
            page.get_by_label('Плавность движения').select_option('linear')
            page.wait_for_function('id=>GraphDev.node(id).data.timeline.story.actions[4].easing==="linear"',arg=ids[2])
            page.locator('.tlw-root [data-act="undo"]').click()
            page.wait_for_function('id=>GraphDev.node(id).data.timeline.story.actions[4].easing==="soft"',arg=ids[2])
            page.locator('.tlw-root [data-act="undo"]').click()
            page.wait_for_function('v=>JSON.stringify(GraphDev.node(v.id).data.timeline)===JSON.stringify(v.before)',arg={'id':ids[2],'before':before_motion})
        expect(page.locator('[data-act="export-css"]')).to_be_disabled()
        page.locator('[data-act="story-action"]').nth(4).click()
        expect(page.locator('[data-story-page="ir"] [data-ir-path="children.3"] input')).to_have_value('Диван')
        page.screenshot(path=str(OUT/'walkthrough-editor.png'))
        page.locator('[data-act="story-action"]').nth(1).click()
        page.get_by_label('Текст для ввода').fill('Кресло');page.get_by_label('Текст для ввода').press('Tab')
        page.wait_for_function('id=>GraphDev.node(id).data.timeline.story.actions[1].text==="Кресло"',arg=ids[2])
        page.get_by_label('Длительность действия').fill('2.5');page.get_by_label('Длительность действия').press('Tab')
        page.wait_for_function('id=>GraphDev.node(id).data.timeline.story.actions[1].duration===2500',arg=ids[2])
        manual=page.evaluate('id=>GraphDev.node(id).data.timeline',ids[2])
        page.locator('[data-act="ai-prompt"]').fill('Увеличь последнюю паузу до двух секунд')
        page.locator('[data-act="ai-run"]').click();page.locator('[data-act="ai-apply"]').click()
        page.wait_for_function('id=>GraphDev.node(id).data.revisions?.length===4',arg=ids[2])
        data=page.evaluate('id=>GraphDev.node(id).data',ids[2])
        assert data['timeline']['story']['actions'][1]['text']=='Кресло'
        assert data['timeline']['story']['actions'][1]['duration']==2500
        assert data['revisions'][2]['timeline']==manual
        page.locator('[data-act="story-action"]').last.click()
        expect(page.locator('[data-story-page="page2"]')).to_have_css('opacity','1')
        page.screenshot(path=str(OUT/'walkthrough-result.png'))
        page.locator('.tlw-root [data-act="close"]').click();page.wait_for_timeout(1800)
        assert saved
        page.evaluate('localStorage.clear()');page.reload()
        page.wait_for_function('id=>window.GraphDev?.node(id)?.data?.revisions?.length===4',arg=ids[2])
        reloaded=page.evaluate('id=>GraphDev.node(id).data',ids[2])
        assert reloaded['timeline']==data['timeline'] and reloaded['sourcePages']==data['sourcePages']
        assert reloaded['pageNames']=={'ir':'Форма','page2':'Готово'}
        legacy=build(pages_fixture()[0]['ir'],{'duration':8000})
        legacy['layers'][0]['transform']['properties']['x']={'keyframes':[{'t':0,'value':23}]}
        old_id=page.evaluate("v=>{ const n=GraphDev.add('timeline',100,100);GraphDev.patchData(n.id,{ir:v.ir,timeline:v.timeline});GraphDev.fit();return n.id;}",{'ir':pages_fixture()[0]['ir'],'timeline':legacy})
        page.locator(f'.svelte-flow__node[data-id="{old_id}"]').get_by_role('button',name='Открыть редактор').click()
        expect(page.get_by_text('Опишите действия в промпте или добавьте их вручную.',exact=True)).to_be_visible()
        upgraded=page.evaluate('id=>GraphDev.node(id).data.timeline',old_id)
        assert upgraded['layers']==legacy['layers'] and len(upgraded['story']['pages'])==1
        page.locator('.tlw-root [data-act="close"]').click()
        assert not errors,errors
        browser.close()
    print('PASS: multiple page inputs / prompt / typing / scroll / transition / manual text and duration / AI preservation / history / reload / no browser errors',flush=True)

if __name__=='__main__': main()
