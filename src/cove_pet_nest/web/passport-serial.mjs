const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const encoder = new TextEncoder();
const errors = {
  device: '挂件尚未安装兼容的公开版固件。请先回安装页备份并安装，再来选宠。',
  pending: '旧小屋还有照顾或同行记录待同步。请让挂件和原小屋连接同一家庭 Wi-Fi，等同步完成再试。',
  space: '挂件剩余空间不足。请减少这次带走的宠物数量。',
  foreign: '挂件上有另一座小屋尚未同步的记录。请在原小屋打开配对页，修复家庭 Wi-Fi 并同步后再带它搬家。',
  excluded: '部分待同步记录属于这次未选的灵宠。请一并选上原来的伙伴，或先只修复家庭 Wi-Fi，让挂件回到原小屋同步。',
  owner: '请在这台挂件原来配对的小屋中修复 Wi-Fi。',
  previous: '这台挂件还没有保存这座小屋的 Wi-Fi。请填写家庭网络名称和密码。',
  changed: '挂件当前图集已变化，请重新连接。',
  hash: '挂件上的图集校验失败。请检查数据线，再写入一次。'
};

// Raw REPL on a running public Passport. Binary payloads only travel as base64.
export class RawPort {
  constructor(port) { this.port = port; this.buffer = ''; }
  async start() {
    await this.port.open({baudRate:115200,bufferSize:16384});
    this.opened = true;
    this.reader = this.port.readable.getReader();
    this.writer = this.port.writable.getWriter();
    this.pump = this.readLoop();
    await this.write('\r\x03\x03');
    await sleep(140);
    this.buffer = '';
    await this.write('\r\x01');
    await this.until('raw REPL; CTRL-B to exit\r\n>', 6000);
  }
  async readLoop() {
    const decoder = new TextDecoder();
    try {
      while (true) {
        const {value,done} = await this.reader.read();
        if (done) break;
        this.buffer += decoder.decode(value,{stream:true});
        if (this.buffer.length > 65536) throw Error('串口响应过长');
        this.wake?.();
      }
    } catch { /* The waiting operation reports a disconnected device. */ }
    finally { this.ended = true; this.wake?.(); }
  }
  async until(marker, timeout=12000) {
    const limit = Date.now()+timeout;
    for (;;) {
      const at = this.buffer.indexOf(marker);
      if (at >= 0) {
        const before = this.buffer.slice(0,at);
        this.buffer = this.buffer.slice(at+marker.length);
        return before;
      }
      if (this.ended) throw Error('挂件已断开，请重新插入数据线。');
      if (Date.now() >= limit) throw Error('挂件没有响应。请关闭其他串口窗口；原厂挂件需先在安装页安装公开版。');
      await new Promise(resolve => {
        const timer = setTimeout(resolve,limit-Date.now());
        this.wake = () => { clearTimeout(timer); resolve(); };
      });
      this.wake = null;
    }
  }
  write(text) { return this.writer.write(encoder.encode(text)); }
  async exec(source, timeout=12000) {
    // MicroPython raw REPL accepts 256-byte writes with short pacing.
    const bytes = encoder.encode(source);
    for (let pos=0;pos<bytes.length;pos+=256) {
      await this.writer.write(bytes.subarray(pos,pos+256));
      if (pos+256 < bytes.length) await sleep(10);
    }
    await this.write('\x04');
    const out = await this.until('\x04', timeout);
    const err = await this.until('\x04');
    await this.until('>');
    if (!out.startsWith('OK') || err) {
      const code = err.trim().split(': ').at(-1);
      throw Error(errors[code] || '挂件没有完成写入，请检查剩余空间和数据线后重试。');
    }
    return out.slice(2).trim();
  }
  async close() {
    if (!this.opened) return;
    this.opened = false;
    if (this.writer) {
      try {
        await this.write('\r\x03\x02');
        await sleep(50);
        await this.write('\x04');
      } catch { /* USB can disappear during a reset. */ }
      this.writer.releaseLock();
    }
    if (this.reader) {
      try { await this.reader.cancel(); } catch {}
      await this.pump;
      this.reader.releaseLock();
    }
    try { await this.port.close(); } catch {}
  }
}

const probe = `import os,json,hashlib,binascii,time
def _pp_slot():
 if 'pocket-pack.json' not in os.listdir('/'):return '-'
 with open('/pocket-pack.json') as f:slot=json.load(f)['slot']
 if slot not in ('a','b'):raise ValueError('changed')
 return slot
def _pp_probe():
 if 'passport-public-v1' not in os.listdir('/'):return {'public':False}
 with open('/passport-public-v1') as f:version=f.read().strip()
 if version!='0.2.0':return {'public':False}
 active=globals().get('session')
 if active:
  active.book.advance(time.ticks_ms())
  active.book.choose(None)
 slot=_pp_slot()
 info={'public':True,'slot':slot}
 if slot!='-':
  with open('/nest/link-'+slot+'/wifi.json') as f:old=json.load(f)
  info['ticket']=old.get('pairing_ticket','')
  info['tokenHash']=binascii.hexlify(hashlib.sha256(old['token'].encode()).digest()).decode()
 return info
print(json.dumps(_pp_probe()))`;

const checkpoint = `import time,hashlib,binascii,gc
gc.collect()
def _pp_checkpoint():
 queued=set()
 if 'care-pending.json' in os.listdir('/'):
  with open('/care-pending.json') as f:legacy=json.load(f)
  ids=legacy.get('pet_ids')
  if not ids:raise ValueError('pending')
  queued.update(ids)
 if _pp_slot()=='-':return queued
 active=globals().get('session')
 if active and not active.starter:
  book=active.book
  end=time.ticks_add(time.ticks_ms(),9000)
  online=globals().get('wlan')
  while online and online.isconnected() and book.rows and time.ticks_diff(end,time.ticks_ms())>0:
   active.tick(time.ticks_ms(),True)
   time.sleep_ms(35)
  rows=book.rows
 else:
  with open('/nest/link-'+_pp_slot()+'/wifi.json') as f:old=json.load(f)
  tag=binascii.hexlify(hashlib.sha256(old['token'].encode()).digest()[:8]).decode()
  from wear_journal import Journal
  rows=Journal('/wear-'+tag,None,time.ticks_ms(),None).rows
 queued.update(row['pet'] for row in rows)
 return queued
_pp_queued=_pp_checkpoint()`;

function bin64(text) { return btoa(Array.from(encoder.encode(text), b => String.fromCharCode(b)).join('')); }
const pyString = s => JSON.stringify(s); // Used only for validated ASCII paths, slots and base64.
export function validateFiles(files,slot,petCount) {
  if (!['a','b'].includes(slot) || !Array.isArray(files) || !files.length) throw Error(errors.changed);
  const allowed=new RegExp('^/(?:nest/link-'+slot+'/(?:(?:portrait|roster|moods)\\.json|p[0-9]+/pose[0135]\\.rgb)|portrait/link-'+slot+'/p[0-9]+\\.bin)$');
  const paths=new Set();
  for (const file of files) {
    if (!allowed.test(file.path) || paths.has(file.path) || !/^[a-f0-9]{64}$/.test(file.sha256) || typeof file.data!=='string' || !/^[A-Za-z0-9+/]+={0,2}$/.test(file.data) || file.data.length%4!==0)
      throw Error('小屋生成的图集格式有误，请检查小屋版本。');
    paths.add(file.path);
  }
  const nest='/nest/link-'+slot+'/';
  const expected=['roster','portrait','moods'].map(name=>nest+name+'.json');
  for(let i=0;i<petCount;i++){
    expected.push('/portrait/link-'+slot+'/p'+i+'.bin');
    for(const pose of [0,1,3,5])expected.push(nest+'p'+i+'/pose'+pose+'.rgb');
  }
  if(paths.size!==expected.length||expected.some(path=>!paths.has(path)))
    throw Error('图集缺少宠物文件，请刷新名单后再试。');
}

export class Passport {
  constructor(raw) { this.raw=raw; }
  close() { return this.raw.close(); }
  async inspect() {
    await this.raw.start();
    return JSON.parse(await this.raw.exec(probe));
  }
  checkpoint() { return this.raw.exec(checkpoint,20000); }
  async prepare(slot,pack,network,pets) {
    const wifi={host:pack.wifi.host,port:pack.wifi.port,token:pack.wifi.token,pairing_ticket:pack.ticket};
    if (!network.reuse) {
      if (!network.ssid || encoder.encode(network.ssid).length>32 || encoder.encode(network.password).length>63) throw Error('请检查 Wi-Fi 名称和密码。');
      Object.assign(wifi,{ssid:network.ssid,password:network.password});
    }
    const configured=bin64(JSON.stringify(wifi));
    const blocks=pack.files.reduce((total,file)=>total+Math.ceil(file.data.length*0.75/4096)*4096,0);
    // Only generated files below the inactive bank may be reclaimed. The
    // allowlisted walk will not descend into or remove unknown directories.
    await this.raw.exec(`import re
_pp_inactive=${pyString(slot)}
if _pp_slot()==_pp_inactive:raise ValueError('changed')
_pp_wifi=json.loads(binascii.a2b_base64(${pyString(configured)}))
old={}
if _pp_slot()!='-':
 with open('/nest/link-'+_pp_slot()+'/wifi.json') as f:old=json.load(f)
same=old.get('token')==_pp_wifi['token']
if _pp_queued:
 if not same:raise ValueError('foreign')
 selected=json.loads(binascii.a2b_base64(${pyString(bin64(JSON.stringify(pets)))}))
 if any(p not in selected for p in _pp_queued):raise ValueError('excluded')
if 'ssid' not in _pp_wifi:
 if not same or not old.get('ssid'):raise ValueError('previous')
 _pp_wifi.update(ssid=old['ssid'],password=old['password'])
def _pp_mkdir(path):
 try:os.mkdir(path)
 except OSError as e:
  if e.args[0]!=17:raise
def _pp_clean():
 for root in ('/nest/link-'+_pp_inactive,'/portrait/link-'+_pp_inactive):
  _pp_mkdir(root)
  for n in os.listdir(root):
   path=root+'/'+n
   if root.startswith('/portrait/'):
    if re.match('^p[0-9]+\\\\.bin$',n):os.remove(path)
   elif n in ('wifi.json','roster.json','portrait.json','moods.json'):os.remove(path)
   elif re.match('^p[0-9]+$',n):
    for name in os.listdir(path):
     if name in ('pose0.rgb','pose1.rgb','pose3.rgb','pose5.rgb'):os.remove(path+'/'+name)
    if not os.listdir(path):os.rmdir(path)
_pp_clean()
s=os.statvfs('/')
if s[0]*s[3]<${blocks+20480}:raise ValueError('space')
def _pp_verify(path,expected):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  while True:
   chunk=f.read(1024)
   if not chunk:break
   h.update(chunk)
 if binascii.hexlify(h.digest()).decode()!=expected:raise ValueError('hash')`);
  }
  async stage(slot,pack,progress) {
    let done=0;
    const total=pack.files.reduce((n,file)=>n+file.data.length,0);
    for (const file of pack.files) {
      const name=pyString(file.path);
      const dir=pyString(file.path.slice(0,file.path.lastIndexOf('/')));
      await this.raw.exec(`_pp_mkdir(${dir})\n_pp_out=open(${name},'wb')`);
      for (let pos=0;pos<file.data.length;pos+=4096) {
        const block=file.data.slice(pos,pos+4096);
        await this.raw.exec(`_pp_out.write(binascii.a2b_base64('${block}'))`);
        done+=block.length; progress?.(done/total);
      }
      await this.raw.exec(`_pp_out.close()\n_pp_verify(${name},${pyString(file.sha256)})`);
    }
    const path=pyString('/nest/link-'+slot+'/wifi.json');
    await this.raw.exec(`with open(${path},'w') as f:json.dump(_pp_wifi,f)\nwith open(${path}) as f:\n if json.load(f)!=_pp_wifi:raise ValueError('hash')`);
  }
  async repairNetwork(network) {
    const encoded=pyString(bin64(JSON.stringify({ssid:network.ssid,password:network.password})));
    await this.raw.exec(`with open('/nest/link-'+_pp_slot()+'/wifi.json') as f:cfg=json.load(f)
cfg.update(json.loads(binascii.a2b_base64(${encoded})))
target='/nest/link-'+_pp_slot()+'/wifi.json'
with open(target+'.new','w') as f:json.dump(cfg,f)
with open(target+'.new') as f:
 if json.load(f)!=cfg:raise ValueError('hash')
os.rename(target+'.new',target)`);
  }
  async commit(slot) {
    await this.raw.exec(`if _pp_slot()==${pyString(slot)}:raise ValueError('changed')\nwith open('/pocket-pack.new','w') as f:json.dump({'slot':${pyString(slot)}},f)\nos.rename('/pocket-pack.new','/pocket-pack.json')\nif _pp_slot()!=${pyString(slot)}:raise ValueError('changed')`);
  }
}

async function restoreConfirmation(info,status,api) {
  if (info.ticket && info.ticket===status.pending_ticket && info.tokenHash===status.token_sha256) {
    await api('/api/passport/confirm',{ticket:info.ticket});
    return true;
  }
  return false;
}

export async function maintain(device,api,network) {
  try {
    const info=await device.inspect();
    if (!info.public) throw Error(errors.device);
    const status=await api('/api/passport/status');
    if (!info.tokenHash || info.tokenHash!==status.token_sha256) throw Error(errors.owner);
    const restored=await restoreConfirmation(info,status,api);
    if (!network) return restored;
    if (!network.ssid || encoder.encode(network.ssid).length>32 || encoder.encode(network.password).length>63)
      throw Error('请填写新的家庭 Wi-Fi 名称和密码。');
    await device.checkpoint();
    await device.repairNetwork(network);
    return true;
  } finally {await device.close();}
}

export async function pair(device,api,{pets,host,network,progress}) {
  try {
    const info=await device.inspect();
    if (!info.public) throw Error(errors.device);
    if (!['a','b','-'].includes(info.slot)) throw Error(errors.changed);
    const slot=info.slot==='a'?'b':'a';
    const status=await api('/api/passport/status');
    await restoreConfirmation(info,status,api);
    await device.checkpoint();
    const pack=await api('/api/passport/pack',{pets,slot,host});
    validateFiles(pack.files,slot,pets.length);
    await device.prepare(slot,pack,network,pets);
    await device.stage(slot,pack,progress);
    await api('/api/passport/activate',{ticket:pack.ticket});
    await device.commit(slot);
    try { await api('/api/passport/confirm',{ticket:pack.ticket}); }
    catch { return {pendingConfirmation:pack.ticket}; }
    return {};
  } finally { await device.close(); }
}
