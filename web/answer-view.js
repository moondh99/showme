// Presentation only: retain every character of both approved fields, including
// exceptions that were not quoted by the model. Never infer a missing condition.
export function rulePresentation(answer){
  const contexts=(answer.approved_context||[]).map(context=>({...context,conditions:[],segments:[]}));
  const {decision,conditions=[]}=answer.assessment||{},unmapped=[];
  conditions.forEach((condition,index)=>{
    const context=contexts.find(c=>c.source===condition.source&&c.text.includes(condition.detail));
    if(!context||!condition.detail){
      if(!condition.role)unmapped.push({...condition,index});
      return;
    }
    const start=context.text.indexOf(condition.detail);
    // A stored or fresh model reply can mislabel a quote. The verdict owns its display role.
    const role=condition.role==='basis'&&decision!=='blocked'?'condition':condition.role;
    context.conditions.push({...condition,role,index,start,end:start+condition.detail.length});
  });
  for(const context of contexts){
    const boundaries=[...new Set([0,context.text.length,...context.conditions.flatMap(c=>[c.start,c.end])])].sort((a,b)=>a-b);
    for(let i=0;i<boundaries.length-1;i++){
      const start=boundaries[i],end=boundaries[i+1];
      const covering=context.conditions.filter(c=>c.start<=start&&c.end>=end);
      context.segments.push({text:context.text.slice(start,end),
        conditions:covering.map(c=>c.index),
        otherTarget:covering.length>0&&covering.every(c=>c.role==='other_target'),
        starts:context.conditions.filter(c=>c.start===start).map(c=>c.index)});
    }
  }
  // Only omit the separate quotation if each complete paragraph is already
  // visible verbatim. Unknown/visual answers and unmatched text remain visible.
  const paragraphs=(answer.answer||'').split(/\n+/).map(p=>p.trim()).filter(Boolean);
  const quotationIsVisible=answer.status==='answered'&&answer.evidence?.some(e=>e.source!=='photo')&&contexts.length>0&&paragraphs.length>0&&
    paragraphs.every(p=>contexts.some(c=>c.text.includes(p)));
  const bases=contexts.flatMap(c=>c.conditions.filter(quote=>quote.role==='basis'));
  const reason=decision==='blocked'&&bases.length===1?bases[0].detail:null;
  return {contexts,unmapped,reason,showAnswer:!quotationIsVisible};
}
