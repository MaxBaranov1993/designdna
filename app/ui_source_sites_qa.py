"""Live, opt-in desktop QA. Uses only the explicitly selected isolated profile.

No fixture interception and no credentials are read or written. Run captures and
provider passes separately so a failed stage remains inspectable/retryable.
"""
import argparse
import json
import os
import shutil
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "source-sites-qa"
SITES = {"slsbmb": "https://slsbmb.com/", "rsale": "https://rsale.net/"}
TITLE = "Source QA — SLSBMB + RSALE"


def output(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    target=OUT / f"{name}.json"
    if target.exists():
        shutil.copy2(target, OUT / f"{name}.previous-{time.time_ns()}.json")
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def api(page, path, body=None):
    return page.evaluate("""async ({path,body}) => {
      const r = await fetch(path,body==null ? undefined : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const data=await r.json(); if(!r.ok || (data.error && !data.jobId)) throw new Error(JSON.stringify(data)); return data;
    }""", {"path": path, "body": body})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["init", "capture", "status", "build", "import", "shot", "diagnose", "probe", "ai", "events"])
    parser.add_argument("--site", choices=list(SITES), default="slsbmb")
    parser.add_argument("--provider", choices=["codex", "claude"], default="codex")
    parser.add_argument("--operation", choices=['organize','style-review','master-review'], default='style-review')
    parser.add_argument("--label", default="", help="Separate artifact label; never overwrite a baseline capture")
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(os.environ.get("DESIGNDNA_CDP", "http://127.0.0.1:9345"))
        page = next(pg for ctx in browser.contexts for pg in ctx.pages if pg.url.startswith("file:"))
        page.wait_for_function("window.GraphDev && window.__flowStore && window.designDNA")
        if args.action == "init":
            ids = page.evaluate("""title => {
              const g=window.GraphDev; const old=g.pages().find(p=>p.name===title);
              if(old) { g.switchPage(old.id); return g.state(); }
              g.createPage(title);
              for (const [i,site] of ['slsbmb','rsale'].entries()) {
                const source=g.add('sourceimport',60+i*850,60).id;
                const ds=g.add('designsystem',430+i*850,60).id;
                g.patchData(source,{url:`https://${site==='slsbmb'?'slsbmb.com':'rsale.net'}/`,mine:true,authenticatedSession:false,aiProvider:i?'claude':'codex',aiEffort:'medium',aiRefine:true,qaSite:site});
                g.patchData(ds,{name:`${site.toUpperCase()} UI Kit`,autoPublish:false,aiProvider:'inherit',qaSite:site});
                g.connect(source,'artifact',ds,'artifact');
              }
              return g.state();
            }""", TITLE)
            output("canvas", ids)
            print(json.dumps(ids))
            return
        ids = page.evaluate("""site => Object.fromEntries(window.__flowStore.getState().nodes.filter(n=>n.data.qaSite===site).map(n=>[n.type,Number(n.id)]))""", args.site)
        if args.action == "capture":
            started = time.time()
            job = api(page, "/api/block-parse", {"url": SITES[args.site], "asyncJob": True,
                "fullResolutionEvidence": True, "viewports": [{"name": n, "width": w, "height": h}
                    for n,w,h in [("desktop",1440,900),("tablet",768,1024),("mobile",390,844)]]})
            last = None
            while job.get("status") in ("queued", "running"):
                if time.time()-started > 900:
                    raise TimeoutError("Capture exceeded 15 minutes")
                if job.get("stage") != last:
                    last=job.get("stage")
                    print(json.dumps({"site":args.site,"stage":last,"seconds":round(time.time()-started)}), flush=True)
                page.wait_for_timeout(2000)
                job=api(page,"/api/block-parse/job/"+job["jobId"])
            if job.get("status")=="error":
                output(args.site+"-capture-error",job)
                raise RuntimeError(job.get("error"))
            result=job.get("result",job)
            output(args.site+"-capture"+(('-'+args.label) if args.label else ''),result)
            page.evaluate("""({id,result,url})=>{const s=window.__flowStore.getState();s.setNodeData(id,{blocks:result.blocks.map(b=>({...b,lit:false})),tokens:result.tokens,sourceArtifact:result.sourceArtifact,url,importedUrl:url});s.propagate(id)}""", {"id":ids["sourceimport"],"result":result,"url":SITES[args.site]})
            print(json.dumps({"site":args.site,"blocks":len(result.get("blocks",[])),"seconds":round(time.time()-started)}))
        elif args.action == "events":
            print(json.dumps(page.evaluate("""() => (window.__siteQaApplyEvidence||[]).filter(e=>e.status>=400).map(e=>({
              status:e.status,at:e.startedAt,error:e.response.detail||e.response.error,
              output:e.request.responses.find(r=>r.taskId===(e.response.detail||{}).taskId)?.output?.slice(0,1200)
            }))"""), ensure_ascii=False))
        elif args.action == "ai":
            # Transparent evidence tap: never intercept, mock, or alter traffic.
            page.evaluate("""() => {
              if(window.__siteQaFetchObserved) return;
              window.__siteQaFetchObserved=true;window.__siteQaApplyEvidence=[];
              const original=window.fetch;
              window.fetch=async function(url,options) {
                const tracked=String(url).endsWith('/design-system/desktop-ai/apply');
                const evidence=tracked?{request:JSON.parse(options.body),startedAt:new Date().toISOString()}:null;
                const response=await original.apply(this,arguments);
                if(evidence) {evidence.status=response.status;evidence.response=await response.clone().json();window.__siteQaApplyEvidence.push(evidence);}
                return response;
              };
            }""")
            evidence_start=page.evaluate('window.__siteQaApplyEvidence.length')
            page.evaluate("""({id,provider,operation})=>{const s=window.__flowStore.getState();s.setNodeData(id,{aiProvider:provider,aiEffort:'medium'});window.__siteAiRuns||={};window.__siteAiRuns[id]={state:'running'};s.runDesignSystemAi(id,operation,'desktop').then(result=>window.__siteAiRuns[id]={state:'done',result}).catch(e=>window.__siteAiRuns[id]={state:'error',error:String(e)});} """,{'id':ids['designsystem'],'provider':args.provider,'operation':args.operation})
            started=time.time()
            last=None
            while page.evaluate('id=>window.__siteAiRuns[id].state',ids['designsystem'])=='running':
                if time.time()-started>3600: raise TimeoutError('DS AI exceeded one hour')
                page.wait_for_timeout(5000)
                status=page.evaluate("id=>window.__flowStore.getState().statuses[id]",ids['designsystem'])
                if status!=last:
                    print(json.dumps({'site':args.site,'provider':args.provider,'operation':args.operation,'status':status,'seconds':round(time.time()-started)}),flush=True)
                    last=status
            result=page.evaluate('id=>window.__siteAiRuns[id]',ids['designsystem'])
            value=page.evaluate('id=>window.GraphDev.node(id).data',ids['designsystem'])
            evidence=page.evaluate('start=>window.__siteQaApplyEvidence.slice(start)',evidence_start)
            # Other DS runs can execute concurrently; scope evidence by document.
            evidence=[entry for entry in evidence if entry['request']['document'].get('id')==value.get('systemId')]
            output(f'{args.site}-{args.provider}-{args.operation}',{'result':result,'node':value,'applyEvidence':evidence,'seconds':round(time.time()-started)})
            stage_status=(value.get('pipelineStatus') or {}).get(args.operation,{}).get('status')
            passed=bool(result.get('result')) and stage_status=='success'
            print(json.dumps({'state':result['state'],'ok':passed,'error':value.get('lastError'),'pipeline':value.get('pipelineStatus'),'seconds':round(time.time()-started)}))
            if not passed:
                raise SystemExit(1)
        elif args.action == "probe":
            capture=page.evaluate("id=>window.GraphDev.node(id).data", ids['sourceimport'])
            preview=capture['blocks'][0].get('previews',{}).get('desktop') or capture['blocks'][0]['preview']
            result=page.evaluate("""async ({provider,preview})=>{
              if(preview.startsWith('ddna://blobs/')) {const name=preview.slice('ddna://blobs/'.length);preview=(await window.designDNA.blobs.getMany([name]))[name];}
              try {return await window.designDNA.providers.chatRequest({provider,model:provider==='claude'?'opus':null,
                profile:'quality_judge',messages:[{role:'user',content:[{type:'text',text:'Inspect the attached website header. Return only JSON with visibleWords (up to 8 exact visible words) and dominantBackground. Do not infer site content outside this image.'},{type:'image_url',image_url:{url:preview}}]}]});}
              catch(error){return {error:String(error),requestedProvider:provider};}
            }""",{'provider':args.provider,'preview':preview})
            result['qaEvidence'] = {'sourceNodeId':ids['sourceimport'], 'viewport':'desktop',
                'imageReference':preview if preview.startswith('ddna:') else 'inline',
                'source':(capture.get('sourceArtifact') or {}).get('source')}
            output(args.site+'-'+args.provider+'-image-probe',result)
            print(json.dumps(result))
            if result.get('error'):
                raise SystemExit(1)
        elif args.action == "diagnose":
            result=page.evaluate("""async id=>{
              const blocks=window.GraphDev.node(id).data.blocks;
              const count=v=>{const s=JSON.stringify(v);return {png:s.split('data:image/png').length-1,blobs:s.split('ddna://blobs/').length-1}};
              const before=count(blocks.map(b=>b.ir));
              const r=await fetch('/api/block-parse/refine',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({blocks,operations:[]})});
              const result=await r.json(); return {status:r.status,before,after:count(result.blocks?.map(b=>b.ir)),error:result.error};
            }""", ids['sourceimport'])
            output(args.site+'-blob-roundtrip',result)
            print(json.dumps(result))
        elif args.action == "import":
            page.evaluate("""({id,provider})=>{const s=window.__flowStore.getState();s.setNodeData(id,{importedUrl:null,aiProvider:provider,aiRefine:true});window.__siteRuns||={};window.__siteRuns[id]={state:'running'};s.runSourceImport(id).then(()=>window.__siteRuns[id]={state:'done'}).catch(e=>window.__siteRuns[id]={state:'error',error:String(e)});} """, {"id":ids["sourceimport"],"provider":args.provider})
            started=time.time()
            last=None
            while page.evaluate("id=>window.__siteRuns[id].state",ids['sourceimport']) == "running":
                if time.time()-started>2400: raise TimeoutError("Source run exceeded 40 minutes")
                page.wait_for_timeout(5000)
                status=page.evaluate("id=>({busy:window.__flowStore.getState().busy[id],status:window.__flowStore.getState().statuses?.[id]})",ids["sourceimport"])
                if status!=last:
                    print(json.dumps(status),flush=True)
                    last=status
            value=page.evaluate("id=>window.GraphDev.node(id).data",ids["sourceimport"])
            output(f"{args.site}-{args.provider}-source",value)
            print(json.dumps({"blocks":len(value.get("blocks",[])),"pipeline":value.get("pipelineStatus"),"seconds":round(time.time()-started)}))
        elif args.action == "build":
            result=page.evaluate("id=>window.__flowStore.getState().rebuildDesignSystemFromSource(id)",ids["designsystem"])
            value=page.evaluate("id=>window.GraphDev.node(id).data",ids["designsystem"])
            output(args.site+"-ds",value)
            print(json.dumps({"ok":result,"systemId":value.get("systemId"),"summary":value.get("summary"),"error":value.get("lastError")}))
            if not result:
                raise RuntimeError(value.get('lastError') or 'DS build did not succeed')
        elif args.action == "shot":
            page.evaluate("window.GraphDev.fit()")
            page.wait_for_timeout(700)
            OUT.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(OUT/"canvas.png"))
        else:
            print(json.dumps(page.evaluate("""async()=>({pages:window.GraphDev.pages(),graph:window.GraphDev.state(),engine:await window.designDNA.engine.status(),nodes:window.__flowStore.getState().nodes.map(n=>({id:n.id,type:n.type,site:n.data.qaSite,blocks:n.data.blocks?.length,systemId:n.data.systemId,error:n.data.lastError,provider:n.data.aiProvider,pipeline:n.data.pipelineStatus}))})""")))


if __name__ == "__main__":
    main()
