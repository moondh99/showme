import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../web/answer-view.js',import.meta.url),'utf8');
const {rulePresentation}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const instruction='파란 펜은 운영자 메모용입니다. 참가자에게 건네지 않습니다.\n예외는 없습니다.';
const completion='잉크가 마른 뒤 접수를 시작합니다.';
const fixture=()=>({status:'answered',answer:'파란 펜은 운영자 메모용입니다.',evidence:[{source:'instruction'}],
  approved_context:[{source:'instruction',text:instruction},{source:'completion_check',text:completion}],
  assessment:{conditions:[{source:'instruction',detail:'파란 펜은 운영자 메모용입니다.',state:'not_met'}]}});
test('duplicate quotation is omitted while complete approved fields and exception remain verbatim',()=>{
  const view=rulePresentation(fixture());assert.equal(view.showAnswer,false);
  assert.deepEqual(view.contexts.map(c=>c.segments.map(s=>s.text).join('')),[instruction,completion]);
  assert.deepEqual(view.contexts[0].segments[0].conditions,[0]);
});
test('conditions in completion and overlapping quotations preserve every character and state',()=>{
  const answer=fixture();answer.assessment.conditions.push(
    {source:'instruction',detail:'운영자 메모용',state:'met'},
    {source:'completion_check',detail:completion,state:'unknown'});
  const view=rulePresentation(answer);
  assert.deepEqual(view.contexts.map(c=>c.segments.map(s=>s.text).join('')),[instruction,completion]);
  assert.ok(view.contexts[0].segments.some(s=>s.conditions.join(',')==='0,1'));
  assert.equal(view.contexts[1].conditions[0].state,'unknown');
});
test('unmatched answer text, unresolved replies and visual answers are never suppressed',()=>{
  for(const answer of [{...fixture(),answer:'사진 속 물체는 파란색입니다.'},
    {...fixture(),status:'insufficient_information'},
    {...fixture(),evidence:[{source:'photo'}]},
    {...fixture(),approved_context:[]}])assert.equal(rulePresentation(answer).showAnswer,true);
});
test('missing or wrong-source condition remains visible for fallback instead of being silently dropped',()=>{
  const answer=fixture();answer.assessment.conditions=[{source:'completion_check',detail:instruction,state:'unknown'}];
  const view=rulePresentation(answer);assert.equal(view.unmapped[0].detail,instruction);
  assert.ok(view.contexts.every(c=>c.conditions.length===0));
});
test('every quoted paragraph must be present, including extra caveats and punctuation',()=>{
  const answer=fixture();answer.answer=instruction+'\n\n'+completion;
  assert.equal(rulePresentation(answer).showAnswer,false);
  answer.answer+='\n담당자에게 확인하세요.';assert.equal(rulePresentation(answer).showAnswer,true);
});

test('a blocked verdict uses one mapped reason and distinguishes the other target',()=>{
  const answer=fixture();
  const reason='참가자에게 건네지 않습니다.';
  answer.assessment={decision:'blocked',conditions:[
    {source:'instruction',detail:reason,state:'met',role:'basis'},
    {source:'completion_check',detail:completion,state:'unknown',role:'other_target'}
  ]};
  const view=rulePresentation(answer);
  assert.equal(view.reason,reason);
  assert.equal(view.contexts[0].segments.find(s=>s.text===reason).otherTarget,false);
  assert.equal(view.contexts[1].segments[0].otherTarget,true);
  assert.deepEqual(view.contexts.map(c=>c.segments.map(s=>s.text).join('')),[instruction,completion]);
  answer.assessment.conditions[0].detail='승인되지 않은 이유입니다.';
  assert.equal(rulePresentation(answer).reason,null);
  assert.deepEqual(rulePresentation(answer).unmapped,[]);
  answer.assessment.conditions[0].detail=reason;
  answer.assessment.decision='conditional';
  assert.equal(rulePresentation(answer).reason,null);
});

test('only a blocked verdict presents a quote as the reason for blocking',()=>{
  const answer=fixture();
  const targetRule='파란 펜은 운영자 메모용입니다.';
  answer.assessment={decision:'conditional',conditions:[
    {source:'instruction',detail:targetRule,state:'met',role:'basis'},
    {source:'completion_check',detail:completion,state:'unknown',role:'condition'}
  ]};
  for(const decision of ['conditional','allowed']){
    answer.assessment.decision=decision;
    const view=rulePresentation(answer);
    assert.equal(view.reason,null);
    assert.equal(view.contexts[0].conditions[0].role,'condition');
    assert.equal(view.contexts[1].conditions[0].state,'unknown');
    assert.equal(answer.assessment.conditions[0].role,'basis');
    assert.deepEqual(view.contexts.map(c=>c.segments.map(s=>s.text).join('')),[instruction,completion]);
  }
});
