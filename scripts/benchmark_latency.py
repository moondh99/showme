#!/usr/bin/env python3
"""Fresh paired Meta calls: full reference vs adaptive audit on frozen R10/R11 cases.
Dry run by default. No result cache, shared draft, automatic retry, or guide mutation.
"""
import argparse,hashlib,importlib.util,json,math,random,statistics,subprocess,sys,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from dotenv import load_dotenv
from showme.images import prepare_image
from showme.reasoning import answer_with_reasoning
from showme.vision import VisionError
spec=importlib.util.spec_from_file_location('semantic_scores',ROOT/'scripts/evaluate_semantics.py');scoring=importlib.util.module_from_spec(spec);spec.loader.exec_module(scoring)


def summarize(rows):
    result={}
    for mode in ('full','adaptive'):
        r=[x for x in rows if x['mode']==mode];valid=[x for x in r if 'checks' in x]
        times=sorted(x['seconds'] for x in r)
        result[mode]={'cases':len(r),'errors':len(r)-len(valid),'model_calls':sum(x.get('metrics',{}).get('model_calls',x.get('error',{}).get('diagnostics',{}).get('model_calls',1)) for x in r),
                      'p50_seconds':round(statistics.median(times),3),'p95_seconds':times[math.ceil(.95*len(times))-1],
                      'mean_seconds':round(statistics.mean(times),3),
                      'checks':{k:{'pass':sum(x['checks'].get(k) is True for x in valid),'scored':sum(x['checks'].get(k) is not None for x in valid)} for k in ['intent_match','status_match','decision_match','target_match','quote_coverage','all_checks_pass']},
                      'unsafe_permissions':sum(x['checks']['unsafe_permission'] for x in valid),
                      'strategies':{s:sum(x.get('metrics',{}).get('audit_strategy')==s for x in r) for s in ['full','compact','compact_repair','plain_visual']},
                      'tokens':{k:sum(x.get('metrics',{}).get('usage',{}).get(k,0) for x in r) for k in ['prompt_tokens','completion_tokens','total_tokens']}}
    by_id={}
    for r in rows:by_id.setdefault(r['id'],{})[r['mode']]=r
    pairs=[{'id':id,'full_seconds':r['full']['seconds'],'adaptive_seconds':r['adaptive']['seconds'],'saved_seconds':round(r['full']['seconds']-r['adaptive']['seconds'],3)} for id,r in by_id.items() if set(r)=={'full','adaptive'}]
    result['paired']={'pairs':len(pairs),'adaptive_faster':sum(p['saved_seconds']>0 for p in pairs),'median_saved_seconds':round(statistics.median(p['saved_seconds'] for p in pairs),3),'details':pairs}
    result['call_reduction_percent']=round(100*(1-result['adaptive']['model_calls']/result['full']['model_calls']),2)
    result['p50_reduction_percent']=round(100*(1-result['adaptive']['p50_seconds']/result['full']['p50_seconds']),2)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute',action='store_true');p.add_argument('--only',default='');p.add_argument('--output',default='state/evaluations/r12');a=p.parse_args()
    folder=ROOT/'evaluations/r10-r11-v1';suite=json.loads((folder/'manifest.json').read_text())
    for name,digest in suite['hashes'].items():
        if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=digest:raise ValueError('Frozen set changed')
    cases=json.loads((folder/'cases.json').read_text());ids=a.only.split(',') if a.only else []
    if ids:cases=[c for c in cases if c['id'] in ids]
    if not cases:raise ValueError('No cases selected')
    random.Random(1207).shuffle(cases)
    contexts=json.loads((folder/'contexts.json').read_text());photos={}
    for key,ctx in contexts.items():
        _,data=prepare_image(ROOT/ctx['image']);assert hashlib.sha256(data).hexdigest()==ctx['canonical_sha256'];photos[key]=data
    print(json.dumps({'cases':len(cases),'max_model_calls':5*len(cases),'execute':a.execute}),flush=True)
    if not a.execute:return
    load_dotenv(ROOT/'.env.local',override=False)
    output=ROOT/a.output/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');output.mkdir(parents=True)
    manifest={'baseline_commit':'7dfd18d','suite':suite,'cases':[c['id'] for c in cases],
              'orders':{c['id']:(['full','adaptive'] if i%2==0 else ['adaptive','full']) for i,c in enumerate(cases)},
              'workers':2,'retries':0,'cache':False,'shared_draft':False,
              'comparison':'Two fresh requests per case; alternating variant order; wall time of real answer service, not browser network timing',
              'source_hashes':{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in [ROOT/'src/showme/reasoning.py',ROOT/'src/showme/vision.py',ROOT/'src/showme/models.py',ROOT/'src/showme/answer_policy.py',ROOT/'src/showme/app.py',Path(__file__)]}}
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    def pair(case):
        rr=[]
        for mode in manifest['orders'][case['id']]:
            start=time.monotonic();row={'id':case['id'],'split':case['split'],'mode':mode,'question':case['question'],'expected':case}
            try:
                answer,metrics=answer_with_reasoning(photos[case['context']],contexts[case['context']]['approved_step'],case['question'],[],case.get('selection'),intent='auto',audit_policy=mode,effort_profile='legacy')
                row.update(answer=answer,assessment=metrics['assessment'],resolved_intent=metrics['resolved_intent'],metrics=metrics,checks=scoring.score(case,answer,metrics['resolved_intent'],metrics['assessment']))
            except VisionError as exc:row['error']={'code':exc.code,'diagnostics':exc.diagnostics or {}}
            row['seconds']=round(time.monotonic()-start,3);rr.append(row);print(json.dumps({'case_finished':row['id'],'mode':mode,'seconds':row['seconds'],'pass':row.get('checks',{}).get('all_checks_pass'),'error':row.get('error')},ensure_ascii=False),flush=True)
        return rr
    rows=[]
    with ThreadPoolExecutor(max_workers=2) as pool,(output/'responses.jsonl').open('w') as f:
        for future in as_completed([pool.submit(pair,c) for c in cases]):
            for r in future.result():
                rows.append(r);f.write(json.dumps(r,ensure_ascii=False)+'\n');f.flush();print(json.dumps({'id':r['id'],'mode':r['mode'],'seconds':r['seconds'],'calls':r.get('metrics',{}).get('model_calls'),'pass':r.get('checks',{}).get('all_checks_pass'),'strategy':r.get('metrics',{}).get('audit_strategy'),'error':r.get('error')},ensure_ascii=False),flush=True)
    summary=summarize(rows);(output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps({'output':str(output),'summary':summary},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
