// A selection is always measured on the displayed image, excluding its surround.
export function normalizedPoint(clientX,clientY,rect){
  if(!rect.width||!rect.height||clientX<rect.left||clientX>rect.left+rect.width||clientY<rect.top||clientY>rect.top+rect.height)return null;
  return {x:Math.min(1000,Math.max(0,Math.floor((clientX-rect.left)/rect.width*1000))),y:Math.min(1000,Math.max(0,Math.floor((clientY-rect.top)/rect.height*1000)))};
}
export function selectionOverlay(selection,cursor,escape){
  let result='';
  if(selection){const [left,top]=selection.mask_bounds;result=`<svg class="selection-mask" viewBox="0 0 ${Number(selection.photo_width)} ${Number(selection.photo_height)}" aria-hidden="true"><path transform="translate(${Number(left)} ${Number(top)})" d="${escape(selection.mask_path)}"/></svg>`;}
  if(cursor)result+=`<span class="pick-point" aria-hidden="true" style="left:${cursor.x/10}%;top:${cursor.y/10}%"></span>`;
  return result;
}
export function bindPointPicker(frame,image,{active,cursor,onMove,onCommit,onCancel}){
  if(!active)return;
  frame.classList.add('point-selecting');frame.tabIndex=0;frame.setAttribute('role','button');frame.setAttribute('aria-label','물체의 가운데를 선택하세요. 방향키로 이동하고 Enter로 선택할 수 있습니다.');frame.setAttribute('aria-describedby','selection-help');
  let point={...cursor};
  frame.onclick=event=>{const next=normalizedPoint(event.clientX,event.clientY,image.getBoundingClientRect());if(next)onCommit(next);};
  frame.onkeydown=event=>{
    if(event.key==='Escape'){event.preventDefault();onCancel();return;}
    if(event.key==='Enter'||event.key===' '){event.preventDefault();onCommit(point);return;}
    const direction={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[event.key];if(!direction)return;
    event.preventDefault();const step=event.shiftKey?50:10;point={x:Math.max(0,Math.min(1000,point.x+direction[0]*step)),y:Math.max(0,Math.min(1000,point.y+direction[1]*step))};onMove(point);
    const marker=frame.querySelector('.pick-point');if(marker){marker.style.left=point.x/10+'%';marker.style.top=point.y/10+'%';}
  };
}
