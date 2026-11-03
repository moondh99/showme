import {rememberEditorView,restoreEditorView} from './editor-view.js';
import {bindPointPicker,selectionOverlay} from './selection.js';
import {conversationCache,hasConversation,recentQuestionCount} from './conversation-cache.js';
import {rulePresentation} from './answer-view.js';
import {searchApprovedSteps} from './guide-search.js';
import {bindBoardConnection,highlightPoint,pinboardIcon} from './pinboard.js';
const main=document.querySelector('#main'),notice=document.querySelector('#notice');
const authorLanguage=new URLSearchParams(location.search).get('lang')==='ko'?'ko':'en';
let language=authorLanguage;
const t=(ko,en)=>language==='ko'?ko:en;
const stagedCredit='AI 연출 시연 사진 · 실제 행사 현장 아님';
const photoCredit=credit=>credit===stagedCredit?t(stagedCredit,'AI-staged demonstration photo'):credit;
function setLanguage(locale, demo=false, showSwitch=true){
  language=locale==='en'?'en':'ko';
  document.documentElement.lang=language;
  const subtitle=t('사진으로 전하는 작업 안내','Work guides from photos');
  const brand=document.querySelector('.brand');
  brand.href=t('/?lang=ko','/');
  brand.setAttribute('aria-label',t('ShowMe 홈','ShowMe home'));
  brand.querySelector('.brand-sub').textContent=subtitle;
  document.querySelector('.skip').textContent=t('본문으로 이동','Skip to content');
  document.title='ShowMe — '+subtitle;
  const switcher=document.querySelector('#language-control');
  switcher.hidden=!showSwitch;
  if(showSwitch){
    const link=switcher.querySelector('a');
    link.href=demo?t('/demo?lang=en','/demo?lang=ko'):t('/','/?lang=ko');
    link.lang=t('en','ko');
    link.textContent=t('English','한국어');
  }
}
const S={author:false,guides:[],guide:null,active:null,dirty:false,busy:false,busyText:'',drawing:false,publication:null,gaps:[],demoUrl:null,lastResolvedGap:null};
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const button=(action,text,kind='',extra='')=>`<button type="button" data-action="${action}" class="btn ${kind}" ${extra}>${text}</button>`;
const input=(id,label,value,extra='')=>`<label class="field"><span>${label}</span><input id="${id}" data-edit type="text" value="${esc(value)}" ${extra}></label>`;
const textarea=(id,label,value,extra='')=>`<label class="field"><span>${label}</span><textarea id="${id}" data-edit ${extra}>${esc(value)}</textarea></label>`;
const current=()=>S.guide?.steps.find(s=>s.id===S.active)||S.guide?.steps[0]||null;
const reviewedCount=()=>S.guide?.steps.filter(s=>s.reviewed).length||0;
const allReviewed=()=>S.guide?.steps.length>0&&S.guide.steps.every(s=>s.reviewed)&&!S.dirty;
const newStep=photo=>({id:'step-'+crypto.randomUUID(),photo_id:photo.id,operator_note:'',title:'',instruction:'',completion_check:'',highlights:[],missing_information:[],reviewed:false});
function say(message,error=false){notice.textContent=message;notice.className=`notice visible${error?' error':''}`;}
async function api(path,options={}){
  let response;
  try{response=await fetch(path,{...options,headers:{...(options.body instanceof FormData?{}:{'Content-Type':'application/json'}),...options.headers}});}
  catch{throw new Error(t('서버에 연결하지 못했습니다. 입력은 화면에 남아 있습니다.',"Could not reach the server. Your input is still here."));}
  let data;try{data=await response.json();}catch{throw new Error(t('서버 응답을 읽지 못했습니다. 잠시 뒤 다시 시도해 주세요.',"Could not read the server response. Try again in a moment."));}
  if(!response.ok){
    const detail=data.detail;
    const limit=Array.isArray(detail)&&detail.some(e=>e.type==='too_long'&&e.loc?.includes('steps'));
    const fallback=limit?t('사진은 최대 6장입니다.','You can add up to 6 photos.'):t('제목·메모·강조 위치의 입력 내용을 확인해 주세요.','Check the title, notes, and highlight coordinates.');
    const message=typeof detail==='string'?detail:detail?.message;
    if(language==='en'&&/[가-힣]/.test(message||'')){
      const modelErrors={authentication:'Check the Meta API key on the server.',billing:'Check your Meta API credits.',timeout:'The AI took too long. Try again in a moment.',invalid_response:'Could not verify the AI response. Try again.'};
      const requestErrors={401:'Check your author password or sign in again.',404:'Could not find this item. Reopen the guide and try again.',409:'Another request or edit is in progress. Try again in a moment.',429:'The request limit was reached. You can still read the approved instructions.',502:'The AI service did not respond. Try again in a moment.'};
      throw new Error(modelErrors[detail?.code]||requestErrors[response.status]||fallback);
    }
    throw new Error(message||fallback);
  }
  return data;
}
const json=body=>JSON.stringify(body);
function dirty(global=false){
  S.dirty=true;if(global)S.guide.steps.forEach(s=>s.reviewed=false);else if(current())current().reviewed=false;
  const badge=document.querySelector('#save-state');if(badge){badge.textContent=t('저장하지 않은 변경',"Unsaved changes");badge.classList.add('dirty');}
  const pub=document.querySelector('[data-action="publish"]');if(pub)pub.disabled=true;
  const r=document.querySelector('#review-state');if(r){r.textContent=t('검토 전',"Needs review");r.classList.remove('ok');}
  const count=document.querySelector('#review-count');if(count)count.textContent=`${t("검토 완료 ","Reviewed ")}${reviewedCount()} / ${S.guide.steps.length}`;
  document.querySelectorAll('.step-card').forEach(card=>{
    const step=S.guide.steps.find(s=>s.id===card.dataset.stepCard);
    card.querySelector('.step-status').textContent=step?.reviewed?t('검토 완료',"Reviewed"):step?.instruction?t('검토 전',"Needs review"):t('설명 작성 전',"Awaiting instructions");
  });
}
function capture(){
  if(!S.guide||!document.querySelector('#guide-title'))return;
  S.guide.title=document.querySelector('#guide-title').value;S.guide.goal=document.querySelector('#goal').value;
  const s=current();if(!s||!document.querySelector('#note'))return;
  for(const [field,id] of [['operator_note','note'],['title','step-title'],['instruction','instruction'],['completion_check','completion']])s[field]=document.querySelector('#'+id).value;
  document.querySelectorAll('[data-box-index]').forEach(row=>{
    const index=Number(row.dataset.boxIndex),old=s.highlights[index];
    const box=[...row.querySelectorAll('[data-coordinate]')].map(el=>Number(el.value));const label=row.querySelector('.box-name').value;
    if(label!==old.label||JSON.stringify(box)!==JSON.stringify(old.box))s.highlights[index]={label,box,origin:'author'};
  });
  const missing=document.querySelector('#missing');if(missing)s.missing_information=missing.value.split('\n').map(x=>x.trim()).filter(Boolean);
}
async function refreshList(){S.guides=await api('/api/guides');}
async function persist(){
  const g=S.guide;S.guide=await api('/api/guides/'+g.id,{method:'PUT',body:json({version:g.version,title:g.title,goal:g.goal,steps:g.steps})});
  S.dirty=false;await refreshList();return S.guide;
}
async function save(){capture();return persist();}
async function work(fn,text=t('저장하고 있어요',"Saving…")){
  if(S.busy)return;capture();const before=main.dataset.editorKey;S.busy=true;S.busyText=text;render();
  try{await fn();}catch(error){say(error.message,true);}finally{S.busy=false;render();if(before!==main.dataset.editorKey&&current())main.querySelector(`[data-select-step="${CSS.escape(current().id)}"]`)?.focus({preventScroll:true});}
}
function photo(src,boxes=[],draw=false,dimensions=null,overlay=''){const size=dimensions?.width&&dimensions?.height?` width="${Number(dimensions.width)}" height="${Number(dimensions.height)}"`:"";return `<div id="photo-frame" class="photo-frame ${draw?'drawing':''}"><img id="work-photo" src="${esc(src)}" alt="${t("현재 단계의 작업 사진","Work photo for this step")}" draggable="false"${size}>${boxes.map((h,i)=>`<span class="photo-box" style="left:${h.box[0]/10}%;top:${h.box[1]/10}%;width:${(h.box[2]-h.box[0])/10}%;height:${(h.box[3]-h.box[1])/10}%"><span class="marker">${i+1}</span></span>`).join('')}${overlay}</div>`;}
function sidebar(){return `<aside class="sidebar"><div class="sidebar-heading"><h2>${t("내 안내서","My guides")}</h2><small>${S.guides.length}${t("개"," guides")}</small></div>${button('new',t('＋ 새 안내서',"＋ New guide"),'primary')}<div class="guide-list">${S.guides.map(g=>`<button type="button" class="guide-item ${g.id===S.guide?.id?'active':''}" data-guide="${esc(g.id)}"><strong>${esc(g.title)}</strong><small>${g.steps.filter(s=>s.reviewed).length}/${g.steps.length}${t(" 검토 · "," reviewed · ")}${g.steps.length}${t("단계"," steps")}</small></button>`).join('')}</div><p class="side-note">${t("사진의 순서가 작업의 순서가 됩니다. 각 단계의 설명과 강조 위치를 확인한 뒤 전달해 주세요.","The photo order sets the task order. Review each step and its highlights before sharing.")}</p></aside>`;}
function stepRail(){
  const g=S.guide;
  return `<section class="panel step-sequence"><div class="panel-head"><div><h2>${t("작업 순서","Step order")}</h2><p class="hint">${t("단계를 선택해 메모와 설명을 검토하세요. 화살표로 순서를 바꿀 수 있어요.","Select a step to review its instructions. Use the arrows to reorder steps.")}</p></div><span id="review-count">${t("검토 완료 ","Reviewed ")}${reviewedCount()} / ${g.steps.length}</span></div><ol class="step-rail">${g.steps.map((s,i)=>`<li class="step-card ${s.id===current()?.id?'selected':''}" data-step-card="${esc(s.id)}"><button type="button" class="step-select" data-select-step="${esc(s.id)}" aria-label="${i+1}${t("단계 열기: "," · Open step ")}${esc(s.title||t('설명 작성 전',"Awaiting instructions"))}"><img src="/api/photos/${esc(s.photo_id)}" alt="${i+1}${t("단계 사진"," photo")}"><span class="step-number">${i+1}</span><strong>${esc(s.title||t('설명 작성 전',"Awaiting instructions"))}</strong><small class="step-status">${s.reviewed?t('검토 완료',"Reviewed"):s.instruction?t('검토 전',"Needs review"):t('설명 작성 전',"Awaiting instructions")}</small></button><div class="step-moves"><button type="button" data-move="up" data-id="${esc(s.id)}" aria-label="${i+1}${t("단계 앞으로"," · Move step earlier")}" ${i===0?'disabled':''}>←</button><button type="button" data-move="down" data-id="${esc(s.id)}" aria-label="${i+1}${t("단계 뒤로"," · Move step later")}" ${i===g.steps.length-1?'disabled':''}>→</button><button type="button" data-delete-step="${esc(s.id)}" aria-label="${i+1}${t("단계 삭제"," · Delete step")}">${t("삭제","Delete")}</button></div></li>`).join('')}</ol><div class="sequence-actions"><label class="btn file-label ${g.steps.length>=6?'at-limit':''}"><input class="file-input" id="photos-add" type="file" accept="image/jpeg,image/png,image/webp" multiple ${g.steps.length>=6?'disabled':''}>${t("＋ 사진 추가 (","＋ Add photos (")}${g.steps.length}/6)</label>${button('sample',t('샘플 사진 추가',"Add sample photo"),'',g.steps.length>=6?'disabled':'')}${button('generate-all',t('미작성 단계 AI 초안 만들기',"Draft unwritten steps with AI"),'',g.steps.length?'':'disabled')}</div>${g.steps.length===6?t('<p class="hint">사진 6장을 모두 등록했습니다. 사진을 바꾸거나 단계를 삭제할 수 있어요.</p>',"<p class=\"hint\">All 6 photo slots are in use. Replace or remove a photo to continue.</p>"):''}</section>`;
}
function boxEditor(){return current().highlights.map((h,i)=>`<div class="box-editor" data-box-index="${i}"><div class="box-row"><strong>${t("강조 ","Highlight ")}${i+1}</strong><button type="button" class="btn quiet danger" data-remove-box="${i}">${t("삭제","Delete")}</button></div><input class="box-name" data-edit aria-label="${t("강조 ","Highlight ")}${i+1}${t(" 이름"," name")}" value="${esc(h.label)}" maxlength="100"><div class="box-controls">${[t('왼쪽',"Left"),t('위쪽',"Top"),t('오른쪽',"Right"),t('아래쪽',"Bottom")].map((label,n)=>`<label>${label}<input data-edit data-coordinate type="number" min="0" max="1000" step="1" value="${h.box[n]}" aria-label="${t("강조 ","Highlight ")}${i+1} ${label}"></label>`).join('')}</div></div>`).join('');}
function editor(){
  const g=S.guide,s=current(),hasDraft=Boolean(s?.instruction),pub=S.publication||g.latest_publication,index=g.steps.findIndex(x=>x.id===s?.id);
  return `<section class="content"><div class="page-head"><div><p class="eyebrow">${t("작업 안내서 만들기","Build a photo guide")}</p><h1>${esc(g.title)}</h1><p>${t("사진을 순서대로 놓고, 단계마다 다음 사람이 할 일을 알려주세요.","Put the photos in order and explain what to do at each step.")}</p></div><span id="save-state" class="save-state ${S.dirty?'dirty':''}">${S.dirty?t('저장하지 않은 변경',"Unsaved changes"):t('저장됨',"Saved")}</span></div><ol class="steps" aria-label="${t("작성 과정","Authoring progress")}"><li class="${!hasDraft?'active':''}"><b>1</b>${t(" 사진과 메모"," Photos and notes")}</li><li class="${hasDraft&&!allReviewed()?'active':''}"><b>2</b>${t(" 단계별 검토"," Step review")}</li><li class="${allReviewed()?'active':''}"><b>3</b>${t(" 전체 승인"," Publish")}</li></ol><details class="guide-settings-wrap"><summary>${t("안내서 제목·작업 목표 수정","Edit guide title and goal")}</summary><section class="panel guide-settings">${input('guide-title',t('안내서 제목',"Guide title"),g.title,'maxlength="120"')}${textarea('goal',t('작업 목표',"Task goal"),g.goal,'maxlength="1000" rows="2"')}</section></details>${stepRail()}${S.busy?`<div class="busy-note" role="status"><span class="spinner" aria-hidden="true"></span>${esc(S.busyText)}</div>`:''}
  ${s?`<div class="editor"><div><section class="panel"><div class="panel-head"><h2>${index+1}${t("단계 사진"," · Step photo")}</h2><span>${index+1} / ${g.steps.length}${t(" 단계"," steps")}</span></div>${photo('/api/photos/'+s.photo_id,s.highlights,S.drawing,g.photo_dimensions?.[s.photo_id])}<div class="photo-toolbar"><label class="btn file-label"><input class="file-input" id="photo-replace" type="file" accept="image/jpeg,image/png,image/webp">${t("이 단계 사진 바꾸기","Replace photo")}</label>${button('draw',S.drawing?t('사진에서 대각선으로 그려 주세요',"Draw diagonally across the photo"):t('강조 영역 그리기',"Draw highlight"),S.drawing?'primary':'')}${button('add-box',t('강조 영역 추가',"Add highlight"),'',s.highlights.length>=8?'disabled':'')}${s.highlights.length?button('clear-boxes',t('강조 모두 지우기',"Clear highlights"),'quiet'):''}</div><p class="credit">${esc(photoCredit(g.photo_credits?.[s.photo_id])||t('등록한 사진은 이 단계의 설명과 함께 사용됩니다.',"The photo is part of this step."))}</p><p class="hint">${t("사진에서 영역을 그리거나 ‘강조 영역 추가’로 만든 뒤 이름과 위치를 수정하세요. 최대 8개까지 추가할 수 있어요.","Draw on the photo or add a highlight and adjust it. You can add up to 8 highlights.")}</p><details class="advanced-boxes"><summary>${t("위치 세부 설정 · ","Fine-tune positions · ")}${s.highlights.length}${t("개 영역"," highlights")}</summary><p class="hint">${t("정밀 조정이 필요할 때 좌표를 수정하세요. 기본 조작은 사진에서 할 수 있어요.","Use the coordinates for precise adjustments.")}</p>${boxEditor()}</details></section></div>
  <section class="panel"><div class="panel-head"><h2>${index+1}${t("단계 설명 검토"," · Review instructions")}</h2><span id="review-state" class="status-pill ${s.reviewed?'ok':''}">${s.reviewed?t('검토 완료',"Reviewed"):t('검토 전',"Needs review")}</span></div><div class="generation-input"><h3>${t("이 단계의 행동 메모","Notes for this step")}</h3><p class="hint">${t("할 일과 지켜야 할 기준을 적어 주세요. 사진에 없는 규칙은 메모를 바탕으로 설명합니다.","Describe the action and any rules. The draft uses these notes for rules the photo cannot establish.")}</p><div style="margin-top:16px">${textarea('note',t('행동 메모',"Operator notes"),s.operator_note,t('maxlength="3000" rows="4" placeholder="예: 검은 펜을 노트 위에 준비합니다. 펜은 참가자 서명용입니다."',"maxlength=\"3000\" rows=\"4\" placeholder=\"Example: Place the black pen on the pad. Attendees use it to sign in.\""))}</div>${button('generate',hasDraft?t('이 단계 AI 초안 다시 만들기',"Regenerate this step with AI"):t('이 단계 AI 초안 만들기',"Draft this step with AI"),'primary generate-button')}<p class="hint">${t("현재 단계의 사진과 메모로 생성합니다. 다른 단계의 수정 내용은 유지됩니다.","Uses this step’s photo and notes. Changes to other steps stay saved.")}</p></div><div class="divider"></div>${s.missing_information.length?`<div class="missing"><strong>${t("담당자 확인이 필요해요","Supervisor input needed")}</strong><p>${t("메모나 설명에 반영한 항목을 목록에서 지워 주세요.","Remove each item after addressing it in the notes or instructions.")}</p><textarea id="missing" data-edit aria-label="${t("아직 확인할 내용","Open questions")}">${esc(s.missing_information.join('\n'))}</textarea></div>`:''}${input('step-title',t('단계 제목',"Step title"),s.title,t('maxlength="120" placeholder="예: 서명용 펜 준비하기"',"maxlength=\"120\" placeholder=\"Example: Set out the signing pen\""))}${textarea('instruction',t('할 일',"Instructions"),s.instruction,t('maxlength="3000" rows="5" placeholder="AI 초안을 만들거나 직접 설명을 적어 주세요."',"maxlength=\"3000\" rows=\"5\" placeholder=\"Generate a draft with AI or write the instructions here.\""))}${textarea('completion',t('완료 확인',"Completion check"),s.completion_check,t('maxlength="500" rows="2" placeholder="이 단계가 끝났을 때 무엇을 확인하나요?"',"maxlength=\"500\" rows=\"2\" placeholder=\"What should staff check when this step is done?\""))}<div class="review-actions">${button('save',t('수정 내용 저장',"Save changes"))}${button('review',s.reviewed?t('이 단계 검토 완료됨',"Step reviewed"):t('이 단계 검토 완료',"Mark step reviewed"),'',hasDraft?'':'disabled')}</div><p class="hint">${t("설명과 강조 위치를 확인해 주세요. 내용이나 순서를 바꾸면 해당 단계는 다시 검토해야 합니다.","Review the instructions and highlights. Changes to the content or order require a new review.")}</p></section></div>`:`<section class="photo-empty"><strong>${t("작업 사진을 순서대로 등록하세요.","Add the work photos in order.")}</strong><p>${t("최대 6장을 한 번에 선택할 수 있습니다. 등록 후에도 순서를 바꿀 수 있어요.","Select up to 6 photos. You can reorder them later.")}</p></section>`}
  ${learningGaps()}<section class="approval"><div><h3>${t("모든 단계를 하나의 승인본으로","Publish an approved guide")}</h3><p>${reviewedCount()} / ${g.steps.length}${t("단계 검토 완료. 승인본은 사진·순서·설명을 함께 고정합니다."," steps reviewed. Publication freezes the photos, order, and instructions.")}</p></div>${button('publish',t('전체 승인본 만들기',"Publish approved guide"),'primary',allReviewed()?'':'disabled')}</section>${pub?`<section class="share"><h3>${t("승인본 ","Approved version ")}${pub.revision_number}${t("이 저장됐습니다"," saved")}</h3><p class="small">${t("이후 초안 수정이나 순서 변경은 기존 승인본에 영향을 주지 않습니다.","Draft edits and reordering leave this approved version intact.")}</p><div class="share-row"><input id="share-link" readonly aria-label="${t("학습 링크","Learner link")}" value="${esc(location.origin+pub.url)}">${button('copy',t('링크 복사',"Copy link"))}<a class="btn" href="${esc(pub.url)}" target="_blank" rel="noopener">${t("승인본 열기 ↗","Open approved guide ↗")}</a></div></section>`:''}</section>`;
}
function learningGaps(){
  const undo=S.lastResolvedGap?.guideId===S.guide.id?`<button class="btn small" type="button" data-undo-gap="${esc(S.lastResolvedGap.id)}">${t("방금 완료 표시 되돌리기","Undo last resolution")}</button>`:'';
  return `<details class="learning-gaps" ${S.gaps.length?'open':''}><summary>${t("검토할 보완 질문 · ","Questions to review · ")}${S.gaps.length}${t("개","")}</summary><p class="hint">${t("답하지 못한 질문은 검토 완료로 표시하거나 승인 규칙 재확인에서 답을 찾을 때까지 남아요. 내용을 보완하고 새 승인본에 반영했는지 확인해 주세요. 기존 승인본은 유지됩니다.","Open questions stay here until reviewed or answered from approved rules. Publish a new version after addressing them to share the updated instructions.")}</p>${button('refresh-gaps',t('질문 새로 확인',"Refresh questions"),'quiet')}${undo}${S.gaps.length?`<ul>${S.gaps.map(g=>`<li><strong>${esc(g.question)}</strong><span>${esc(g.step_title)}</span><button class="btn small" type="button" data-select-step="${esc(g.step_id)}" ${S.guide.steps.some(s=>s.id===g.step_id)?'':'disabled'}>${t("이 단계 보완하기","Edit this step")}</button><button class="btn small" type="button" data-resolve-gap="${esc(g.id)}">${t("검토 완료로 표시","Mark reviewed")}</button></li>`).join('')}</ul>`:t('<p class="small">미처리 보완 질문이 없어요. 사용자 검증이 완료되었다는 뜻은 아니에요.</p>',"<p class=\"small\">There are no open questions to review.</p>")}</details>`;
}
function demoEntry(){return S.demoUrl?`<a class="btn demo-entry" href="${esc(S.demoUrl)}">${t("사진에서 골라 묻기 · 데모 체험","Try the interactive demo")}</a><p class="small">${t("로그인 없이 볼 수 있어요. AI 연출 사진을 사용한 가상 작업입니다.","Explore an AI-staged example without signing in.")}</p>`:'';}
function render(){
  rememberEditorView(main);
  document.querySelector('#session-control').innerHTML=S.author?button('logout',t('로그아웃',"Sign out"),'quiet'):'';
  if(!S.author){main.innerHTML=`<section class="login"><p class="eyebrow">${t("작성자 작업 공간","Author workspace")}</p><h1>${t("노하우를 사진으로","Turn work photos")}<br>${t("전해 주세요.","into step-by-step guides.")}</h1><p>${t("사진 속 물체를 가리켜 묻고,","Point to an object in a photo")}<br>${t("담당자가 정한 작업 규칙을 찾아보세요.","and find the rules your supervisor approved.")}</p>${demoEntry()}<form id="login"><label class="field"><span>${t("작성자 비밀번호","Author password")}</span><input id="password" type="password" autocomplete="current-password" required></label><button type="submit" class="btn primary">${t("작업 공간 열기","Open workspace")}</button></form></section>`;return;}
  main.innerHTML=`<div class="workspace">${sidebar()}${S.guide?editor():`<section class="content"><div class="empty-intro"><div class="empty-symbol" aria-hidden="true">↗</div><div><p class="eyebrow">${t("사진에서 시작하는 인수인계","Hand over a task with photos")}</p><h1>${t("순서가 있는 노하우를 전하세요.","Share a procedure in order.")}</h1><p>${t("사진을 최대 6장 등록하고, 각 단계의 설명과 강조 위치를 검토해 안내서로 만드세요.","Add up to 6 photos, then review each step’s instructions and highlights before publishing.")}</p>${button('new',t('새 안내서 만들기',"Create a guide"),'primary')}${demoEntry()}</div></div></section>`}</div>`;
  if(S.busy)main.querySelectorAll('button,input,textarea').forEach(el=>el.disabled=true);
  const key=S.guide?S.guide.id+':'+(current()?.id||'empty'):'';
  const restored=restoreEditorView(main,key,S.busy);
  if(!S.busy&&S.guide&&!restored){
    const target=main.querySelector(`[data-select-step="${CSS.escape(current()?.id||'')}"]`)||main.querySelector('#photos-add');
    target?.focus({preventScroll:true});
  }
  bindDrawing();
}
function bindDrawing(){
  const frame=document.querySelector('#photo-frame');if(!frame||!S.drawing)return;let start=null,temp=null;
  const position=e=>{const r=frame.getBoundingClientRect();return [Math.max(0,Math.min(1000,Math.round((e.clientX-r.left)/r.width*1000))),Math.max(0,Math.min(1000,Math.round((e.clientY-r.top)/r.height*1000)))];};
  frame.onpointerdown=e=>{if(S.busy)return;start=position(e);frame.setPointerCapture(e.pointerId);temp=document.createElement('span');temp.className='photo-box';frame.append(temp);};
  frame.onpointermove=e=>{if(!start)return;const p=position(e);Object.assign(temp.style,{left:Math.min(start[0],p[0])/10+'%',top:Math.min(start[1],p[1])/10+'%',width:Math.abs(start[0]-p[0])/10+'%',height:Math.abs(start[1]-p[1])/10+'%'});};
  frame.onpointerup=e=>{if(!start)return;capture();const p=position(e),box=[Math.min(start[0],p[0]),Math.min(start[1],p[1]),Math.max(start[0],p[0]),Math.max(start[1],p[1])];start=null;if(box[2]-box[0]<5||box[3]-box[1]<5){temp?.remove();say(t('조금 더 넓은 영역을 그려 주세요.',"Draw a slightly larger area."),true);return;}if(current().highlights.length>=8){temp?.remove();say(t('강조 영역은 최대 8개입니다.',"You can add up to 8 highlights."),true);return;}current().highlights.push({label:t('강조할 물건',"Object to highlight"),box,origin:'author'});S.drawing=false;dirty();render();};
  frame.onpointercancel=()=>{start=null;temp?.remove();};
}
async function addPhotos(files,replace=false){
  const capacity=6-S.guide.steps.length;
  if(!replace&&files.length>capacity){say(`${t("사진은 최대 6장입니다. 지금은 ","You can add up to 6 photos. Remaining slots: ")}${capacity}${t("장 더 등록할 수 있어요.",".")}`,true);return;}
  if(files.some(f=>f.size>10*1024*1024)){say(t('사진은 한 장당 10MB 이하로 선택해 주세요.',"Choose photos no larger than 10 MB each."),true);return;}
  await work(async()=>{
    let added=0;
    try{for(const file of files){
      const form=new FormData();form.append('file',file);const result=await api('/api/photos',{method:'POST',body:form});
      if(replace){const s=current();Object.assign(s,{photo_id:result.id,title:'',instruction:'',completion_check:'',highlights:[],missing_information:[],reviewed:false});}
      else{const step=newStep(result);S.guide.steps.push(step);S.active=step.id;}
      added++;S.dirty=true;S.drawing=false;
    }}finally{if(added)await persist();}
    say(replace?t('이 단계 사진을 바꿨습니다. 설명과 강조 위치를 다시 검토해 주세요.',"Photo replaced. Review the instructions and highlights for this step."):`${added}${t("장의 사진을 등록했습니다. 순서와 단계별 메모를 확인해 주세요."," photos added. Check their order and step notes.")}`);
  },replace?t('사진을 바꾸고 있어요',"Replacing the photo…"):t('작업 사진을 등록하고 있어요',"Uploading work photos…"));
}
async function action(name){
  if(name==='new'){if(S.dirty&&!confirm(t('저장하지 않은 변경이 있습니다. 새 안내서를 만들까요?',"You have unsaved changes. Create a new guide?")))return;return work(async()=>{S.guide=await api('/api/guides',{method:'POST',body:json({title:t('새 작업 안내서',"New work guide"),goal:'',language})});S.active=null;S.dirty=false;S.publication=null;S.gaps=[];await refreshList();});}
  if(name==='logout'){if(S.dirty&&!confirm(t('저장하지 않은 변경이 있습니다. 로그아웃할까요?',"You have unsaved changes. Sign out?")))return;await api('/api/session',{method:'DELETE'});Object.assign(S,{author:false,guide:null,active:null,dirty:false});render();return;}
  if(name==='copy'){const value=document.querySelector('#share-link').value;try{await navigator.clipboard.writeText(value);say(t('학습 링크를 복사했습니다.',"Learner link copied."));}catch{document.querySelector('#share-link').select();say(t('선택된 링크를 복사해 주세요.',"Copy the selected link."));}return;}
  if(name==='refresh-gaps')return work(async()=>{S.gaps=await api('/api/guides/'+S.guide.id+'/learning-gaps');});
  capture();
  if(name==='sample'){if(S.guide.steps.length>=6){say(t('사진은 최대 6장입니다.',"You can add up to 6 photos."),true);return;}return work(async()=>{const p=await api('/api/photos/sample',{method:'POST'}),s=newStep(p);S.guide.steps.push(s);S.active=s.id;S.dirty=true;await persist();say(t('샘플 사진을 단계로 등록했습니다.',"Sample photo added."));},t('샘플 사진을 등록하고 있어요',"Adding the sample photo…"));}
  if(name==='add-box'){
    if(current().highlights.length>=8){say(t('강조 영역은 최대 8개입니다.',"You can add up to 8 highlights."),true);return;}
    current().highlights.push({label:t('강조할 물건',"Object to highlight"),box:[250,250,750,750],origin:'author'});
    S.drawing=false;dirty();render();
    main.querySelector('.advanced-boxes').open=true;
    main.querySelector('.box-editor:last-child .box-name').focus();
    say(t('사진 가운데에 강조 영역을 추가했습니다. 이름과 위치를 수정해 주세요.',"Highlight added. Adjust its name and position."));return;
  }
  if(name==='draw'){S.drawing=!S.drawing;render();return;}
  if(name==='clear-boxes'){current().highlights=[];dirty();render();return;}
  if(name==='save')return work(async()=>{await persist();say(t('안내서의 수정 내용을 저장했습니다.',"Guide changes saved."));});
  if(name==='generate'){
    if(!current().operator_note.trim()){say(t('이 단계에서 할 행동을 메모에 적어 주세요.',"Enter the action for this step in the notes."),true);document.querySelector('#note')?.focus();return;}
    if(current().instruction&&!confirm(t('현재 단계의 설명을 새 AI 초안으로 바꿀까요?',"Replace this step’s instructions with a new AI draft?")))return;
    const id=current().id;
    return work(async()=>{await persist();S.guide=await api(`/api/guides/${S.guide.id}/steps/${id}/generate`,{method:'POST',body:json({version:S.guide.version})});S.dirty=false;await refreshList();say(t('이 단계의 AI 초안을 저장했습니다. 설명과 강조 위치를 확인해 주세요.',"AI draft saved. Review its instructions and highlights."));},t('현재 단계의 사진과 메모를 읽고 있어요',"Reading the photo and notes for this step…"));
  }
  if(name==='generate-all'){
    const ids=S.guide.steps.filter(s=>!s.instruction).map(s=>s.id);if(!ids.length){say(t('모든 단계에 설명이 있습니다. 수정한 내용은 그대로 유지합니다.',"All steps have instructions. Your edits are saved."));return;}
    const missing=S.guide.steps.findIndex(s=>ids.includes(s.id)&&!s.operator_note.trim());if(missing>=0){S.active=S.guide.steps[missing].id;render();say(`${missing+1}${t("단계의 행동 메모를 먼저 적어 주세요."," · Add operator notes for this step first.")}`,true);main.querySelector('#note')?.focus();return;}
    return work(async()=>{await persist();let completed=0;for(const id of ids){S.active=id;S.busyText=`${t("미작성 단계 설명 생성 중 · ","Drafting unwritten steps · ")}${completed} / ${ids.length}${t(" 완료"," complete")}`;render();S.guide=await api(`/api/guides/${S.guide.id}/steps/${id}/generate`,{method:'POST',body:json({version:S.guide.version})});completed++;}S.dirty=false;await refreshList();say(`${completed}${t("단계의 AI 초안을 저장했습니다. 단계마다 검토해 주세요."," AI drafts saved. Review each step.")}`);},t('미작성 단계 설명을 만들고 있어요',"Drafting unwritten steps…"));
  }
  if(name==='review')return work(async()=>{await persist();const s=current();if(!s.title||!s.instruction||!s.completion_check||s.missing_information.length)throw new Error(t('이 단계의 제목·설명·완료 확인을 채우고, 확인할 내용을 보완해 주세요.',"Add a title, instructions, and a completion check, then address the open questions."));s.reviewed=true;await persist();say(`${S.guide.steps.findIndex(x=>x.id===s.id)+1}${t("단계 검토를 완료했습니다. ("," · Step reviewed (")}${reviewedCount()}/${S.guide.steps.length})`);});
  if(name==='publish')return work(async()=>{if(!allReviewed())throw new Error(t('모든 단계의 수정 내용을 저장하고 검토를 완료해 주세요.',"Save and review every step before publishing."));S.publication=await api(`/api/guides/${S.guide.id}/publish`,{method:'POST',body:json({version:S.guide.version})});await refreshList();say(t('전체 단계의 순서와 내용을 승인본으로 저장했습니다.',"Approved guide saved with all steps in order."));},t('전체 승인본을 저장하고 있어요',"Saving the approved guide…"));
}
document.addEventListener('input',e=>{if(e.target.matches('[data-edit]')&&S.guide)dirty(['guide-title','goal'].includes(e.target.id));});
document.addEventListener('change',async e=>{if(['photos-add','photo-replace'].includes(e.target.id)&&e.target.files.length)await addPhotos([...e.target.files],e.target.id==='photo-replace');});
document.addEventListener('click',async e=>{
  const t=e.target.closest('[data-action],[data-guide],[data-select-step],[data-move],[data-delete-step],[data-remove-box],[data-resolve-gap],[data-undo-gap]');if(!t||S.busy)return;
  try{
    if(t.dataset.action)await action(t.dataset.action);
    if(t.dataset.resolveGap||t.dataset.undoGap){
      const id=t.dataset.resolveGap||t.dataset.undoGap,resolved=Boolean(t.dataset.resolveGap);
      await work(async()=>{await api(`/api/guides/${S.guide.id}/learning-gaps/${encodeURIComponent(id)}/resolve`,{method:'POST',body:json({resolved})});S.lastResolvedGap=resolved?{id,guideId:S.guide.id}:null;S.gaps=await api(`/api/guides/${S.guide.id}/learning-gaps`);});
      say(resolved?t('보완 질문을 검토 완료로 표시했습니다.',"Question marked reviewed."):t('보완 질문을 미처리 목록으로 되돌렸습니다.',"Question reopened."));
    }
    if(t.dataset.guide){if(S.dirty&&!confirm(t('저장하지 않은 변경이 있습니다. 다른 안내서를 열까요?',"You have unsaved changes. Open a different guide?")))return;await work(async()=>{S.guide=await api('/api/guides/'+t.dataset.guide);S.gaps=await api('/api/guides/'+t.dataset.guide+'/learning-gaps');S.active=S.guide.steps[0]?.id;S.publication=null;S.dirty=false;S.drawing=false;});}
    if(t.dataset.selectStep){capture();await work(async()=>{if(S.dirty)await persist();S.active=t.dataset.selectStep;S.drawing=false;});}
    if(t.dataset.move){capture();const old=S.guide.steps.map(s=>s.id),i=old.indexOf(t.dataset.id),j=i+(t.dataset.move==='up'?-1:1);if(j<0||j>=old.length)return;[S.guide.steps[i],S.guide.steps[j]]=[S.guide.steps[j],S.guide.steps[i]];S.guide.steps.forEach((s,n)=>{if(s.id!==old[n])s.reviewed=false;});S.dirty=true;render();say(t('작업 순서를 바꿨습니다. 순서가 바뀐 단계는 다시 검토해 주세요.',"Step order updated. Review the steps that moved."));}
    if(t.dataset.deleteStep){if(!confirm(t('이 단계를 초안에서 삭제할까요? 기존 승인본은 유지됩니다.',"Remove this step from the draft? Existing approved versions will stay available.")))return;capture();const old=S.guide.steps.map(s=>s.id);S.guide.steps=S.guide.steps.filter(s=>s.id!==t.dataset.deleteStep);S.guide.steps.forEach((s,i)=>{if(old[i]!==s.id)s.reviewed=false;});if(S.active===t.dataset.deleteStep)S.active=S.guide.steps[0]?.id;S.dirty=true;S.drawing=false;render();}
    if(t.dataset.removeBox!==undefined){capture();current().highlights.splice(Number(t.dataset.removeBox),1);dirty();render();main.querySelector('.advanced-boxes').open=true;main.querySelector('[data-action="add-box"]').focus();}
  }catch(error){say(error.message,true);}
});
document.addEventListener('submit',async e=>{
  if(e.target.id!=='login')return;e.preventDefault();const password=document.querySelector('#password').value,submit=e.target.querySelector('button');submit.disabled=true;
  try{await api('/api/session',{method:'POST',body:json({password})});S.author=true;await refreshList();render();notice.className='notice';}catch(error){say(error.message,true);submit.disabled=false;}
});
window.addEventListener('beforeunload',e=>{if(S.dirty){e.preventDefault();e.returnValue='';}});
async function learner(shareId){
  try{
    const r=await api('/api/learn/'+encodeURIComponent(shareId));
    setLanguage(r.language, true, r.demo);
    let index=0,done=[],searchQuery='';
    let stopBoardConnection=()=>{},renderedStepId;
    const cache=conversationCache(shareId);
    const questions=new Map(r.steps.map(({id})=>{
      const saved=cache.read(id);
      return [id,{items:[],draft:'',parent:null,selection:null,expiresAt:null,interrupted:false,
        ...saved,restored:Boolean(saved),busy:false,error:'',location:null,selectionBusy:false,selectionError:'',
        selectMode:false,showConnection:true,cursor:{x:500,y:500}}];
    }));
    const stateFor=id=>questions.get(id);
    const statusName={needs_clarification:t('대상을 확인해 주세요',"Clarify the object"),not_visible:t('사진에서 확인하지 못했어요',"Could not identify it in the photo"),insufficient_information:t('이 단계에 답할 규칙이 없어요',"This step has no rule that answers the question")};
    const sourceName={photo:t('사진에 대한 AI 관찰',"AI observation from the photo"),instruction:t('승인된 설명 원문',"Approved instructions"),completion_check:t('승인된 완료 확인 원문',"Approved completion check")};
    const key='showme:progress:'+shareId;
    try{const saved=JSON.parse(localStorage.getItem(key)||'{}');done=(saved.completed||[]).filter(id=>r.steps.some(s=>s.id===id));index=Math.max(0,r.steps.findIndex(s=>s.id===saved.current));if(r.steps.length===1&&localStorage.getItem('showme:complete:'+shareId)==='1')done=[r.steps[0].id];}catch{}
    function remember(){try{localStorage.setItem(key,json({completed:done,current:r.steps[index].id}));}catch{}}
    const conditionNames={met:t('판정에 사용한 승인 기준',"Approved rule used in the decision"),not_met:t('진행 기준과 맞지 않는 부분',"Requirement not met"),unknown:t('추가 확인이 필요한 기준',"Requirement still to confirm")};
    const quoteLabel=c=>({basis:t('진행 불가 근거',"Reason for blocking"),other_target:t('다른 대상에 적용되는 기준',"Rule for a different object")})[c.role]||
      (c.role==='condition'||c.state!=='met'?conditionNames[c.state]:t('관련 승인 문장',"Related approved text"));
    function assessmentCard(a,presentation){
      const v=a.assessment;if(a.status!=='answered'||!v||v.decision==='visual')return '';
      const verdicts={
        policy:t('승인된 용도',"Approved purpose"),
        allowed:t('질문에 적힌 조건에서 가능해요',"Allowed in the scenario described"),
        blocked:t('질문에 적힌 상황에서는 진행할 수 없어요',"Do not proceed in the scenario described"),
        conditional:t('조건을 더 확인해야 해요',"Confirm the required conditions")
      };
      const headline=presentation.reason?`${t("진행 불가. ","Do not proceed. ")}${presentation.reason}`:verdicts[v.decision]||t('판단 근거를 확인하세요',"Review the decision and its sources");
      return `<section class="rule-assessment" aria-label="${t("대상·조건 확인","Object and conditions")}"><h3 tabindex="-1">${esc(v.target)} · ${esc(headline)}</h3>${presentation.unmapped.length?`<ul>${presentation.unmapped.map(c=>`<li><span class="condition-state">${esc(quoteLabel(c))}</span><p>${esc(c.detail)}</p></li>`).join('')}</ul>`:''}<p class="small">${v.decision==='policy'?t('물체와 승인된 용도의 연결은 AI가 해석했어요.',"The AI linked the object to its approved purpose."):t('질문에 적힌 상황을 가정한 AI 판단이에요. 실제 조건은 현장에서 확인해 주세요.',"This AI assessment uses the facts in your question. Verify the conditions on site.")}</p></section>`;
    }
    function approvedContext(presentation,id){
      if(!presentation.contexts.length)return '';
      return `<section class="approved-answer-context" aria-label="${t("함께 확인할 승인 문맥","Full approved context")}"><h3>${t("판정 근거 · 승인 원문 전체","Decision and full approved text")}</h3>${presentation.contexts.map(context=>`<h4>${sourceName[context.source]}</h4>${context.conditions.length?`<ul class="rule-key">${context.conditions.map(c=>`<li><a id="${id}-key-${c.index}" ${c.role==='other_target'?'class="other-target-quote"':''} href="#${id}-quote-${c.index}">${c.index+1} · ${esc(quoteLabel(c))}</a></li>`).join('')}</ul>`:''}<p class="full-approved-context">${context.segments.map(segment=>`${segment.starts.map(index=>`<span class="quote-anchor" id="${id}-quote-${index}"></span>`).join('')}${segment.conditions.length?`<mark${segment.otherTarget?' class="other-target-quote"':''} aria-describedby="${segment.conditions.map(index=>`${id}-key-${index}`).join(' ')}">${esc(segment.text)}</mark>`:esc(segment.text)}`).join('')}</p>`).join('')}</section>`;
    }
    function answerCard(item,i,q,step){
      const a=item.response,approved=a?.evidence.some(e=>e.source!=='photo'),presentation=a?rulePresentation(a):null,position=Math.max(0,q.items.length-recentQuestionCount)+i,turnId='answer-'+position;
      const label=a?.status==='answered'?(approved?t('관련 승인 문장',"Related approved text"):t('사진을 보고 답한 AI 응답',"AI answer from the photo")):a?.status==='insufficient_information'&&item.intent==='appearance'?t('사진에서 답할 정보를 확인하지 못했어요',"The photo does not show enough to answer"):statusName[a?.status];
      return `<article class="question-turn"><p class="question-text"><b>${t("질문","Question")}</b> ${esc(item.question)}</p>${item.selection?t('<p class="selection-context">사진에서 선택한 물체에 대한 질문</p>',"<p class=\"selection-context\">Question about the selected object</p>"):''}${a?`
        <p class="answer-status" tabindex="-1">${approved&&presentation.contexts.length?t('승인 원문을 기준으로 한 AI 판정',"AI assessment based on approved text"):label}</p>${assessmentCard(a,presentation)}${presentation.showAnswer?`<p class="answer-text">${esc(a.answer)}</p>`:''}
        ${approved&&!a.assessment?t('<p class="answer-boundary">대상 연결은 AI 해석입니다. 표시된 근거와 전체 승인 문맥을 함께 확인하세요.</p>',"<p class=\"answer-boundary\">The AI identified the object. Review the evidence and full approved context.</p>"):''}
        ${approvedContext(presentation,turnId)}
        ${item.selection||a.highlights.length?`<button type="button" class="btn small answer-location-shortcut" data-answer-location="${position}" ${q.busy||q.selectionBusy?'disabled':''}>${item.selection?`<span class="answer-photo-thumb"><img src="/api/learn/${encodeURIComponent(shareId)}/steps/${encodeURIComponent(step.id)}/photo" alt="" width="${step.photo_width}" height="${step.photo_height}">${selectionOverlay(item.selection,item.selection.point,esc)}</span>`:pinboardIcon('photo')}${item.selection?t('이 질문의 선택 다시 보기',"Show the object selected for this question"):t('이 답변의 위치 보기',"Show the location from this answer")}</button>`:''}
        ${a.recovered_gap_id?t('<p class="recovery-note" role="status">승인 규칙에서 답을 찾았어요. 연결된 보완 질문도 해결로 반영했습니다.</p>',"<p class=\"recovery-note\" role=\"status\">Found an answer in the approved rules. The related open question is now resolved.</p>"):''}
        ${item.recoveredBy?t('<p class="recovery-note">아래 재확인 답변에서 해결했어요.</p>',"<p class=\"recovery-note\">Resolved by the follow-up answer below.</p>"):''}
        ${a.evidence.length&&!approved?`<details class="answer-sources" id="${turnId}-sources"><summary>${t("사진 관찰 근거 보기","Show photo observations")}</summary><ul class="answer-evidence">${a.evidence.map(e=>`<li><b>${sourceName[e.source]}</b> · ${esc(e.detail)}</li>`).join('')}</ul></details>`:''}
        ${a.status==='insufficient_information'?`${(item.intent==='appearance'||item.recheckOf)&&!item.recoveredBy?`<button type="button" class="btn small" data-rule-reask="${position}" ${q.busy||q.selectionBusy?'disabled':''}>${t("승인 규칙에서 다시 확인","Recheck against the approved rules")}</button>`:''}<button type="button" class="btn small" data-open-search>${t("다른 단계의 승인 설명에서 찾기","Search the approved instructions in other steps")}</button>`:''}
        <a class="ask-again-link" href="#question-form">${t("이어서 질문하기","Ask another question")}</a>`:t('<div class="answer-pending" role="status" tabindex="-1"><p><span class="spinner" aria-hidden="true"></span>사진과 승인 규칙을 확인하고 있어요…</p><p class="small">기다리는 동안 승인 메모를 읽거나 다른 단계로 이동할 수 있어요.</p></div>',"<div class=\"answer-pending\" role=\"status\" tabindex=\"-1\"><p><span class=\"spinner\" aria-hidden=\"true\"></span>Checking the photo and approved rules…</p><p class=\"small\">You can read the approved notes or move to another step while you wait.</p></div>")}</article>`;
    }
    function questionPanel(s){
      const q=stateFor(s.id),blocked=q.busy||q.selectionBusy||q.selectMode,options=q.parent&&!blocked?(q.items.at(-1)?.response?.clarification_options||[]):[];
      return `<section class="question-panel" aria-labelledby="question-heading">
        <h2 id="question-heading" tabindex="-1">${q.selection?t('선택한 물체에 질문하세요',"Ask about the selected object"):t('이름을 몰라도, 가리켜 물어보세요',"Point to an object and ask")}</h2>
        <p class="small">${q.selection?t('파란 윤곽의 물체를 묻고 있어요.',"Your question refers to the object outlined in blue."):t('사진 위의 선택 버튼을 누른 뒤 물체를 골라 주세요. 선택 없이 질문해도 됩니다.',"Select an object in the photo or ask a question without a selection.")}</p>
        <a class="question-photo-link" href="#learner-photo">${t("사진으로 돌아가기","Back to the photo")}</a>
        ${q.selection&&!q.parent?`<div class="quick-questions"><button type="button" class="btn" data-quick="procedure" ${blocked?'disabled':''}>${t("무엇에 쓰나요?","What is it for?")}</button><button type="button" class="btn" data-quick="appearance" ${blocked?'disabled':''}>${t("색·모양·위치 알려주세요","Describe its color, shape, and location")}</button></div>`:''}
        ${q.interrupted&&!q.error?t('<p class="small">답변을 받지 못한 질문을 입력란에 남겼어요. 내용을 확인하고 다시 보낼 수 있어요.</p>',"<p class=\"small\">Your unanswered question is still in the box. Review it and send it again.</p>"):q.restored?t('<p class="small">이 탭에서 하던 질문을 이어갈 수 있어요.</p>',"<p class=\"small\">Continue the question you started in this tab.</p>"):''}
        ${q.error?`<p class="question-error" role="alert" tabindex="-1">${esc(q.error)}</p>`:''}
        ${q.parent?t('<p class="clarification-note">앞선 질문의 대상을 확인하고 있어요. 다른 내용을 물으려면 새 질문으로 시작하세요.</p>',"<p class=\"clarification-note\">Clarify the object from your previous question. Start a new question to change topics.</p>"):''}
        ${options.map(option=>`<button type="button" class="btn clarification-option" data-clarification="${esc(option)}">${esc(option)}</button>`).join('')}
        <form id="question-form"><label class="field"><span>${q.parent?t('어떤 대상을 말했나요?',"Which object did you mean?"):t('궁금한 점을 적어 주세요',"Enter your question")}</span>
          <textarea id="step-question" maxlength="1000" required ${blocked?'disabled':''} placeholder="${q.selection?t('예: 이 물체를 참가자에게 건네도 되나요?',"Example: Can I give this object to an attendee?"):t('예: 사진 오른쪽 물체는 무엇에 쓰나요?',"Example: What is the item on the right for?")}">${esc(q.draft)}</textarea></label>
          <div class="question-actions"><button class="btn primary" type="submit" ${blocked?'disabled':''}>${q.parent?t('확인 답변 보내기',"Send clarification"):t('질문 보내기',"Send question")}</button>
          ${q.parent?`<button class="btn" type="button" id="new-question" ${blocked?'disabled':''}>${t("새 질문으로 시작","Start a new question")}</button>`:''}</div>
        </form>
        <div class="question-history" aria-live="polite" aria-relevant="additions">${q.items.slice(-recentQuestionCount).map((item,i)=>answerCard(item,i,q,s)).join('')}</div>
        <details class="question-help" id="question-help"><summary>${t("AI 답변의 한계·대화 보관 안내","AI limits and conversation history")}</summary>
          <p class="small question-footnote">${t("사진 해석과 대상 연결에는 오류가 있을 수 있어요. 최근 질문 8개와 작성 중인 질문, 물체 선택을 이 탭에서 최대 24시간 동안 다시 불러올 수 있어요. 답하지 못한 질문은 담당자의 보완 목록에 남아요.","The AI can misidentify objects. This tab can restore up to 8 recent questions, the current draft, and the selection for up to 24 hours. Unanswered questions go to the supervisor’s review list.")}</p>
          <p class="small question-footnote">${t("아래 버튼은 이 단계의 화면 기록을 지웁니다. 이미 보낸 질문은 서버 보관 정책을 따릅니다.","Clearing the view removes this step’s local history. Sent questions follow the server’s retention policy.")}</p>
          <button class="btn" type="button" id="clear-conversation" ${blocked||!hasConversation(q)?'disabled':''}>${t("이 단계의 대화 지우기","Clear this step’s conversation")}</button>
          <span class="small" id="conversation-status" role="status"></span>
        </details>
      </section>`;
    }
    function selectionControls(s){
      const q=stateFor(s.id),disabled=q.busy||q.selectionBusy;
      return `<div class="selection-controls"><button type="button" class="btn primary" id="object-select-toggle" ${disabled?'disabled':''}>${q.selectMode?t('선택 취소',"Cancel selection"):q.selection?t('다른 물체 선택',"Select a different object"):t('사진에서 물체 선택',"Select an object in the photo")}</button>${q.selection||q.selectionError?`<button type="button" class="btn" id="object-select-clear" ${disabled?'disabled':''}>${t("선택 해제","Clear selection")}</button>`:''}<a class="read-approved" href="#approved-step">${t("승인 설명 읽기 ↓","Read approved instructions ↓")}</a></div>
      <p class="selection-help" id="selection-help">${q.selectMode?t('물체 가운데를 누르세요. 방향키·Enter로도 선택할 수 있어요.',"Click the center of the object. You can also use the arrow keys and Enter."):q.selection?t('파란 윤곽의 물체를 선택했어요. 빠른 질문을 눌러 보세요.',"The selected object is outlined in blue. Try a quick question below."):t('사진 속 물체를 고르면 이름을 몰라도 질문할 수 있어요.',"Point to an object in the photo to ask about it by location.")}</p>
      ${q.selectionBusy?t('<p class="selection-status" role="status" tabindex="-1"><span class="spinner" aria-hidden="true"></span>선택한 물체의 윤곽을 찾고 있어요…</p>',"<p class=\"selection-status\" role=\"status\" tabindex=\"-1\"><span class=\"spinner\" aria-hidden=\"true\"></span>Finding the selected object’s outline…</p>"):''}
      ${q.selectionError?`<p class="selection-error" role="alert" tabindex="-1">${esc(q.selectionError)}${t(" 승인된 설명은 계속 읽을 수 있어요."," You can still read the approved instructions.")}</p>`:''}`;
    }
    function searchPanel(){
      return `<details class="guide-search" id="guide-search"><summary>${t("안내서 전체의 승인 설명에서 찾기","Search approved instructions across the guide")}</summary><p class="small">${t("단어로 원문을 찾아요. 예: 명찰, 검은 펜. AI 호출 없이 모든 단계에서 검색합니다.","Search words such as badge or black pen. This search works across all steps without AI.")}</p><form id="guide-search-form"><label class="field"><span>${t("찾을 단어","Search term")}</span><input id="guide-search-input" type="search" maxlength="100" value="${esc(searchQuery)}" autocomplete="off"></label><button class="btn" id="guide-search-submit" type="submit">${t("승인 문구 찾기","Search approved text")}</button></form><div id="guide-search-results" aria-live="polite"></div></details>`;
    }
    function renderSearch(){
      const results=searchApprovedSteps(r.steps,searchQuery),target=main.querySelector('#guide-search-results');
      target.innerHTML=!searchQuery.trim()?'':results.length?`<p class="small">${results.length}${t("개 단계에서 찾았어요."," matching steps.")}</p>${results.map(({step,index:i})=>`<article class="search-result"><h3>${i+1}. ${esc(step.title)}</h3><p class="small">${t("승인된 설명","Approved instructions")}</p><p>${esc(step.instruction)}</p><p class="small">${t("승인된 완료 확인","Approved completion check")}</p><p>${esc(step.completion_check)}</p><button class="btn small" type="button" data-search-step="${i}">${t("이 단계로 이동","Open this step")}</button></article>`).join('')}`:t('<p class="small">일치하는 승인 문구가 없어요. 더 짧은 단어로 검색하거나 담당자에게 확인해 주세요.</p>',"<p class=\"small\">No approved text matched. Try a shorter term or ask your supervisor.</p>");
      target.querySelectorAll('[data-search-step]').forEach(el=>el.onclick=()=>{moveStep(Number(el.dataset.searchStep));});
    }
    function relatedSteps(){
      const adjacent=[index-1,index+1].filter(i=>i>=0&&i<r.steps.length);
      if(!adjacent.length)return '';
      return `<aside class="pinboard-related" aria-label="${t("이어지는 작업 단계","Adjacent steps")}">${adjacent.map(i=>{const step=r.steps[i];return `<button type="button" class="pinboard-step-card" data-board-step="${i}" aria-label="${i+1}${t("단계로 이동: "," · Open step ")}${esc(step.title)}"><img src="/api/learn/${encodeURIComponent(shareId)}/steps/${encodeURIComponent(step.id)}/photo" alt="" width="120" height="80" loading="lazy"><span><small>${i<index?t('이전 단계',"Previous step"):t('다음 단계',"Next step")} · ${i+1} / ${r.steps.length}</small><strong>${esc(step.title)}</strong></span>${pinboardIcon(i<index?'left':'right')}</button>`;}).join('')}</aside>`;
    }
    function focusLearner(selector,block='nearest'){
      const target=main.querySelector(selector);
      if(!target||target.disabled)return;
      target.focus({preventScroll:true});
      if(block)target.scrollIntoView({block});
    }
    function moveStep(next,focusId='step-heading'){
      index=next;
      remember();
      draw();
      const control=main.querySelector('#'+focusId);
      if(focusId==='step-heading'||control?.disabled)focusLearner('#step-heading','start');
      else focusLearner('#'+focusId);
    }
    function settleRequest(step,pending,resultSelector){
      if(r.steps[index].id!==step.id)return;
      const followResult=document.activeElement===pending;
      draw(!followResult);
      if(followResult)focusLearner(resultSelector,'start');
    }
    function draw(keepFocus=false){
      const active=document.activeElement;
      const step=r.steps[index];
      const openDisclosures=[...main.querySelectorAll('details[open][id]')]
        .filter(el=>renderedStepId===step.id||!el.classList.contains('answer-sources'))
        .map(el=>el.id);
      let focusSelector;
      if(keepFocus&&main.contains(active)){
        if(active.id)focusSelector='#'+CSS.escape(active.id);
        else if(active.matches('summary')&&active.parentElement.id)focusSelector='#'+CSS.escape(active.parentElement.id)+' > summary';
        else if(active.matches('a[href]'))focusSelector='a[href="'+CSS.escape(active.getAttribute('href'))+'"]';
      }
      const caret=focusSelector&&active.matches('input,textarea')?[active.selectionStart,active.selectionEnd]:null;
      stopBoardConnection();
      const s=r.steps[index],complete=done.includes(s.id),finished=done.length===r.steps.length,q=stateFor(s.id);
      const nextIndex=index+1<r.steps.length?index+1:r.steps.findIndex(step=>!done.includes(step.id));
      const nextLabel=index+1<r.steps.length?t('다음 단계로',"Continue to the next step"):t('미완료 단계로',"Go to an unfinished step");
      const location=q.location,answerBoxes=location?.highlights||[],shownBoxes=q.selection||q.selectionBusy?[]:answerBoxes.length?answerBoxes:s.highlights;
      const markers=!q.selection&&!q.selectionBusy&&!q.selectMode?shownBoxes.map((h,i)=>{const point=highlightPoint(h.box);return `<button type="button" class="pinboard-marker" data-x="${point.x}" data-y="${point.y}" data-select-highlight="${i}" style="left:${point.x/10}%;top:${point.y/10}%" aria-label="${esc(h.label)}${t(" 위치에서 물체 선택"," · Select object here")}" ${q.busy?'disabled':''}>${pinboardIcon('plus')}</button>`;}).join(''):'';
      main.innerHTML=`<section class="learner learner-workbench pinboard-workspace"><header class="learn-header"><div><h1>${esc(r.title)}</h1></div><span class="status-pill ok">${pinboardIcon('check')}${t(" 담당자 승인본 "," Approved version ")}${r.revision_number}</span></header>
        ${r.steps.some(step=>step.photo_origin==='staged_ai')?t('<p class="demo-origin" id="photo-origin">시연용 AI 연출 사진 · 실제 행사 현장 검증 자료가 아닙니다.</p>',"<p class=\"demo-origin\" id=\"photo-origin\">AI-staged demonstration photo · Simulated work setting</p>"):''}
        <details class="guide-context" id="guide-information"><summary>${t("작업 목표·안내서 정보","Task goal and guide details")}</summary><p>${esc(r.goal)}</p><p class="small">${t("승인된 작업 사진에서 대상을 고릅니다. 실시간 카메라 화면이 아닙니다.","Select an object in the approved work photo. The photo shows the procedure as approved.")}</p></details>
        <section class="pinboard-board" aria-label="${t("사진과 승인 메모 작업 보드","Photo and approved notes")}"><header class="pinboard-board-bar"><h2 id="step-heading" class="current-step-title" tabindex="-1">${esc(s.title)}</h2><nav class="learn-nav" aria-label="${t("안내서 단계","Guide steps")}"><button type="button" class="btn" id="learn-prev" ${index===0?'disabled':''} aria-label="${t("이전 단계","Previous step")}">${pinboardIcon('left')}</button><label><span>${index+1} / ${r.steps.length}${t(" 단계 · "," step · ")}${done.length}${t("단계 완료"," completed")}</span><select id="learn-step-select" aria-label="${t("현재 단계 선택","Select the current step")}">${r.steps.map((step,i)=>`<option value="${i}" ${i===index?'selected':''}>${i+1}. ${esc(step.title)}${done.includes(step.id)?' ✓':''}</option>`).join('')}</select></label><button type="button" class="btn" id="learn-next" ${index===r.steps.length-1?'disabled':''} aria-label="${t("다음 단계","Next step")}">${pinboardIcon('right')}</button></nav></header>
        <div class="pinboard-canvas"><svg class="pinboard-connector" aria-hidden="true" preserveAspectRatio="none"><path/><circle data-connection-source r="4"/><circle data-connection-target r="4"/></svg>
          <div class="pinboard-visual">${selectionControls(s)}<div class="pinboard-photo-card"><div id="learner-photo" tabindex="-1" class="${answerBoxes.length?'answer-location':''}">
            ${answerBoxes.length?`<div class="answer-location-label">${t("AI가 해석한 위치 · ","Location identified by AI · ")}${esc(location.question)} <button type="button" id="approved-locations">${t("승인된 표시로 돌아가기","Back to approved markers")}</button></div>`:''}
            ${photo(`/api/learn/${encodeURIComponent(shareId)}/steps/${encodeURIComponent(s.id)}/photo`,shownBoxes,false,{width:s.photo_width,height:s.photo_height},selectionOverlay(q.selection,q.selectMode||q.selectionBusy?q.cursor:q.selection?.point,esc)+markers)}</div>
            <div class="pinboard-photo-caption">${pinboardIcon('photo')}<span>${esc(s.title)}</span></div>
            ${shownBoxes.length?`<div class="box-legend">${shownBoxes.map((h,i)=>`<button type="button" class="pinboard-target" data-select-highlight="${i}" ${q.busy||q.selectMode?'disabled':''}>${pinboardIcon('plus')}${i+1} · ${esc(h.label)}${t(" 선택"," · Select")}</button>`).join('')}</div>`:''}
            ${s.photo_credit?`<p class="credit">${esc(photoCredit(s.photo_credit))}</p>`:''}</div></div>
          <div class="pinboard-notes"><section class="approved-step pinboard-note" id="approved-step" aria-labelledby="approved-heading"><h3 id="approved-heading" tabindex="-1">${pinboardIcon('pin')}${t(" 이 단계의 승인 메모"," Approved notes for this step")}</h3><p class="instruction">${esc(s.instruction)}</p><div class="check-card"><h3>${t("완료 확인","Completion check")}</h3><p>${esc(s.completion_check)}</p></div><div class="step-completion-actions">
            <button type="button" class="btn" id="mark-complete">${pinboardIcon('check')}${complete?t('완료 표시 해제',"Undo completion"):t('이 단계 완료 표시',"Mark this step complete")}</button>
            ${complete&&!finished?'<button type="button" class="btn primary" id="continue-step">'+nextLabel+pinboardIcon('right')+'</button>':''}
          </div>
          ${complete?'<p class="completed" role="status">'+(finished?t('모든 단계를 완료 표시했습니다.',"You marked all steps complete."):t('이 단계를 완료했다고 표시했습니다.',"You marked this step complete."))+'</p>':''}
          <p class="learn-footer">${t("직접 확인한 뒤 표시하세요. 완료 상태는 이 기기에 저장됩니다.","Check the work yourself before marking it complete. Your progress is stored on this device.")}</p>
          <a class="ask-from-instructions" href="#question-heading">${t("이 단계에 질문하기","Ask about this step")}</a></section>
            <div class="pinboard-tools"><button type="button" class="btn quiet" id="pinboard-connection-toggle" aria-pressed="${q.showConnection}">${pinboardIcon('link')}${t("메모 연결선 표시","Show the line linking photo and notes")}</button><p class="small">${t("연결선은 사진과 승인 메모를 함께 읽기 위한 표시입니다. 대상과 규칙의 적용 여부는 AI 답변에서 확인하세요.","The line helps you read the photo alongside the approved notes. AI answers explain which object and rule apply.")}</p></div>
          </div>
          ${questionPanel(s)}
          ${relatedSteps()}
        </div></section>
        <div class="pinboard-question-workspace">${searchPanel()}</div></section>`;
      renderedStepId=step.id;
      for(const id of openDisclosures){
        const details=main.querySelector('#'+CSS.escape(id));
        if(details)details.open=true;
      }
      if(focusSelector){
        focusLearner(focusSelector,null);
        if(caret&&caret[0]!==null)document.activeElement.setSelectionRange?.(...caret);
      }
      const anchor=q.selection?.point||(answerBoxes.length?highlightPoint(answerBoxes[0].box):{x:1000,y:500});
      stopBoardConnection=bindBoardConnection(main.querySelector('.pinboard-canvas'),anchor,q.showConnection);
      main.querySelector('#pinboard-connection-toggle').onclick=()=>{q.showConnection=!q.showConnection;draw();main.querySelector('#pinboard-connection-toggle').focus({preventScroll:true});};
      main.querySelectorAll('[data-select-highlight]').forEach(el=>el.onclick=()=>selectAt(s,highlightPoint(shownBoxes[Number(el.dataset.selectHighlight)].box)));
      main.querySelectorAll('[data-board-step]').forEach(el=>el.onclick=()=>moveStep(Number(el.dataset.boardStep)));
      main.querySelector('#object-select-toggle').onclick=()=>{
        q.selectMode=!q.selectMode;
        q.selectionError='';
        if(q.selectMode)q.cursor=q.selection?.point?{...q.selection.point}:{x:500,y:500};
        draw();
        focusLearner(q.selectMode?'#photo-frame':'#object-select-toggle');
      };
      const clear=main.querySelector('#object-select-clear');if(clear)clear.onclick=()=>{q.selection=null;q.selectionError='';q.selectMode=false;q.parent=null;q.location=null;cache.write(s.id,q);draw();focusLearner('#object-select-toggle');};
      bindPointPicker(main.querySelector('#photo-frame'),main.querySelector('#work-photo'),{active:q.selectMode&&!q.selectionBusy&&!q.busy,cursor:q.cursor,label:t('물체의 가운데를 선택하세요. 방향키로 이동하고 Enter로 선택할 수 있습니다.','Select the center of the object. Move with the arrow keys and press Enter to select.'),onMove:point=>{q.cursor=point;},onCommit:point=>selectAt(s,point),onCancel:()=>{q.selectMode=false;draw();focusLearner('#object-select-toggle');}});
      const field=main.querySelector('#step-question'),clearConversation=main.querySelector('#clear-conversation');
      field.oninput=()=>{
        q.draft=field.value;
        q.interrupted=false;
        cache.write(s.id,q);
        clearConversation.disabled=!hasConversation(q);
      };
      clearConversation.onclick=()=>{
        Object.assign(q,{items:[],draft:'',parent:null,selection:null,location:null,expiresAt:null,
          restored:false,interrupted:false,error:'',selectionError:''});
        cache.clear(s.id);
        draw();
        focusLearner('#question-help > summary');
        main.querySelector('#conversation-status').textContent=t(' 이 단계의 화면 기록을 지웠어요.'," This step’s local history was cleared.");
      };
      main.querySelector('#question-form').onsubmit=e=>{e.preventDefault();sendQuestion(s);};
      main.querySelectorAll('[data-quick]').forEach(el=>el.onclick=()=>{q.draft=el.dataset.quick==='procedure'?t('선택한 물체는 무엇에 쓰나요?',"What is the selected object used for?"):t('선택한 물체의 색과 모양, 사진 속 위치를 알려 주세요.',"Describe the selected object’s color, shape, and position in the photo.");sendQuestion(s,el.dataset.quick);});
      const restart=main.querySelector('#new-question');if(restart)restart.onclick=()=>{q.parent=null;q.draft='';q.error='';q.interrupted=false;cache.write(s.id,q);draw();main.querySelector('#step-question').focus();};
      main.querySelectorAll('[data-clarification]').forEach(el=>el.onclick=()=>{q.draft=el.dataset.clarification;sendQuestion(s);});
      main.querySelectorAll('.ask-again-link').forEach(el=>el.onclick=e=>{e.preventDefault();main.querySelector('#step-question').focus();});
      main.querySelectorAll('[data-answer-location]').forEach(el=>el.onclick=()=>{const item=q.items[Number(el.dataset.answerLocation)];q.selection=item.selection||null;q.parent=null;q.selectMode=false;q.location=item.selection?null:{question:item.question,highlights:item.response.highlights};cache.write(s.id,q);draw();focusLearner('#learner-photo');});
      const approved=main.querySelector('#approved-locations');if(approved)approved.onclick=()=>{q.location=null;q.selection=null;q.parent=null;cache.write(s.id,q);draw();focusLearner('#learner-photo');};
      main.querySelector('#mark-complete').onclick=()=>{done=complete?done.filter(id=>id!==s.id):[...done,s.id];remember();draw();main.querySelector('#mark-complete').focus({preventScroll:true});};
      const continuation=main.querySelector('#continue-step');
      if(continuation)continuation.onclick=()=>moveStep(nextIndex);
      main.querySelector('#learn-prev').onclick=()=>moveStep(index-1,'learn-prev');main.querySelector('#learn-next').onclick=()=>moveStep(index+1,'learn-next');
      main.querySelector('#learn-step-select').onchange=e=>moveStep(Number(e.target.value),'learn-step-select');
      main.querySelector('#guide-search-input').oninput=e=>{searchQuery=e.target.value;};
      renderSearch();
      main.querySelector('#guide-search-form').onsubmit=e=>{e.preventDefault();searchQuery=main.querySelector('#guide-search-input').value;renderSearch();};
      main.querySelectorAll('[data-rule-reask]').forEach(el=>el.onclick=()=>{const item=q.items[Number(el.dataset.ruleReask)];q.selection=item.selection||null;q.parent=null;q.selectMode=false;q.draft=item.question;sendQuestion(s,'procedure',item.response.id);});
      main.querySelectorAll('[data-open-search]').forEach(el=>el.onclick=()=>{const search=main.querySelector('#guide-search');search.open=true;main.querySelector('#guide-search-input').focus();});
      main.querySelectorAll('a[href="#approved-step"],a[href="#question-heading"],a[href="#learner-photo"]').forEach(link=>{
        link.onclick=event=>{
          event.preventDefault();
          const target=link.hash==='#approved-step'?'#approved-heading':link.hash;
          focusLearner(target,'start');
        };
      });
    }
    async function selectAt(step,point){
      const q=stateFor(step.id);if(q.busy||q.selectionBusy)return;
      q.selectionBusy=true;q.selectMode=false;q.selection=null;q.selectionError='';q.parent=null;q.location=null;q.cursor=point;cache.write(step.id,q);draw();
      const pending=main.querySelector('.selection-status');
      focusLearner('.selection-status');
      try{const selected=await api(`/api/learn/${encodeURIComponent(shareId)}/selections`,{method:'POST',body:json({step_id:step.id,point})});if(selected.status==='selected'){q.selection=selected;}else q.selectionError=t(selected.message||'물체를 확인하지 못했습니다. 안쪽을 다시 선택해 주세요.','Could not identify the object. Try clicking its center.');}
      catch(error){q.selectionError=error.message;}
      finally{
        q.selectionBusy=false;
        cache.write(step.id,q);
        settleRequest(step,pending,q.selection?'#question-heading':'.selection-error');
      }
    }
    async function sendQuestion(step,intent='auto',recheckOf=null){
      const q=stateFor(step.id),question=q.draft.trim();if(q.busy||q.selectionBusy||q.selectMode||!question)return;
      if(question.length>1000){q.error=t('질문은 1,000자 이내로 적어 주세요.',"Enter a question of up to 1,000 characters.");draw();focusLearner('.question-error');return;}
      q.busy=true;q.error='';q.location=null;q.interrupted=false;q.restored=false;
      const turn={question,intent,response:null,selection:q.selection,recheckOf};q.items.push(turn);
      cache.write(step.id,q);draw();
      const pending=main.querySelector('.answer-pending');
      focusLearner('.answer-pending');
      try{
        const response=await api(`/api/learn/${encodeURIComponent(shareId)}/questions`,{method:'POST',body:json({step_id:step.id,question,clarification_of:q.parent,selection_id:q.selection?.id||null,intent,recheck_of:recheckOf})});
        turn.response=response;turn.intent=response.intent;turn.recheckOf=response.recheck_of||null;if(response.recovered_gap_id){for(const item of q.items){if(item.response?.status!=='answered'&&(item.response?.id===response.recovered_gap_id||item.recheckOf===response.recovered_gap_id))item.recoveredBy=response.id;}}q.parent=response.status==='needs_clarification'?response.id:null;q.draft='';
        if(response.highlights.length)q.location={question,highlights:response.highlights};
      }catch(error){q.items=q.items.filter(item=>item!==turn);q.error=error.message;q.interrupted=true;}
      finally{
        q.busy=false;
        cache.write(step.id,q);
        const hasVerdict=turn.response?.status==='answered'&&turn.response.assessment&&turn.response.assessment.decision!=='visual';
        const result=hasVerdict?'.rule-assessment h3':'.answer-status';
        settleRequest(step,pending,turn.response?`.question-turn:last-child ${result}`:'.question-error');
      }
    }
    document.body.classList.add('pinboard-page');
    document.querySelector('.brand .brand-mark').outerHTML=pinboardIcon('focus');
    document.querySelector('meta[name="theme-color"]').content='#f0f0ec';
    document.title=r.title+' — ShowMe';draw();
  }catch(error){main.innerHTML=`<section class="error-page"><h1>${t("안내서를 열 수 없어요.","Could not open the guide.")}</h1><p>${esc(error.message)}</p><a class="btn" href="/">${t("ShowMe 홈으로","Back to ShowMe")}</a></section>`;}
}
async function boot(){const match=location.pathname.match(/^\/learn\/([^/]+)$/);if(match)return learner(match[1]);setLanguage(authorLanguage);try{const [session,demo]=await Promise.all([api('/api/session'),api(t('/api/demo?lang=ko','/api/demo'))]);S.author=session.author;S.demoUrl=demo.url;if(S.author)await refreshList();render();}catch(error){say(error.message,true);main.innerHTML=t('<div class="boot">서버 연결을 확인하고 새로고침해 주세요.</div>',"<div class=\"boot\">Check the server connection and refresh.</div>");}}
boot();
