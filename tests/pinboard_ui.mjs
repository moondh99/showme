import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../web/pinboard.js',import.meta.url),'utf8');
const {connectorGeometry,highlightPoint,crowdedMarkerIndices}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));

test('connector preserves the selected image coordinate inside an offset board',()=>{
  const result=connectorGeometry({left:100,top:200,width:800,height:600},
    {left:120,top:220,width:400,height:300},{left:650,top:240,height:300},{x:750,y:500});
  assert.deepEqual(result.source,{x:320,y:170});
  assert.deepEqual(result.target,{x:550,y:125});
  assert.match(result.path,/^M 320 170 C /);
});
test('resize and page scroll retain normalized selection and relative line endpoints',()=>{
  const a=connectorGeometry({left:0,top:100,width:900,height:700},
    {left:20,top:160,width:500,height:400},{left:650,top:150,height:240},{x:200,y:800});
  const b=connectorGeometry({left:0,top:-200,width:900,height:700},
    {left:20,top:-140,width:500,height:400},{left:650,top:-150,height:240},{x:200,y:800});
  assert.deepEqual(a,b);
  const resized=connectorGeometry({left:0,top:100,width:600,height:500},
    {left:20,top:160,width:250,height:200},{left:400,top:150,height:240},{x:200,y:800});
  assert.deepEqual(resized.source,{x:70,y:220});
});
test('empty or non-finite geometry never creates a broken SVG path',()=>{
  const board={left:0,top:0,width:800,height:600},image={left:20,top:20,width:400,height:300},note={left:600,top:20,height:200};
  assert.equal(connectorGeometry(board,{...image,width:0},note),null);
  assert.equal(connectorGeometry(board,image,note,{x:NaN,y:200}),null);
  assert.equal(connectorGeometry({...board,height:0},image,note),null);
  const edge=connectorGeometry(board,image,note,{x:1200,y:-10});
  assert.deepEqual(edge.source,{x:420,y:20});
});
test('approved marker centers retain the same normalized API coordinate',()=>{
  assert.deepEqual(highlightPoint([552,125,943,824]),{x:748,y:475});
  assert.deepEqual(highlightPoint([0,0,1000,1000]),{x:500,y:500});
});

test('close approved points use separate labeled controls on narrow photos',()=>{
  const points=[{x:744,y:543},{x:822,y:572},{x:100,y:100}];
  assert.deepEqual([...crowdedMarkerIndices(points,280,210)],[0,1]);
  assert.deepEqual([...crowdedMarkerIndices(points,680,510)],[]);
});
test('distant mobile targets remain visible and 48px spacing has no collision',()=>{
  assert.equal(crowdedMarkerIndices([{x:200,y:500},{x:750,y:500}],280,210).size,0);
  assert.equal(crowdedMarkerIndices([{x:0,y:0},{x:480,y:0}],100,100).size,0);
});
