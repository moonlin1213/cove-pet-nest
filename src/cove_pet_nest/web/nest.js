const $=id=>document.getElementById(id);
let state=null, selected=null, offset=0;
const species={cat:'小猫',dog:'小狗',egg:'神秘灵宠蛋',parrot:'鹦鹉',snow_leopard:'雪豹',snake:'蛇',lizard:'蜥蜴'};
const statuses={fed:'吃饱啦',played:'一起玩了一会儿',comforted:'收到了摸摸',full:'已经吃饱了',no_food:'粮仓暂时没有粮食',pending:'宝宝的模样还在准备'};
function tell(text){$('message').textContent=text;}
async function api(path,body,headers={}){
  const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json',...headers},body:body===undefined?undefined:JSON.stringify(body)});
  const value=await response.json();
  if(!response.ok){
    if(response.status===401){$('login').hidden=false;$('room').hidden=true;}
    const errors={acknowledge_possible_prior_charge:'上次生成的结果不确定，请确认可能已计费后再继续。',job_not_retryable:'任务还在进行，或已完成。',invalid_request:'请检查填写的内容。'};
    throw new Error(errors[value.error]||'这次没有完成，请稍后重试。');
  }
  return value;
}
async function load(){state=await api(`/api/nest?offset=${offset}&limit=100`);$('login').hidden=true;$('room').hidden=false;render();}
function button(text,handler){const b=document.createElement('button');b.textContent=text;b.onclick=handler;return b;}
function render(){
  $('subtitle').textContent=`和${state.assistant_name}一起生活，慢慢长大。`;
  $('grains').textContent=state.grains;$('empty').hidden=state.total>0;
  $('pets').replaceChildren();$('roster').replaceChildren();
  state.pets.forEach((pet,i)=>{
    $('roster').append(button(`${pet.name} · ${species[pet.kind]}`,()=>openCare(pet)));
    if(i>=12)return;
    const b=button('',()=>openCare(pet));b.className='pet';b.setAttribute('aria-label',`照顾${pet.name}`);
    b.style.left=`${22+(i%4)*19}%`;b.style.top=`${51+Math.floor(i/4)*12}%`;
    if(pet.kind==='egg'&&pet.stage===0){b.style.left=`${82-(i%3)*5}%`;b.style.top=`${32+Math.floor(i/3)*2}%`;}
    const sprite=document.createElement('span');sprite.className='sprite';
    const ref=pet.asset_ref?`/api/assets/${encodeURIComponent(pet.asset_ref)}`:(['cat','dog','egg'].includes(pet.kind)?`/starter/${pet.kind}-sprites-light.webp`:null);
    if(ref)sprite.style.backgroundImage=`url("${ref}")`;else{sprite.textContent='✧';sprite.style.fontSize='40px';sprite.style.paddingTop='20px';}
    const label=document.createElement('span');label.className='pet-label';label.textContent=pet.name+(pet.status==='pending'?' · 准备中':'');
    b.append(sprite,label);$('pets').append(b);
  });
  $('events').replaceChildren();
  if(!state.events.length){const li=document.createElement('li');li.textContent='第一段共同照顾，会从这里开始。';$('events').append(li);}
  state.events.slice(0,8).forEach(event=>{
    const name=state.pets.find(p=>p.id===event.pet_id)?.name||'宝宝';
    const li=document.createElement('li');li.textContent=`${event.actor==='user'?state.user_name:state.assistant_name}${{feed:'喂了',play:'陪玩了',comfort:'摸摸了'}[event.action]}${name}`;$('events').append(li);
  });
  $('previous').hidden=offset===0;$('next').hidden=offset+100>=state.total;
}
function openCare(pet){
  selected=pet.id;$('careTitle').textContent=pet.name;
  $('careDetails').textContent=`${species[pet.kind]} · 饱腹 ${Math.round(pet.satiety)} · 成长 ${Math.round(pet.growth)}`;
  $('careActions').hidden=pet.status==='pending';$('jobInfo').replaceChildren();
  if(pet.kind==='egg'&&pet.stage===0){const p=document.createElement('p');p.textContent='照顾与共同相处会影响它未来的模样。成长达到门槛、相处满两天后，神秘蛋会开始准备孵化。';$('jobInfo').append(p);}
  pet.jobs.forEach(job=>{
    const p=document.createElement('p');
    p.textContent={reserved:state.image_generation_configured?'模样正在排队准备。':'模样需要图片服务；配置后会继续准备。',submitted:'模样正在生成，请稍候。',success:'模样已经准备好了。',superseded:'已使用你导入的模样。',failed:'生成或图片处理未完成，可以继续。重试可能再次计费。',unknown:'上次请求可能已经计费，但结果不确定。'}[job.status]||'任务等待继续。';
    $('jobInfo').append(p);
    if(['failed','unknown','abandoned'].includes(job.status)){
      $('jobInfo').append(button('继续准备',async()=>{
        const ack=job.status==='unknown'?confirm('上次请求可能已经计费。继续会发送新的生成请求，可能再次计费，确定继续吗？'):false;
        if(job.status==='unknown'&&!ack)return;
        try{await api(`/api/jobs/${job.id}/retry`,{request_id:crypto.randomUUID(),acknowledge_unknown:ack});$('careDialog').close();await load();tell('已重新排队。');}catch(e){tell(e.message);}
      }));
    }
  });
  if(!$('careDialog').open)$('careDialog').showModal();
}
$('adoptOpen').onclick=()=>$('adoptDialog').showModal();
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>b.closest('dialog').close());
$('kind').onchange=()=>{$('kindHint').textContent=['cat','dog'].includes($('kind').value)?'小猫和小狗有现成的模样，可以直接到家。':$('kind').value==='egg'?'先领一颗未知的蛋；未来的模样由你们的相处共同塑造，孵化需要图片服务。':'这一种宝宝需要图片服务或导入专属模样，准备好后才会来到小屋。';};
$('adoptForm').onsubmit=async e=>{e.preventDefault();const submit=e.submitter;submit.disabled=true;try{const result=await api('/api/adoptions',{kind:$('kind').value,name:$('petName').value,request_id:crypto.randomUUID()});$('adoptDialog').close();$('petName').value='';await load();tell(result.status==='preparing'?'宝宝的模样正在准备。':'宝宝到家了。');}catch(error){tell(error.message);}finally{submit.disabled=false;}};
async function care(action,all=false){try{const result=await api('/api/care',{action,request_id:crypto.randomUUID(),scope:all?'all':'selected',...(all?{}:{pet_ids:[selected]})});tell(result.results.map(r=>statuses[r.status]).filter(Boolean).join('；')||'小屋还没有宝宝。');$('careDialog').close();await load();}catch(error){tell(error.message);}}
document.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>care(b.dataset.action));$('feedAll').onclick=()=>care('feed',true);
$('previous').onclick=async()=>{offset=Math.max(0,offset-100);await load();};$('next').onclick=async()=>{offset+=100;await load();};
$('loginForm').onsubmit=async e=>{e.preventDefault();try{await api('/api/session',{}, {Authorization:`Bearer ${$('accessCode').value}`});$('accessCode').value='';await load();}catch(error){tell(error.message);}};
const key=new URLSearchParams(location.hash.slice(1)).get('key');
if(key){history.replaceState(null,'',location.pathname);try{await api('/api/session',{}, {Authorization:`Bearer ${key}`});}catch(error){tell(error.message);}}
load().catch(e=>tell(e.message));
setInterval(()=>{if(state&&!document.querySelector('dialog[open]')&&!document.hidden)load().catch(()=>{});},10000);
