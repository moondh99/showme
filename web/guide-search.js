// Search only the approved fields already delivered to the learner. No model call.
export function searchApprovedSteps(steps,query){
  const terms=String(query).trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if(!terms.length)return [];
  return steps.map((step,index)=>({step,index})).filter(({step})=>{
    const text=[step.title,step.instruction,step.completion_check].join(' ').toLocaleLowerCase();
    return terms.every(term=>text.includes(term));
  });
}
