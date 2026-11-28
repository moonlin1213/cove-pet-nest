const el = id => document.getElementById(id);
const say = text => { el('notice').textContent = text; };
const sourceNames = {relationship:'互动摘要',life:'共同生活',care:'宠物照顾'};
const statusNames = {
  reserved:'等待生成', submitted:'正在请求服务', waiting_image:'等待玩具图片',
  success:'已完成', failed:'服务未完成', unknown:'上次调用结果未知'
};

async function api(path, body) {
  const response = await fetch('/api/creation/' + path, body === undefined ? {cache:'no-store'} : {
    method:'POST', headers:{'Content-Type':'application/json'},body:JSON.stringify(body)
  });
  if (response.status === 401) {
    el('loginHint').hidden=false;el('setup').hidden=el('checkPanel').hidden=true;
    throw Error('尚未登录或登录已过期。');
  }
  const data=await response.json();
  if (!response.ok) {
    const reasons = {invalid_provider:'请检查模型名、服务完整地址和密钥。', invalid_provider_update:'请选择填写新服务或清除本机覆盖。',
      invalid_request:'请核对必填项和确认信息。', daily_limit:'今日调用额度已用完。', invalid_creation_settings:'本机配置文件需要修复。'};
    throw Error(reasons[data.error] || '本次操作未完成，请刷新查看任务状态。');
  }
  return data;
}

function showConfig(cfg) {
  for (const kind of ['text','image']) {
    const provider=cfg[kind];
    el(kind+'State').textContent = provider.ready
      ? (provider.source==='environment'?'已沿用启动环境':'已保存本机配置') : '待配置';
  }
  el('sources').textContent=Object.entries(sourceNames).map(([key,name])=>name+(cfg.sources[key]?'已收到':'暂无记录')).join(' · ');
  el('dailyTextLimit').value=cfg.daily_text_limit;
  el('notesEnabled').checked=cfg.notes_enabled;el('toysEnabled').checked=cfg.toys_enabled;
  el('trial').disabled=!cfg.text.ready || cfg.daily_text_limit===0;
  const messages=[];
  if(cfg.notes_enabled || cfg.toys_enabled) {
    if(!cfg.text.ready) messages.push('等待文字服务配置。');
    if(cfg.toys_enabled && !cfg.image.ready) messages.push('玩具等待图片服务配置。');
    if(!Object.values(cfg.sources).some(Boolean)) messages.push('等待这座小屋的真实互动。');
    if(cfg.daily_text_limit===0) messages.push('每日文字上限为零。');
    if(!messages.length) messages.push('已开启后台创作，小屋运行时会等待生成机会。');
  } else messages.push('后台创作已关闭。');
  el('activity').textContent=messages.join(' ');
  el('setup').hidden=el('checkPanel').hidden=false;el('loginHint').hidden=true;
}

async function showJobs() {
  const jobs=await api('jobs');const list=el('jobs');list.replaceChildren();
  for(const job of jobs) {
    const row=document.createElement('li');
    const name={note:'宠物纸条',toy:'惊喜玩具',trial:'文字试生成'}[job.kind] || '创作任务';
    row.textContent=name+' · '+(statusNames[job.status] || '处理中');
    if(job.kind!=='trial' && ['failed','unknown'].includes(job.status)) {
      const retry=document.createElement('button');retry.type='button';retry.textContent='重新尝试';
      let attempt=crypto.randomUUID();
      retry.onclick=async()=>{
        if(!confirm(job.status==='unknown'?'上次请求结果未知，可能已经计费。是否发送新请求？':'重新尝试会提交新的生成请求，可能计费。继续吗？'))return;
        retry.disabled=true;
        try {
          await api('jobs/'+encodeURIComponent(job.id)+'/retry',{request_id:attempt,acknowledge_unknown:job.status==='unknown'});
          attempt=crypto.randomUUID();await showJobs();say('已提交重试。');
        } catch(error){say(error.message);}
        finally{retry.disabled=false;}
      };
      row.append(retry);
    }
    list.append(row);
  }
}

async function refresh() {
  showConfig(await api('settings'));await showJobs();
}
el('setup').onsubmit=async event=>{
  event.preventDefault();
  el('save').disabled=true;
  try {
    const patch={notes_enabled:el('notesEnabled').checked,toys_enabled:el('toysEnabled').checked,daily_text_limit:Number(el('dailyTextLimit').value)};
    for(const kind of ['text','image']) {
      const endpoint=el(kind+'Endpoint').value.trim(), model=el(kind+'Model').value.trim(), key=el(kind+'Key').value.trim();
      const reset=el(kind+'Reset').checked;
      if(endpoint||model||key) {
        if(!endpoint||!model||!key||reset)throw Error('更改服务时，请一并填写完整地址、模型名和密钥，并取消清除选项。');
        patch[kind]={endpoint,model,key};
      }
      if(reset)patch['reset_'+kind]=true;
    }
    const updated=await api('settings',patch);
    for(const kind of ['text','image']){
      for(const field of ['Endpoint','Model','Key'])el(kind+field).value='';
      el(kind+'Reset').checked=false;
    }
    showConfig(updated);say('已保存到这座小屋。');await showJobs();
  } catch(error){say(error.message);}
  finally{el('save').disabled=false;}
};
el('diagnose').onclick=async()=>{
  el('diagnose').disabled=true;
  try{
    const result=await api('diagnostic',{});
    say(result.stored && result.deduplicated && result.isolated
      ? '离线诊断通过。虚构事件已保存，重开后重复上报只记一次。没有调用模型。'
      : '离线诊断未通过。请检查当前小屋的数据目录。');
  } catch(error){say(error.message);}
  finally{el('diagnose').disabled=false;}
};
let trialID=crypto.randomUUID();
el('trial').onclick=async()=>{
  if(!confirm('这将把固定的虚构片段发给已配置的文字服务，占用一次每日文字名额，可能产生费用。确认试生成一次？'))return;
  el('trial').disabled=true;
  try{
    const result=await api('trial',{confirmed:true,request_id:trialID});
    trialID=crypto.randomUUID();
    say('文字试生成 · '+(statusNames[result.status] || '请检查配置和每日额度'));
    await showJobs();
  } catch(error){say(error.message);}
  finally{el('trial').disabled=false;}
};
el('refresh').onclick=()=>refresh().catch(error=>say(error.message));
refresh().catch(error=>say(error.message));
