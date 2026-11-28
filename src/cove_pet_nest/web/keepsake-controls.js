const $ = id => document.getElementById(id);
export function element(tag, text, className) {
  const el=document.createElement(tag);
  if(text!==undefined) el.textContent=text;
  if(className) el.className=className;
  return el;
}
export function action(text,handler) {
  const el=element('button',text);
  el.type='button';
  el.onclick=async()=>{
    el.disabled=true;
    try {await handler();} catch(error){
      if(el.isConnected && el.closest('dialog')?.open)$('collectionStatus').textContent=error.message;
    }
    finally {el.disabled=false;}
  };
  return el;
}
export function dropdown(title, options, value) {
  const label=element('label',title), select=element('select');
  for(const [key,name] of options)select.add(new Option(name,key));
  if(value!==undefined)select.value=value;
  label.append(select);
  return [label,select];
}
export function image(url,alt='') {
  const img=element('img');img.src=url;img.alt=alt;img.draggable=false;return img;
}
export const toyImage=t=>'/api/assets/'+encodeURIComponent(t.forms[t.form]);
const statuses={
  toy_play_cooldown:'让宝宝歇一歇，五秒后可以再玩。', pet_not_ready:'宝宝的模样还在准备中。',
  habitat_changed:'另一页已经保存了布置。请重新打开栖息地，查看最新布局。',
  invalid_request:'请检查填写的内容。',local_session_required:'请重新登录小屋。'
};
export async function request(path,method='GET',body) {
  const response=await fetch('/api/'+path,{method,cache:'no-store',headers:{'Content-Type':'application/json'},
    body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json();
  if(!response.ok){
    const error=new Error(statuses[data.error||data.detail]||'操作未完成，请重新打开再试。');
    error.status=response.status;
    throw error;
  }
  return data;
}
export function position(el,x,y) {
  el.style.left=(x*100)+'%';el.style.top=(y*100)+'%';
}

// Shared pointer and keyboard movement, relative to the visible board, not the page.
export function movable(el,board,item,finish,onError,canDropOnPet=false) {
  let start=null;
  const clamp=n=>Math.max(.06,Math.min(.94,n));
  async function done(x,y,pet) {
    try{await finish(clamp(x),clamp(y),pet);}
    catch(e){position(el,item.x,item.y);onError(e.message);}
  }
  function point(e){
    const b=board.getBoundingClientRect();
    return [clamp(start.x+(e.clientX-start.px)/b.width),clamp(start.y+(e.clientY-start.py)/b.height)];
  }
  el.onpointerdown=e=>{
    if(e.button!==0||!e.isPrimary)return;
    start={x:item.x,y:item.y,px:e.clientX,py:e.clientY,moved:false};
    el.setPointerCapture(e.pointerId);
  };
  el.onpointermove=e=>{
    if(!start||!e.isPrimary)return;
    if(Math.hypot(e.clientX-start.px,e.clientY-start.py)>4)start.moved=true;
    if(start.moved)position(el,...point(e));
  };
  el.onpointerup=e=>{
    if(!start||!e.isPrimary)return;
    const moved=start.moved,[x,y]=point(e);
    start=null;el.releasePointerCapture(e.pointerId);
    if(!moved)return;
    const pet=canDropOnPet?document.elementsFromPoint(e.clientX,e.clientY).map(n=>n.closest('[data-pet-id]')).find(Boolean)?.dataset.petId:null;
    done(x,y,pet);
  };
  el.onpointercancel=()=>{start=null;position(el,item.x,item.y);};
  el.onkeydown=e=>{
    const delta={ArrowLeft:[-.03,0],ArrowRight:[.03,0],ArrowUp:[0,-.03],ArrowDown:[0,.03]}[e.key];
    if(delta){e.preventDefault();done(item.x+delta[0],item.y+delta[1],null);}
  };
  return ()=>Boolean(start);
}
