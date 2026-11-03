// The board is presentation only. Image points retain the API's 0..1000 space.
export function highlightPoint(box){
  return {x:Math.round((box[0]+box[2])/2),y:Math.round((box[1]+box[3])/2)};
}

// Keep 44px touch targets distinct; crowded photo markers have labeled controls below.
export function crowdedMarkerIndices(points,width,height,spacing=48){
  const crowded=new Set();
  for(let i=0;i<points.length;i++)for(let j=i+1;j<points.length;j++){
    if(Math.abs(points[i].x-points[j].x)*width/1000<spacing&&Math.abs(points[i].y-points[j].y)*height/1000<spacing){crowded.add(i);crowded.add(j);}
  }
  return crowded;
}

export function connectorGeometry(board,image,note,point={x:1000,y:500}){
  const values=[board.left,board.top,board.width,board.height,image.left,image.top,image.width,image.height,note.left,note.top,note.height,point.x,point.y];
  if(!values.every(Number.isFinite)||board.width<=0||board.height<=0||image.width<=0||image.height<=0||note.height<=0)return null;
  const source={x:image.left-board.left+image.width*Math.max(0,Math.min(1000,point.x))/1000,
    y:image.top-board.top+image.height*Math.max(0,Math.min(1000,point.y))/1000};
  const target={x:note.left-board.left,y:note.top-board.top+Math.min(85,note.height/3)};
  const bend=Math.max(35,Math.abs(target.x-source.x)*.45);
  return {source,target,path:`M ${source.x} ${source.y} C ${source.x+bend} ${source.y} ${target.x-bend} ${target.y} ${target.x} ${target.y}`};
}

export function bindBoardConnection(canvas,point,enabled=true){
  const svg=canvas.querySelector('.pinboard-connector'),image=canvas.querySelector('#work-photo'),note=canvas.querySelector('#approved-step');
  if(!svg||!image||!note)return ()=>{};
  let frame=0;
  const update=()=>{
    frame=0;if(!canvas.isConnected)return;
    const board=canvas.getBoundingClientRect();
    const imageRect=image.getBoundingClientRect();
    const markers=[...canvas.querySelectorAll('.pinboard-marker')];
    const crowded=crowdedMarkerIndices(markers.map(el=>({x:Number(el.dataset.x),y:Number(el.dataset.y)})),imageRect.width,imageRect.height);
    markers.forEach((el,i)=>{el.hidden=crowded.has(i);});
    const geometry=connectorGeometry(board,imageRect,note.getBoundingClientRect(),point);
    if(!enabled||!geometry||window.matchMedia('(max-width:850px)').matches){svg.setAttribute('hidden','');return;}
    svg.removeAttribute('hidden');svg.setAttribute('viewBox',`0 0 ${board.width} ${board.height}`);
    svg.querySelector('path').setAttribute('d',geometry.path);
    for(const [name,p] of [['source',geometry.source],['target',geometry.target]]){
      const dot=svg.querySelector(`[data-connection-${name}]`);dot.setAttribute('cx',p.x);dot.setAttribute('cy',p.y);
    }
  };
  const schedule=()=>{if(!frame)frame=requestAnimationFrame(update);};
  const observer=typeof ResizeObserver==='undefined'?null:new ResizeObserver(schedule);
  [canvas,image,note].forEach(el=>observer?.observe(el));
  image.addEventListener('load',schedule);window.addEventListener('resize',schedule);schedule();
  return ()=>{observer?.disconnect();image.removeEventListener('load',schedule);window.removeEventListener('resize',schedule);if(frame)cancelAnimationFrame(frame);};
}

const paths={
  focus:'<path d="M8 3H5a2 2 0 0 0-2 2v3m13-5h3a2 2 0 0 1 2 2v3M3 16v3a2 2 0 0 0 2 2h3m8 0h3a2 2 0 0 0 2-2v-3"/><circle cx="12" cy="12" r="3"/>',
  pin:'<path d="m16 3 5 5-4 1-4 4v4l-3-3-5 5m5-5-3-3h4l4-4z"/>',
  link:'<path d="m10 13 4-4m-6 6-2 2a4 4 0 0 1-5-5l5-5a4 4 0 0 1 5 0m2 2 2-2a4 4 0 0 1 5 5l-5 5a4 4 0 0 1-5 0"/>',
  left:'<path d="m14 6-6 6 6 6"/>',right:'<path d="m10 6 6 6-6 6"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  photo:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1"/><path d="m21 15-6-6L3 21"/>',
  message:'<path d="M21 11a9 9 0 0 1-9 9H4l-3 3V11a10 10 0 0 1 20 0Z"/>',
};
export function pinboardIcon(name){
  return `<svg class="pinboard-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]||''}</svg>`;
}
