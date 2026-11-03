import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../web/guide-search.js',import.meta.url),'utf8');
const {searchApprovedSteps}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const steps=[{title:'펜 준비',instruction:'검은 펜은 서명용입니다.',completion_check:'두 펜 확인',operator_note:'PRIVATE 명찰'},
  {title:'명찰 배치',instruction:'노란 트레이에는 현장등록 명찰을 놓습니다.',completion_check:'트레이 확인'}];
test('approved search finds other steps and requires all typed terms',()=>{
  assert.deepEqual(searchApprovedSteps(steps,'명찰').map(r=>r.index),[1]);
  assert.deepEqual(searchApprovedSteps(steps,'노란 명찰').map(r=>r.index),[1]);
  assert.deepEqual(searchApprovedSteps(steps,'노란 펜'),[]);
});
test('search excludes private notes and treats empty and special input literally',()=>{
  assert.deepEqual(searchApprovedSteps(steps,'PRIVATE'),[]);
  assert.deepEqual(searchApprovedSteps(steps,'   '),[]);
  assert.deepEqual(searchApprovedSteps(steps,'<script>'),[]);
});
