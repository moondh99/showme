#!/usr/bin/env python3
"""Frozen local evaluation of the production answer function; never alters guides.
Default is a dry run. --execute makes paid Meta requests with bounded concurrency.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from dotenv import load_dotenv
from showme.images import prepare_image
from showme.vision import QUESTION_PROMPT, VisionError, answer_question


def iou(a,b):
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union if union else 0


def score(expectation,answer):
    status=answer['status']==expectation['expected_status']
    groups=all(any(term in answer['answer'] for term in group) for group in expectation.get('required_answer_groups',[]))
    box=expectation.get('reference_box')
    overlap=max((iou(h['box'],box) for h in answer['highlights']),default=0) if box else None
    return {'status_match':status,'answer_terms_match':groups,'best_iou':round(overlap,4) if overlap is not None else None,
            'geometry_pass':overlap>=.5 if box else None,
            'inappropriate_answer':expectation['expected_status'] in ('insufficient_information','not_visible') and answer['status']=='answered',
            'automatic_checks_pass':status and groups and (overlap is None or overlap>=.5)}


def percentile(values, fraction):
    """Nearest-rank percentile, including small non-multiple sample sizes."""
    if not values or not 0 < fraction <= 1:
        raise ValueError('A percentile needs observations and a fraction in (0, 1].')
    return sorted(values)[math.ceil(len(values) * fraction) - 1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--repeat',type=int,default=2,choices=range(1,4))
    parser.add_argument('--workers',type=int,default=2,choices=[1,2])
    parser.add_argument('--cases',default='evaluations/grounded-qa-v1/cases.json')
    parser.add_argument('--contexts',default='evaluations/grounded-qa-v1/contexts.json')
    parser.add_argument('--output',default='state/evaluations')
    args=parser.parse_args()
    cases_path=ROOT/args.cases;contexts_path=ROOT/args.contexts
    cases=json.loads(cases_path.read_text());contexts=json.loads(contexts_path.read_text())
    planned=sum(2 if c.get('followup') else 1 for c in cases)*args.repeat
    print(json.dumps({'mode':'execute' if args.execute else 'dry_run','cases':len(cases),'planned_calls':planned,'workers':args.workers}),flush=True)
    prepared={}
    for key,ctx in contexts.items():
        _,data=prepare_image(ROOT/ctx['image'])
        if hashlib.sha256(data).hexdigest()!=ctx['canonical_sha256']:raise ValueError('Input photograph changed: '+key)
        prepared[key]=data
    if not args.execute:return
    load_dotenv(ROOT/'.env.local',override=False)
    output=ROOT/args.output/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output.mkdir(parents=True,exist_ok=False)
    manifest={'planned_calls':planned,'cases_sha256':hashlib.sha256(cases_path.read_bytes()).hexdigest(),
              'contexts_sha256':hashlib.sha256(contexts_path.read_bytes()).hexdigest(),
              'prompt_sha256':hashlib.sha256(QUESTION_PROMPT.encode()).hexdigest(),'repeat':args.repeat,
              'limits':'No retries; two concurrent calls maximum; production answering function, separate from public endpoint throttling.',
              'evaluation_limitations':'Agent-authored expectations on known photographs; not independent human evaluation, unseen-photo generalization, or user impact.'}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2))
    rows=[]
    def run(case,repeat):
        ctx=contexts[case['context']];history=[];turns=[]
        for number,expected in enumerate([case]+([case['followup']] if case.get('followup') else [])):
            start=time.monotonic();row={'case_id':case['id'],'repeat':repeat,'turn':number,'context':case['context'],
                'image_origin':ctx['image_origin'],'question':expected['question'],'expected':expected}
            try:
                answer,metrics=answer_question(prepared[case['context']],ctx['approved_step'],expected['question'],history)
                row.update(answer=answer,metrics=metrics,checks=score(expected,answer))
                history.append({'question':expected['question'],'response':answer})
            except VisionError as exc:row.update(error={'code':exc.code,'message':str(exc)})
            row['wall_seconds']=round(time.monotonic()-start,3);turns.append(row)
            # A failed clarification must not be replaced by invented conversation history.
            if expected.get('followup') and (row.get('answer',{}).get('status')!='needs_clarification'):break
        return turns
    with (output/'responses.jsonl').open('w') as stream,ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(run,case,repeat+1) for repeat in range(args.repeat) for case in cases]
        for future in as_completed(futures):
            for row in future.result():
                rows.append(row);stream.write(json.dumps(row,ensure_ascii=False)+'\n');stream.flush()
                print(json.dumps({'completed':len(rows),'case':row['case_id'],'repeat':row['repeat'],'turn':row['turn'],
                    'status':row.get('answer',{}).get('status'),'checks':row.get('checks'),'error':row.get('error',{}).get('code')},ensure_ascii=False),flush=True)
    answered=[r for r in rows if 'answer' in r];geometry=[r for r in answered if r['checks']['best_iou'] is not None]
    summary={'attempted_calls':len(rows),'planned_calls':planned,'valid_responses':len(answered),'errors':len(rows)-len(answered),
        'status_matches':sum(r['checks']['status_match'] for r in answered),'all_automatic_checks_pass':sum(r['checks']['automatic_checks_pass'] for r in answered),
        'inappropriate_answers':sum(r['checks']['inappropriate_answer'] for r in answered),'geometry_passes':sum(r['checks']['geometry_pass'] for r in geometry),
        'geometry_count':len(geometry),'latency_p50_seconds':round(statistics.median(r['wall_seconds'] for r in rows),3),
        'latency_p95_seconds':round(percentile([r['wall_seconds'] for r in rows],.95),3),
        'usage':{k:sum(r['metrics'].get('usage',{}).get(k,0) for r in answered) for k in ['prompt_tokens','completion_tokens','total_tokens']},
        'by_origin':{origin:{'valid_responses':sum(r['image_origin']==origin for r in answered),'status_matches':sum(r['image_origin']==origin and r['checks']['status_match'] for r in answered)} for origin in ['real_cc0','synthetic']},
        'limitation':manifest['evaluation_limitations']}
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'result_directory':str(output.relative_to(ROOT)),'summary':summary},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
