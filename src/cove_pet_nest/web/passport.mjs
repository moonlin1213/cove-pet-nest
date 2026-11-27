import {Passport,RawPort,pair,maintain} from './passport-serial.mjs';

const el=id=>document.getElementById(id);
const tell=text=>{el('notice').textContent=text;};
let busy=false, confirmation=null;
async function api(path,body,headers={}) {
  let reply;
  try {reply=await fetch(path,{method:body===undefined?'GET':'POST',cache:'no-store',
    headers:{'Content-Type':'application/json',...headers},body:body===undefined?undefined:JSON.stringify(body)});}
  catch {throw Error('与本机小屋的连接中断，请确认小屋仍在运行后重试。');}
  if (!reply.ok) {
    if (reply.status===401) {
      el('login').hidden=false;el('pairing-form').hidden=true;
      throw Error('请先登录这座小屋。');
    }
    const error=await reply.json().catch(()=>({}));
    if (reply.status===404) throw Error('小屋版本还不支持挂件配对，请先更新本机灵宠屋。');
    if (error.error==='passport_lan_unavailable'||error.detail==='passport_lan_unavailable')
      throw Error('无法启动家庭同步。请关闭旧版连接助手，并检查电脑的局域网地址。');
    if (reply.status===409) throw Error('这次配对状态已变化，请刷新页面重新选择。');
    throw Error('小屋暂时无法完成这一步。请检查小屋仍在运行，稍后重试。');
  }
  return reply.json();
}
function networkFields() {
  el('credentials').hidden=el('reuse').checked;
  el('repair').hidden=el('reuse-label').hidden;
  el('ssid').required=!el('reuse').checked;
}
async function load() {
  const status=await api('/api/passport/status');
  const pets=[];
  for (let offset=0;;) {
    const page=await api('/api/nest?limit=100&offset='+offset);
    pets.push(...page.pets.filter(p=>p.status==='ready'));
    offset+=page.pets.length;
    if (offset>=page.total) break;
    if (!page.pets.length) throw Error('名单发生变化，请刷新重试。');
  }
  el('choices').replaceChildren();
  for (const pet of pets) {
    const label=document.createElement('label'), check=document.createElement('input');
    check.type='checkbox';check.name='pet';check.value=pet.id;
    check.checked=status.pets.includes(pet.id);
    label.append(check);
    const art=pet.asset_ref?'/api/assets/'+encodeURIComponent(pet.asset_ref):['cat','dog','egg'].includes(pet.kind)?'/starter/'+pet.kind+'-sprites-light.webp':null;
    if (art) {
      const sprite=document.createElement('span');sprite.className='pet-art';
      sprite.style.backgroundImage='url("'+art+'")';label.append(sprite);
    }
    label.append(document.createTextNode(pet.name));el('choices').append(label);
  }
  el('empty').hidden=pets.length>0;
  el('host').value=status.host||'';
  if (!status.host) el('address-details').open=true;
  el('confirm').hidden=!status.pending_ticket;
  el('reuse-label').hidden=!status.paired;
  el('reuse').checked=status.paired;
  networkFields();
  el('pairing-form').hidden=false;el('login').hidden=true;
  el('write').disabled=!pets.length||!navigator.serial;
  tell(navigator.serial?'':'请用电脑上的 Chrome 或 Edge 打开本机小屋以连接 USB。');
}
el('login-form').onsubmit=async event=>{
  event.preventDefault();
  const code=el('code').value;el('code').value='';
  try {await api('/api/session',{}, {Authorization:'Bearer '+code});await load();}
  catch(error){tell(error.message);}
};
el('reuse').onchange=networkFields;
el('host').oninvalid=()=>{el('address-details').open=true;};
el('pairing-form').onsubmit=async event=>{
  event.preventDefault();
  const pets=[...el('choices').querySelectorAll('input:checked')].map(c=>c.value);
  if (!pets.length){tell('请先勾选至少一只随身伙伴。');return;}
  if (busy)return;
  const host=el('host').value.trim();
  const address=host.split('.').map(n=>/^\d{1,3}$/.test(n)?Number(n):-1);
  if (address.length!==4||!address.every(n=>n>=0&&n<=255)||!(address[0]===10||address[0]===192&&address[1]===168||address[0]===172&&address[1]>=16&&address[1]<=31)) {
    el('address-details').open=true;el('host').focus();tell('请填写这台电脑在家庭 Wi-Fi 上的 IPv4 地址。');return;
  }
  const network=el('reuse').checked?{reuse:true}:{ssid:el('ssid').value,password:el('password').value};
  busy=true;el('write').disabled=true;el('confirm').hidden=true;
  const unload=e=>{e.preventDefault();e.returnValue='';};
  let device;
  const leave=()=>{device?.close().catch(()=>{});};
  window.addEventListener('beforeunload',unload);
  window.addEventListener('pagehide',leave);
  try {
    const port=await navigator.serial.requestPort({filters:[{usbVendorId:0x303a,usbProductId:0x1001}]});
    tell('正在检查挂件并准备图集，请保持数据线连接。');
    device=new Passport(new RawPort(port));
    const result=await pair(device,api,{pets,host,network,progress:fraction=>{
      el('progress').hidden=false;el('progress').value=fraction;
      tell('正在写入宠物图集 · '+Math.round(fraction*100)+'%');
    }});
    el('password').value='';
    el('reuse-label').hidden=false;el('reuse').checked=true;networkFields();
    confirmation=result.pendingConfirmation;
    el('confirm').hidden=!confirmation;
    tell(confirmation?'挂件已保存图集。请保持小屋运行，点击下方按钮完成确认。':'配对完成。挂件已重新启动，可以拔线选宠了。');
  } catch(error) {
    tell(error.name==='NotFoundError'?'已取消设备选择。':error.name==='NetworkError'?'串口连接中断或正在被占用。请关闭其他安装窗口，重新插线后再试。':error.message);
  } finally {
    busy=false;el('write').disabled=false;el('progress').hidden=true;
    window.removeEventListener('beforeunload',unload);
    window.removeEventListener('pagehide',leave);
  }
};
async function recover(mode) {
  if (busy)return;
  const repair=mode==='wifi';
  if (repair && el('reuse').checked) {
    el('reuse').checked=false;networkFields();el('ssid').focus();
    tell('填好新的家庭网络后，再点一次「只修复这台挂件的 Wi-Fi」。');return;
  }
  const network=repair?{ssid:el('ssid').value,password:el('password').value}:null;
  if (repair && !network.ssid) {tell('请先填写新的家庭 Wi-Fi 名称和密码。');el('ssid').focus();return;}
  busy=true;el('write').disabled=el('repair').disabled=el('confirm').disabled=true;
  let device;
  const unload=e=>{e.preventDefault();e.returnValue='';};
  const leave=()=>device?.close().catch(()=>{});
  window.addEventListener('beforeunload',unload);window.addEventListener('pagehide',leave);
  try {
    if (!repair && confirmation) {
      await api('/api/passport/confirm',{ticket:confirmation});
    } else {
      const port=await navigator.serial.requestPort({filters:[{usbVendorId:0x303a,usbProductId:0x1001}]});
      device=new Passport(new RawPort(port));
      if (!await maintain(device,api,network)) {
        tell('当前挂件仍在使用原图集，或上次配对已经完成。可以重新选宠写入。');return;
      }
    }
    confirmation=null;el('confirm').hidden=true;
    if (repair) {
      el('password').value='';el('reuse').checked=true;networkFields();
      tell('家庭 Wi-Fi 已更新。原来的宠物和记录留在挂件上，连回小屋就会继续同步。');
    } else {await load();tell('小屋已确认当前挂件的图集。');}
  } catch(error){tell(error.name==='NotFoundError'?'已取消设备选择。':error.message);}
  finally {
    window.removeEventListener('beforeunload',unload);window.removeEventListener('pagehide',leave);
    busy=false;el('write').disabled=el('repair').disabled=el('confirm').disabled=false;
  }
}
el('confirm').onclick=()=>recover('confirm');
el('repair').onclick=()=>recover('wifi');
async function openRoom() {
  const code=new URLSearchParams(location.hash.slice(1)).get('key');
  if (location.hash) history.replaceState(null,'',location.pathname);
  if (code) await api('/api/session',{}, {Authorization:'Bearer '+code});
  await load();
}
openRoom().catch(error=>tell(error.message));
