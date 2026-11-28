import {element,action,dropdown,image,request,movable,position,toyImage} from './keepsake-controls.js';

const decorNames={hide:'躲避屋',stone:'石头',fern:'蕨类'};

export function editHabitat(body,pet,layout,toys,say) {
  let selected=layout.decor.length?0:-1,dirty=false,saving=false;
  const board=element('div',undefined,'habitat-board');
  board.setAttribute('role','group');board.setAttribute('aria-label','栖息地布置');
  const [themeLabel,theme]=dropdown('主题',[['warm_stone','暖石'],['moss_forest','苔林']],layout.theme);
  const [itemLabel,kind]=dropdown('添加装饰',[...Object.entries(decorNames),...toys.map(t=>['toy:'+t.id,t.name])]);
  const menu=element('div',undefined,'keepsake-actions'),controls=element('div',undefined,'keepsake-actions');
  const changed=()=>{dirty=true;say('布置尚未保存。');};
  theme.onchange=()=>{layout.theme=theme.value;changed();draw();};
  function describe(item) {
    if(item.kind!=='toy')return [decorNames[item.kind],'/starter/habitats/'+item.kind+'-light.webp'];
    const toy=toys.find(t=>t.id===item.toy_id);
    return [toy.name,toyImage(toy)];
  }
  const add=action('加入',()=>{
    if(layout.decor.length>=20){say('每个栖息地最多放二十件装饰。');return;}
    const value=kind.value;
    layout.decor.push({...(value.startsWith('toy:')?{kind:'toy',toy_id:value.slice(4)}:{kind:value}),x:.5,y:.65,scale:1});
    selected=layout.decor.length-1;changed();draw();
  });
  async function save(){
    if(saving||!dirty)return;
    saving=true;theme.disabled=kind.disabled=true;draw();
    try{
      const result=await request('habitats/'+pet.id,'PUT',layout);
      layout.revision=result.revision;dirty=false;say('布置已保存。');
    }finally{saving=false;theme.disabled=kind.disabled=false;draw();}
  }
  const saveButton=action('保存布置',save);
  const scaleLabel=element('label','大小'),size=element('input');
  size.type='range';size.min='.5';size.max='1.5';size.step='.05';scaleLabel.append(size);
  size.oninput=()=>{
    if(saving||selected<0)return;
    layout.decor[selected].scale=Number(size.value);changed();drawBoard();
  };
  const remove=action('移除装饰',()=>{
    layout.decor.splice(selected,1);selected=Math.min(selected,layout.decor.length-1);changed();draw();
  });
  function drawBoard(){
    board.replaceChildren();
    board.classList.toggle('moss-forest',layout.theme==='moss_forest');
    if(pet.asset_ref){
      const sprite=element('span',undefined,'habitat-pet');
      sprite.setAttribute('role','img');sprite.setAttribute('aria-label',pet.name);
      sprite.style.backgroundImage='url("/api/assets/'+encodeURIComponent(pet.asset_ref)+'")';board.append(sprite);
    }
    layout.decor.forEach((item,i)=>{
      const [name,url]=describe(item),el=element('button',undefined,'habitat-decor');
      el.type='button';el.setAttribute('aria-label',name);el.setAttribute('aria-pressed',String(i===selected));
      el.disabled=saving;el.append(image(url));position(el,item.x,item.y);el.style.width=(item.scale*23)+'%';
      el.onclick=()=>{if(selected!==i){selected=i;draw();}};
      movable(el,board,item,async(x,y)=>{
        if(saving)return;
        selected=i;item.x=x;item.y=y;changed();draw();board.querySelectorAll('button')[i]?.focus();
      },say);
      board.append(el);
    });
  }
  function draw(){
    drawBoard();controls.replaceChildren();
    if(selected>=0){
      const [name]=describe(layout.decor[selected]);
      size.value=layout.decor[selected].scale;
      controls.append(element('span',name),scaleLabel,remove);
    }
    add.disabled=saving||layout.decor.length>=20;
    remove.disabled=size.disabled=saving;
    saveButton.disabled=saving||!dirty;
  }
  menu.append(themeLabel,itemLabel,add);body.replaceChildren(menu,board,controls,saveButton);draw();
}
