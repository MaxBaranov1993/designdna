"""Inspect/finalize the existing owned QA canvas; never replaces project data."""
import argparse
import json
import os
from playwright.sync_api import sync_playwright
from ui_source_sites_qa import output, TITLE, OUT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--finalize', action='store_true')
    parser.add_argument('--label', default='checkpoint')
    parser.add_argument('--compare', help='Compare saved canonical data against an earlier QA checkpoint label')
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(os.environ.get('DESIGNDNA_CDP', 'http://127.0.0.1:9345'))
        page = next(pg for ctx in browser.contexts for pg in ctx.pages if pg.url.startswith('file:'))
        page.wait_for_function('window.GraphDev && window.__flowStore && window.designDNA')
        result = page.evaluate('''async ({title,finalize}) => {
          const g=window.GraphDev, s=window.__flowStore.getState();
          if(!g.pages().find(p=>p.active && p.name===title) || s.nodes.length!==4 || s.edges.length!==2)
            throw Error('Unexpected QA canvas');
          const busy=Object.values(s.busy).some(Boolean) || s.nodes.some(n=>n.data.busyAction);
          const editors=[...document.querySelectorAll('.dna-editor,[data-ds-editor]')].filter(e=>e.getClientRects().length).length;
          if(finalize) {
            if(busy || editors) throw Error('Finish active operations/editors first');
            for(const n of s.nodes) {
              if(!['slsbmb','rsale'].includes(n.data.qaSite)) throw Error('Unexpected node ownership');
              if(n.type==='sourceimport') g.patchData(Number(n.id),{aiProvider:n.data.qaSite==='slsbmb'?'codex':'claude'});
              else if(n.type==='designsystem') g.patchData(Number(n.id),{aiProvider:'inherit',autoPublish:false});
              else throw Error('Unexpected node type');
            }
          }
          const current=window.__flowStore.getState();
          return {busy,editors,pages:g.pages(),edges:current.edges,engine:await window.designDNA.engine.status(),
            nodes:current.nodes.map(n=>({id:n.id,type:n.type,site:n.data.qaSite,provider:n.data.aiProvider,
              autoPublish:n.data.autoPublish,systemId:n.data.systemId,revision:n.data.revision,
              contentHash:n.data.contentHash,blocks:n.data.blocks?.length,pipeline:n.data.pipelineStatus,
              hasEditorDraft:!!n.data._editorDraft}))};
        }''', {'title': TITLE, 'finalize': args.finalize})
        if args.finalize:
            page.wait_for_timeout(2500)
        saved = page.evaluate('''async()=>{
          const r=await fetch('/api/project/load',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
          if(!r.ok) throw Error('Project persistence read failed'); return r.json();
        }''')
        result['savedRevision'] = saved.get('revision')
        result['savedProject'] = saved.get('project')
        if args.compare:
            previous = json.loads((OUT / (args.compare + '.json')).read_text(encoding='utf-8'))
            def protected(project):
                pages = []
                for item in project.get('pages', []):
                    graph = item.get('graph', {})
                    nodes = []
                    for node in graph.get('nodes', []):
                        data = node.get('data', {})
                        keys = ('blocks','sourceArtifact','tokens','url','importedUrl') if node.get('type') == 'sourceimport' else ('systemId','revision','contentHash','autoPublish')
                        nodes.append({'id':node['id'],'type':node['type'],'data':{k:data.get(k) for k in keys}})
                    pages.append({'id':item['id'],'name':item['name'],'nodes':nodes,'edges':graph.get('edges')})
                return pages
            result['canonicalPreservation'] = protected(previous['savedProject']) == protected(result['savedProject'])
            # The previous live snapshot records the requested settings. Its DB
            # read can precede a debounced save; do not use that older provider
            # value as the intended setting. Verify both live AND saved values.
            expected = {str(n['id']):n['provider'] for n in previous['nodes']}
            live = {str(n['id']):n['provider'] for n in result['nodes']}
            saved_nodes = next(p for p in result['savedProject']['pages'] if p['name']==TITLE)['graph']['nodes']
            stored = {str(n['id']):n['data'].get('aiProvider') for n in saved_nodes}
            result['providerSettingsRestored'] = expected == live == stored
            result['restartPreservation'] = result['canonicalPreservation'] and result['providerSettingsRestored']
        output(args.label, result)
        print(json.dumps({k:v for k,v in result.items() if k!='savedProject'}))
        if args.compare and not result['restartPreservation']:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
