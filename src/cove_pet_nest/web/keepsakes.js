import {editHabitat} from './habitat.js';

import {element, action, dropdown, image, toyImage, request, movable, position} from './keepsake-controls.js';
const $=id=>document.getElementById(id);

export function mountKeepsakes({tell}) {
  let data={toys:[],notes:[],pets:[]},latest=0,openVersion=0;
  const placedNodes=new Map();
  const dialog=$('collectionDialog'), body=$('collectionBody');
  const say=text=>{$('collectionStatus').textContent=text;};
  function open(title){
    ++openVersion;$('collectionTitle').textContent=title;body.replaceChildren();say('');
    if(!dialog.open)dialog.showModal();
    return openVersion;
  }
  $('collectionClose').onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>{++openVersion;});
  async function refresh(){
    const serial=++latest;
    const next=await request('keepsakes');
    if(serial!==latest)return;
    data=next;
    const layer=$('roomToys');
    const placed=new Set(data.toys.filter(t=>t.placed).map(t=>t.id));
    for(const [id,node] of placedNodes){
      if(!placed.has(id)){node.el.remove();placedNodes.delete(id);}
    }
    const basket=$('toyBasket');
    basket.querySelectorAll('.basket-preview').forEach(el=>el.remove());
    for(const [i,t] of data.toys.filter(t=>!t.placed).slice(0,3).entries()){
      const preview=image(toyImage(t));preview.className='basket-preview';preview.style.setProperty('--i',i);basket.append(preview);
    }
    for(const t of data.toys.filter(t=>t.placed)){
      let node=placedNodes.get(t.id);
      if(!node){
        const el=element('button',undefined,'room-toy'),model={...t},art=image(toyImage(t));
        el.setAttribute('aria-label','移动'+t.name);
        el.title=t.name+' · 拖动或用方向键移动';el.append(art);
        const dragging=movable(el,layer.parentElement,model,async(x,y,pet)=>{
          if(pet){await play(model,pet);tell('宝宝和玩具玩了一会儿。');}
          else await request('toys/'+model.id,'PATCH',{placed:true,x,y});
          await refresh();
        },tell,true);
        node={el,model,art,dragging};placedNodes.set(t.id,node);layer.append(el);
      }
      Object.assign(node.model,t);
      if(!node.dragging())position(node.el,t.x,t.y);
      if(node.art.getAttribute('src')!==toyImage(t))node.art.src=toyImage(t);
    }
  }
  async function play(toy,pet){
    const key='nest-play:'+toy.id+':'+pet;
    const id=sessionStorage.getItem(key)||crypto.randomUUID();
    sessionStorage.setItem(key,id);
    function clearReceipt(){
      if(sessionStorage.getItem(key)===id)sessionStorage.removeItem(key);
    }
    try{
      await request('toys/'+toy.id+'/play','POST',{pet_id:pet,request_id:id});
      clearReceipt();
    }catch(error){
      if(error.status>=400&&error.status<500){clearReceipt();throw error;}
      throw Error('玩耍回执还未确认。请选同一只宝宝再试，小屋会核对刚才那一次。');
    }
  }
  const active=version=>dialog.open && version===openVersion;
  async function redraw(version,draw){
    if(!active(version))return;
    await refresh();
    if(active(version))draw();
  }
  function renderToys(){
    const version=openVersion;
    body.replaceChildren();
    if(!data.toys.length)body.append(element('p','藤篮里还没有玩具。启用后台创作、接入互动后，留意接下来的惊喜。','quiet'));
    for(const t of data.toys){
      const article=element('article',undefined,'toy-entry'), story=element('div');
      article.append(image(toyImage(t),t.name),story);
      story.append(element('h3',t.name),element('p',t.origin),element('small',new Date(t.created_at*1000).toLocaleDateString()+' · 形态 '+(t.form+1)+' / 4'));
      const menu=element('div',undefined,'keepsake-actions');
      async function change(fields){
        await request('toys/'+t.id,'PATCH',fields);await redraw(version,renderToys);
      }
      menu.append(action('换个模样',()=>change({form:(t.form+1)%4})),action(t.placed?'收进箱子':'摆出来',()=>change({placed:!t.placed})));
      const available=data.pets.filter(p=>p.status==='ready'),options=available.map(p=>[p.id,p.name]);
      if(options.length){
        const [label,select]=dropdown('和谁玩',options);
        menu.append(label,action('给宝宝玩',async()=>{
          await play(t,select.value);await redraw(version,renderToys);
        }));
      }
      story.append(menu);
      for(const p of data.pets.filter(p=>t.plays[p.id]))story.append(element('small',p.name+'玩过 '+t.plays[p.id]+' 次'));
      body.append(article);
    }
  }
  let favoriteOnly=false;
  function renderNotes(){
    const version=openVersion;
    body.replaceChildren();
    const filter=action(favoriteOnly?'查看全部纸条':'只看收藏',()=>{favoriteOnly=!favoriteOnly;renderNotes();});
    body.append(filter);
    const notes=data.notes.filter(n=>!favoriteOnly||n.favorite);
    if(!notes.length)body.append(element('p',favoriteOnly?'还没有收藏的纸条。':'这里会收好宝宝留下的纸条。','quiet'));
    for(const n of notes){
      const article=element('article',undefined,'nest-note');
      const pet=data.pets.find(p=>p.id===n.pet_id);
      const kinds={arrival:'新玩具',observation:'小观察',affection:'亲昵',snack:'零食',doodle:'涂鸦'};
      article.append(element('small',[pet?.name,kinds[n.kind],new Date(n.created_at*1000).toLocaleDateString()].filter(Boolean).join(' · ')),element('p',n.text));
      if(n.kind==='doodle')article.append(image('/starter/doodle-heart-light.webp','手绘爱心'));
      async function update(flags){
        await request('notes/'+n.id,'PATCH',flags);await redraw(version,renderNotes);
      }
      article.append(action(n.is_read?'标为未读':'标为已读',()=>update({is_read:!n.is_read})),
        action(n.favorite?'取消收藏':'收藏',()=>update({favorite:!n.favorite})));
      body.append(article);
    }
  }
  async function openList(title,draw){
    const serial=open(title);
    try{await refresh();if(active(serial))draw();}
    catch(e){if(active(serial))say(e.message);}
  }
  $('toyBasket').onclick=()=>openList('玩具箱',renderToys);
  $('notesOpen').onclick=()=>{favoriteOnly=false;return openList('宠物纸条',renderNotes);};
  return {refresh,async openHabitat(pet){
    const serial=open(pet.name+'的栖息地');
    try{
      const [layout]=await Promise.all([request('habitats/'+pet.id),refresh()]);
      if(active(serial))editHabitat(body,pet,layout,data.toys,text=>{if(active(serial))say(text);});
    }catch(e){if(active(serial))say(e.message);}
  }};
}
