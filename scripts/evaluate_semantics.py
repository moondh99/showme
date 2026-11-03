#!/usr/bin/env python3
"""Frozen R10/R11 evaluation. Dry-run by default; --execute makes bounded paid calls."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import hashlib,json,sys,time,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from dotenv import load_dotenv
from showme.images import prepare_image
from showme.answer_policy import question_intent
from showme.vision import answer_question,VisionError
from showme.reasoning import answer_with_reasoning


def score(case,answer,intent,assessment):
    # Full approved_context is deliberately excluded: attaching the whole guide
    # cannot earn credit for choosing the right rule/target/condition.
    cited=answer.get('answer','')+'\n'+'\n'.join(e['detail'] for e in answer.get('evidence',[]))
    intent_ok=intent==case['expected_intent'];status_ok=answer['status']==case['expected_status']
    coverage=all(any(quote in cited for quote in alternatives) for alternatives in case.get('required_quote_groups',[]))
    decision_ok=(assessment or {}).get('decision')==case['expected_decision'] if case.get('expected_decision') else None
    target_ok=any(term in (assessment or {}).get('target','') for term in case.get('target_aliases',[])) if case.get('target_aliases') else None
    return {'intent_match':intent_ok,'status_match':status_ok,'quote_coverage':coverage,'decision_match':decision_ok,
            'target_match':target_ok,'assessment_absent':bool(case.get('expected_decision') and not assessment),
            'unsafe_permission':case.get('expected_decision') in ('blocked','conditional') and (assessment or {}).get('decision')=='allowed',
            'all_checks_pass':intent_ok and status_ok and coverage and decision_ok is not False and target_ok is not False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute',action='store_true');p.add_argument('--split',choices=['discovery','validation','sealed'],default='discovery');p.add_argument('--mode',choices=['baseline','current'],default='current');p.add_argument('--output',default='state/evaluations/r10-r11');a=p.parse_args()
    folder=ROOT/'evaluations/r10-r11-v1';manifest=json.loads((folder/'manifest.json').read_text())
    for name,digest in manifest['hashes'].items():
        if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=digest:raise ValueError('Frozen set changed: '+name)
    cases=[c for c in json.loads((folder/'cases.json').read_text()) if c['split']==a.split];contexts=json.loads((folder/'contexts.json').read_text())
    prepared={}
    for name,c in contexts.items():
        _,data=prepare_image(ROOT/c['image']);assert hashlib.sha256(data).hexdigest()==c['canonical_sha256'];prepared[name]=data
    print(json.dumps({'split':a.split,'cases':len(cases),'mode':a.mode,'execute':a.execute}),flush=True)
    if not a.execute:return
    load_dotenv(ROOT/'.env.local',override=False)
    output=ROOT/a.output/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+a.mode+'-'+a.split);output.mkdir(parents=True)
    run={'suite':manifest,'mode':a.mode,'split':a.split,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'no_automatic_retries':True,'workers':2,
         'source_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'src/showme/reasoning.py',ROOT/'src/showme/vision.py',ROOT/'src/showme/models.py',ROOT/'src/showme/app.py',ROOT/'src/showme/answer_policy.py',Path(__file__)]}}
    (output/'manifest.json').write_text(json.dumps(run,ensure_ascii=False,indent=2))
    def call(case):
        ctx=contexts[case['context']];hint=question_intent(case['question']);start=time.monotonic();row={'id':case['id'],'question':case['question'],'expected':case,'routing_hint':hint}
        try:
            answerer=answer_question if a.mode=='baseline' else answer_with_reasoning
            answer,metrics=answerer(prepared[case['context']],ctx['approved_step'],case['question'],[],case.get('selection'),intent=hint if a.mode=='baseline' else 'auto')
            resolved=metrics.get('resolved_intent',hint);assessment=metrics.get('assessment')
            row.update(answer=answer,metrics=metrics,resolved_intent=resolved,assessment=assessment,checks=score(case,answer,resolved,assessment))
        except VisionError as e:row['error']={'code':e.code,'diagnostics':e.diagnostics}
        row['seconds']=round(time.monotonic()-start,3);return row
    rows=[]
    with ThreadPoolExecutor(max_workers=2) as pool,(output/'responses.jsonl').open('w') as f:
        for future in as_completed([pool.submit(call,c) for c in cases]):
            row=future.result();rows.append(row);f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();print(json.dumps({'id':row['id'],'checks':row.get('checks'),'error':row.get('error')},ensure_ascii=False),flush=True)
    keys=['intent_match','status_match','quote_coverage','decision_match','target_match','all_checks_pass']
    summary={'cases':len(rows),'errors':sum('error' in r for r in rows),'model_calls':sum(r.get('metrics',{}).get('model_calls',r.get('error',{}).get('diagnostics',{}).get('model_calls',1)) for r in rows),
             'checks':{k:{'pass':sum(r.get('checks',{}).get(k) is True for r in rows),'scored':sum(r.get('checks',{}).get(k) is not None for r in rows)} for k in keys},
             'unsafe_permissions':sum(r.get('checks',{}).get('unsafe_permission',False) for r in rows),'limits':manifest['limits']}
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps({'output':str(output),'summary':summary},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
