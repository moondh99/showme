#!/usr/bin/env python3
"""R12 tail-latency: same adaptive audit, fresh default-depth vs explicit-low calls.
Dry run by default. Cases, expected labels and approved rules are frozen inputs.
"""
import argparse,hashlib,importlib.util,json,math,random,statistics,sys,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from dotenv import load_dotenv
from showme.images import prepare_image
from showme.reasoning import answer_with_reasoning
from showme.vision import VisionError
spec=importlib.util.spec_from_file_location('semantics',ROOT/'scripts/evaluate_semantics.py');scoring=importlib.util.module_from_spec(spec);spec.loader.exec_module(scoring)


def load_cases():
    folder=ROOT/'evaluations/r10-r11-v1';manifest=json.loads((folder/'manifest.json').read_text())
    for name,digest in manifest['hashes'].items():
        if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=digest:raise ValueError('Frozen set changed')
    cases=json.loads((folder/'cases.json').read_text());contexts=json.loads((folder/'contexts.json').read_text());photos={}
    for key,ctx in contexts.items():
        _,image=prepare_image(ROOT/ctx['image']);assert hashlib.sha256(image).hexdigest()==ctx['canonical_sha256'];photos[key]=image
    slow=dict(next(c for c in cases if c['id']=='V06'),id='SLOW',split='selected_repetition',
              question='교육을 받았으니까 이 표로 장비를 가져가겠습니다.',
              selection={'point':{'x':240,'y':641},'box':[139,529,344,735]})
    return cases,contexts,photos,slow,manifest


def stats(rows):
    out={}
    for profile in dict.fromkeys(r['profile'] for r in rows):
        rr=[r for r in rows if r['profile']==profile];good=[r for r in rr if 'checks' in r];times=sorted(r['seconds'] for r in rr)
        phases={}
        for index,label in enumerate(['plan','audit','repair']):
            pp=[r['metrics']['passes'][index] for r in good if len(r['metrics']['passes'])>index]
            if pp:
                phases[label]={'count':len(pp),'p50_seconds':round(statistics.median(p['elapsed_seconds'] for p in pp),3),
                    'p95_seconds':sorted(p['elapsed_seconds'] for p in pp)[math.ceil(.95*len(pp))-1],
                    'reasoning_tokens':sum(p.get('reasoning_tokens') or 0 for p in pp),
                    'visible_tokens':sum(p.get('visible_output_tokens') or 0 for p in pp),
                    'http_seconds':round(sum(p.get('timings',{}).get('http_seconds',0) for p in pp),3),
                    'local_seconds':round(sum(sum(v for k,v in p.get('timings',{}).items() if k!='http_seconds') for p in pp),6)}
        out[profile]={'cases':len(rr),'errors':len(rr)-len(good),'p50_seconds':round(statistics.median(times),3),
            'p95_seconds':times[math.ceil(.95*len(times))-1],'max_seconds':max(times),
            'model_calls':sum(r.get('metrics',{}).get('model_calls',r.get('error',{}).get('diagnostics',{}).get('model_calls',1)) for r in rr),
            'checks':{k:{'pass':sum(r['checks'].get(k) is True for r in good),'scored':sum(r['checks'].get(k) is not None for r in good)} for k in ['intent_match','status_match','target_match','decision_match','quote_coverage','all_checks_pass']},
            'unsafe_permissions':sum(r['checks']['unsafe_permission'] for r in good),
            'http_wait_seconds':round(sum(p.get('timings',{}).get('http_seconds',0) for r in good for p in r['metrics']['passes']),3),
            'local_pipeline_seconds':round(sum(r['seconds']-sum(p.get('timings',{}).get('http_seconds',0) for p in r['metrics']['passes']) for r in good),6),
            'repairs':sum(r.get('metrics',{}).get('audit_strategy')=='compact_repair' for r in rr),
            'total_tokens':sum(r.get('metrics',{}).get('usage',{}).get('total_tokens',0) for r in rr),
            'phases':phases}
    return out


def summarize(rows):
    out={'all':stats(rows),'fixed_suite':stats([r for r in rows if r['split']!='selected_repetition']),
         'selected_repetitions':stats([r for r in rows if r['split']=='selected_repetition'])}
    pairs={}
    for r in rows:pairs.setdefault(r['id'],{})[r['profile']]=r
    both=[{'id':key,'legacy_seconds':p['legacy']['seconds'],'corrective_seconds':p['corrective']['seconds'],
           'saved_seconds':round(p['legacy']['seconds']-p['corrective']['seconds'],3)} for key,p in pairs.items() if set(p)=={'legacy','corrective'}]
    out['paired_details']=both
    if both:
        candidate=[r for r in rows if r['profile']=='corrective']
        before,after=out['all']['legacy'],out['all']['corrective']
        fixed_before,fixed_after=out['fixed_suite']['legacy'],out['fixed_suite']['corrective']
        out['gates']={'quality_pass':all(r.get('checks',{}).get('all_checks_pass') for r in candidate),
            'latency_pass':after['p50_seconds']<before['p50_seconds'] and after['p95_seconds']<before['p95_seconds']
                and fixed_after['p50_seconds']<fixed_before['p50_seconds'] and fixed_after['p95_seconds']<fixed_before['p95_seconds']
                and out['selected_repetitions']['corrective']['max_seconds']<30}
    return out


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true');parser.add_argument('--phase',choices=['canary','corrective-canary','paired'],default='canary');parser.add_argument('--output',default='state/evaluations/r12-tail');args=parser.parse_args()
    cases,contexts,photos,slow,suite=load_cases()
    if args.phase=='canary':
        jobs=[[(dict(slow,id='SLOW-'+p),p)] for p in ['legacy','plan_low','audit_low','bounded']]
        jobs += [[(next(c for c in cases if c['id']==key),'bounded')] for key in ['V04','H05']]
        workers=1  # isolate each knob; this is a development canary, not a holdout
    elif args.phase=='corrective-canary':
        jobs=[[(slow,'corrective')]]+ [[(next(c for c in cases if c['id']==key),'corrective')] for key in ['V04','H05']]
        workers=1
    else:
        random.Random(523).shuffle(cases);cases += [dict(slow,id='SLOW-'+str(i+1)) for i in range(3)]
        jobs=[[(c,p) for p in (['legacy','corrective'] if i%2==0 else ['corrective','legacy'])] for i,c in enumerate(cases)];workers=2
    print(json.dumps({'phase':args.phase,'pipelines':sum(len(j) for j in jobs),'max_model_calls':sum(2 if p=='corrective' else 3 for j in jobs for c,p in j),'workers':workers,'execute':args.execute}),flush=True)
    if not args.execute:return
    load_dotenv(ROOT/'.env.local',override=False)
    output=ROOT/args.output/(args.phase+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));output.mkdir(parents=True)
    manifest={'baseline_commit':'3a51ee5','phase':args.phase,'suite':suite,'workers':workers,'retry':0,'response_cache':False,'shared_draft':False,
        'jobs':[[{'id':c['id'],'profile':p,'case':c} for c,p in j] for j in jobs],
        'profiles':{'legacy':{'plan':None,'audit':None,'repair':None},'plan_low':{'plan':'low','audit':None,'repair':None},'audit_low':{'plan':None,'audit':'low','repair':None},'bounded':{'plan':'low','audit':'low','repair':None},'corrective':{'plan':'low','audit':'low','audit_style':'full_correction','max_calls':2}},
        'source_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'src/showme/reasoning.py',ROOT/'src/showme/vision.py',ROOT/'src/showme/app.py',ROOT/'src/showme/models.py',ROOT/'src/showme/answer_policy.py',Path(__file__)]}}
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    def run(job):
        result=[]
        for case,profile in job:
            start=time.monotonic();r={'id':case['id'],'split':case['split'],'profile':profile,'question':case['question'],'expected':case}
            try:
                answer,metrics=answer_with_reasoning(photos[case['context']],contexts[case['context']]['approved_step'],case['question'],[],case.get('selection'),intent='auto',effort_profile=profile)
                r.update(answer=answer,metrics=metrics,checks=scoring.score(case,answer,metrics['resolved_intent'],metrics['assessment']))
            except VisionError as e:r['error']={'code':e.code,'diagnostics':e.diagnostics or {}}
            r['seconds']=round(time.monotonic()-start,3);result.append(r)
            print(json.dumps({'finished':r['id'],'profile':profile,'seconds':r['seconds'],'passes':[p['elapsed_seconds'] for p in r.get('metrics',{}).get('passes',[])],'pass':r.get('checks',{}).get('all_checks_pass'),'error':r.get('error')},ensure_ascii=False),flush=True)
        return result
    rows=[]
    with ThreadPoolExecutor(max_workers=workers) as pool,(output/'responses.jsonl').open('w') as f:
        for future in as_completed([pool.submit(run,j) for j in jobs]):
            for r in future.result():rows.append(r);f.write(json.dumps(r,ensure_ascii=False)+'\n');f.flush()
    summary=summarize(rows);(output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'output':str(output),'summary':summary},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
