import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../web/selection.js',import.meta.url),'utf8');
const {normalizedPoint,bindPointPicker,selectionOverlay}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
test('image-relative points stay consistent at different display sizes and exclude surroundings',()=>{
  assert.deepEqual(normalizedPoint(500,500,{left:100,top:200,width:800,height:600}),{x:500,y:500});
  assert.deepEqual(normalizedPoint(300,350,{left:100,top:200,width:400,height:300}),{x:500,y:500});
  assert.equal(normalizedPoint(99,500,{left:100,top:200,width:800,height:600}),null);
  assert.equal(normalizedPoint(100,200,{left:100,top:200,width:0,height:0}),null);
  assert.deepEqual(normalizedPoint(900,800,{left:100,top:200,width:800,height:600}),{x:1000,y:1000});
});
test('keyboard moves without rerender, clamps edges, commits and cancels',()=>{
  const marker={style:{}};const attrs={};const commits=[];let cancelled=false;
  const frame={classList:{add(){}},setAttribute(k,v){attrs[k]=v;},querySelector(){return marker;}};
  bindPointPicker(frame,{getBoundingClientRect(){return {left:100,top:100,width:200,height:200};}},{active:true,cursor:{x:990,y:500},onMove(){},onCommit(p){commits.push(p);},onCancel(){cancelled=true;}});
  const press=(key,shiftKey=false)=>frame.onkeydown({key,shiftKey,preventDefault(){}});
  press('ArrowRight',true);press('ArrowDown');press('Enter');
  assert.deepEqual(commits[0],{x:1000,y:510});assert.equal(marker.style.left,'100%');
  press('Escape');assert.equal(cancelled,true);assert.equal(attrs.role,'button');
  frame.onclick({clientX:90,clientY:200});assert.equal(commits.length,1);
  frame.onclick({clientX:200,clientY:200});assert.deepEqual(commits[1],{x:500,y:500});
});
test('mask overlay preserves source image coordinates and escapes path data',()=>{
  const markup=selectionOverlay({photo_width:1536,photo_height:1024,mask_bounds:[1105,346,1187,766],mask_path:'M0 0L2 2Z'},null,s=>s.replaceAll('"','&quot;'));
  assert.match(markup,/viewBox="0 0 1536 1024"/);assert.match(markup,/translate\(1105 346\)/);
  assert.equal(selectionOverlay(null,null,s=>s),'');
});
