// Keep the author's place while the editor is rebuilt around saved data.
const views=new Map();
const attributes=['data-action','data-select-step','data-guide','data-move','data-id','data-remove-box'];
function focusSelector(element){
  if(!element)return null;
  if(element.id)return '#'+CSS.escape(element.id);
  if(element.matches('summary'))return element.parentElement.classList.length?'.'+CSS.escape(element.parentElement.classList[0])+' > summary':null;
  const row=element.closest('[data-box-index]');
  if(row){
    const field=element.matches('.box-name')?'.box-name':null;
    if(element.hasAttribute('data-coordinate')){
      const index=[...row.querySelectorAll('[data-coordinate]')].indexOf(element);
      return `[data-box-index="${row.dataset.boxIndex}"] .box-controls label:nth-child(${index+1}) input`;
    }
    if(field)return `[data-box-index="${row.dataset.boxIndex}"] ${field}`;
  }
  const parts=attributes.filter(name=>element.hasAttribute(name)).map(name=>`[${name}="${CSS.escape(element.getAttribute(name))}"]`);
  return parts.length?element.tagName.toLowerCase()+parts.join(''):null;
}
export function rememberEditorView(root){
  const key=root.dataset.editorKey;
  if(!key||root.dataset.busy==='true')return;
  const active=document.activeElement,focused=root.contains(active)?active:null;
  views.set(key,{
    details:[...root.querySelectorAll('details')].map(el=>({selector:'.'+CSS.escape(el.classList[0]),open:el.open})),
    focus:focusSelector(focused),start:focused?.selectionStart,end:focused?.selectionEnd,
    scroll:window.scrollY
  });
}
export function restoreEditorView(root,key,busy){
  root.dataset.editorKey=key;root.dataset.busy=String(busy);
  const view=views.get(key);if(!view)return false;
  for(const item of view.details){const el=root.querySelector(item.selector);if(el)el.open=item.open;}
  if(!busy&&view.focus){
    const original=root.querySelector(view.focus);
    const target=original&&!original.disabled?original:root.querySelector(view.focus.includes('clear-boxes')?'[data-action="add-box"]':'.step-card.selected .step-select');
    if(target&&!target.disabled){
      target.focus({preventScroll:true});
      if(target===original&&typeof view.start==='number'&&target.setSelectionRange)target.setSelectionRange(view.start,view.end);
    }
  }
  window.scrollTo({top:view.scroll,behavior:'instant'});
  return true;
}
