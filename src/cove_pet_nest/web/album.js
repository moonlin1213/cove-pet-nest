const $=id=>document.getElementById(id);
const safeUrl=url=>typeof url==='string'&&/^(\/api\/assets\/[a-f0-9]{64}\.webp|\/starter\/(cat|dog|egg)-sprites-light\.webp)$/.test(url)?url:null;
const date=stamp=>new Date(stamp*1000).toLocaleDateString('zh-CN');
const jobText={reserved:'模样已排队，新画像就绪前仍保留现在的样子。',submitted:'模样正在准备。',failed:'这次没有准备好，可以手动继续。',unknown:'上次请求可能已计费，结果暂时不确定。'};
function el(tag,text,className){const node=document.createElement(tag);if(text)node.textContent=text;if(className)node.className=className;return node;}
function action(text,handler){const button=el('button',text);button.type='button';button.onclick=handler;return button;}
export function mountAlbum({api,getState,tell}){
  let selected=null,history=null,life=null,page=0,lifeOffset=0,generation=0;
  const dialog=$('albumDialog');
  async function refresh(reset=false){
    const ticket=++generation;const id=selected;if(!id)return;
    $('albumMessage').textContent='正在翻开相册……';
    try{
      const [h,l]=await Promise.all([api(`/api/pets/${encodeURIComponent(id)}/stages`),api(`/api/life-events?pet_id=${encodeURIComponent(id)}&offset=${lifeOffset}&limit=12`)]);
      if(ticket!==generation||id!==selected||!dialog.open)return;
      history=h;life=l;page=reset?Math.max(0,h.stages.length-1):Math.min(page,Math.max(0,h.stages.length-1));
      $('albumTitle').textContent=h.name+' · 一起长大的日子';
      $('albumMessage').textContent=h.stages.length?'':'模样正在准备，到家后会收进相册。';
      renderStage();renderPhotos();
    }catch(error){if(ticket===generation)$('albumMessage').textContent=error.message;}
  }
  function zoom(url,atlas,caption){
    url=safeUrl(url);if(!url)return;
    $('viewerPicture').replaceChildren();$('viewerCaption').textContent=caption;
    if(atlas){const p=el('div',null,'zoom-atlas');p.style.backgroundImage=`url("${url}")`;$('viewerPicture').append(p);}
    else{const img=el('img');img.src=url;img.alt=caption;$('viewerPicture').append(img);}
    $('photoViewer').showModal();
  }
  function retryControl(job){
    return action('继续准备',async event=>{
      const ack=job.status==='unknown';
      if(!confirm(ack?'上次请求可能已计费。继续会发送新请求，可能再次计费，确定继续吗？':'继续准备会再次使用图片服务，可能产生费用，确定继续吗？'))return;
      const button=event.currentTarget;button.disabled=true;
      try{await api(`/api/jobs/${job.id}/retry`,{request_id:crypto.randomUUID(),acknowledge_unknown:ack});await refresh();}
      catch(error){$('albumMessage').textContent=error.message;}finally{button.disabled=false;}
    });
  }
  function renderStage(){
    const stage=history.stages[page];const url=safeUrl(stage?.asset_url);
    $('stagePortrait').style.backgroundImage=url?`url("${url}")`:'none';$('stagePortrait').disabled=!url;
    $('stageTitle').textContent=stage?.title||'还在路上';
    $('stageDate').textContent=stage?(stage.date_estimated?'升级前已有 · 日期为估计':'')+(stage.date_estimated?'':date(stage.activated_at)):'';
    $('stageFeatures').textContent=stage?.features.length?stage.features.join('；'):'从第一天开始，留下属于它的样子。';
    $('stageCurrent').textContent=stage?.active?'现在的模样':'曾经的模样，依然好好收着。';
    $('stageCounter').textContent=history.stages.length?`${page+1} / ${history.stages.length}`:'0 / 0';
    $('stagePrevious').disabled=page<=0;$('stageNext').disabled=page>=history.stages.length-1;
    $('stagePortrait').onclick=()=>zoom(url,true,history.name+' · '+stage.title);
    $('growthJobs').replaceChildren();
    history.jobs.filter(j=>['reserved','submitted','failed','unknown'].includes(j.status)).forEach(job=>{
      $('growthJobs').append(el('p',jobText[job.status]));
      if(['failed','unknown'].includes(job.status))$('growthJobs').append(retryControl(job));
    });
    const progress=getState()?.pets.find(p=>p.id===selected)?.growth_progress;
    if(progress)$('growthJobs').append(el('p',`下一阶段需要成长 ${progress.required_growth}，相处 ${progress.elapsed_days}/${progress.required_days} 天。`));
    if(!getState()?.image_edit_configured)$('growthJobs').append(el('p','持续蜕变需要配置支持参考图的图片接口。首次孵化仍使用原来的生成接口。'));
  }
  function renderPhotos(){
    const host=$('lifePhotos');host.replaceChildren();
    $('photoConfig').textContent=getState()?.image_edit_configured?'生成照片会使用你配置的图片服务，并占用当天的图片名额。':'先配置支持参考图的图片接口，就可以把这些真实片刻留成照片。';
    if(!life.events.length)host.append(el('p','一次真实照顾后，这里就会留下可拍照的生活瞬间。','quiet'));
    for(const source of life.events){
      const card=el('article',null,'life-photo');const job=source.photo;
      card.append(el('h3',source.label),el('p',`${date(source.occurred_at)} · ${source.participants.length} 位宝宝`,'quiet'));
      if(job?.status==='success'&&safeUrl(job.asset_url)){
        const button=action('',()=>zoom(job.asset_url,false,source.label));button.dataset.photoView=job.id;button.className='photo-thumb';
        const image=el('img');image.src=job.asset_url;image.alt=source.label;image.loading='lazy';button.append(image);card.append(button);
      }else if(job){
        const photoText={reserved:'照片已排队，等待图片服务或当天名额。',submitted:'正在准备这张生活照。',failed:'照片没有准备好，可以手动继续。',unknown:jobText.unknown};
        card.append(el('p',photoText[job.status]||'照片正在收进相册。','quiet'));
        if(['failed','unknown'].includes(job.status))card.append(retryControl(job));
      }else{
        const button=action('留下这张生活照',async event=>{
          if(!confirm('这会使用你配置的图片服务生成一张生活照，可能产生费用。确定留住这个片刻吗？'))return;
          const target=event.currentTarget;target.disabled=true;
          try{await api('/api/photos',{event_id:source.id,request_id:crypto.randomUUID()});await refresh();}
          catch(error){$('albumMessage').textContent=error.message;}finally{target.disabled=false;}
        });
        button.dataset.photoCreate=source.id;button.disabled=!getState()?.image_edit_configured;card.append(button);
      }
      host.append(card);
    }
    $('lifeCounter').textContent=life.total?`${lifeOffset+1}–${Math.min(lifeOffset+life.limit,life.total)} / ${life.total}`:'0 / 0';
    $('lifePrevious').disabled=lifeOffset===0;$('lifeNext').disabled=lifeOffset+life.limit>=life.total;
  }
  async function open(id){
    const state=getState();if(!state?.pets.length){tell('先接一位宝宝回家，再一起留下成长的记忆。');return;}
    selected=id||state.pets[0].id;lifeOffset=0;history=null;life=null;
    $('albumPet').replaceChildren(...state.pets.map(p=>{const option=el('option',p.name);option.value=p.id;return option;}));$('albumPet').value=selected;
    if(!dialog.open)dialog.showModal();await refresh(true);
  }
  $('albumOpen').onclick=()=>open();$('albumClose').onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>{generation++;});
  $('albumPet').onchange=()=>{selected=$('albumPet').value;lifeOffset=0;refresh(true);};
  $('albumRefresh').onclick=()=>refresh();
  $('stagePrevious').onclick=()=>{if(page>0){page--;renderStage();}};
  $('stageNext').onclick=()=>{if(history&&page<history.stages.length-1){page++;renderStage();}};
  $('lifePrevious').onclick=()=>{lifeOffset=Math.max(0,lifeOffset-12);refresh();};
  $('lifeNext').onclick=()=>{lifeOffset+=12;refresh();};
  function tab(lifeVisible){
    $('stagePanel').hidden=lifeVisible;$('lifePanel').hidden=!lifeVisible;
    $('stageTab').setAttribute('aria-selected',String(!lifeVisible));$('lifeTab').setAttribute('aria-selected',String(lifeVisible));
  }
  $('stageTab').onclick=()=>tab(false);$('lifeTab').onclick=()=>tab(true);
  $('stageTab').onkeydown=$('lifeTab').onkeydown=event=>{if(['ArrowLeft','ArrowRight'].includes(event.key)){const showLife=event.key==='ArrowRight';tab(showLife);$(showLife?'lifeTab':'stageTab').focus();event.preventDefault();}};
  $('viewerClose').onclick=()=>$('photoViewer').close();
  $('photoViewer').onclick=event=>{if(event.target===$('photoViewer'))$('photoViewer').close();};
  return {open};
}
