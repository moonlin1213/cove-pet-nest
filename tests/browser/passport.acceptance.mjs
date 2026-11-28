/* Run from the public core checkout with the Passport repo next to it.
   NEST_FIXTURE_PYTHON points at Python with the core dependencies. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,readFile,writeFile,mkdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve,basename} from 'node:path';
import {createRequire} from 'node:module';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import {createHash} from 'node:crypto';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const py=process.env.NEST_FIXTURE_PYTHON||'python3', repo=process.cwd();
const site=process.env.PASSPORT_INSTALL_DIR||resolve('../cove-pet-nest-passport/docs/install');
const tmp=await mkdtemp(join(tmpdir(),'passport-browser-')), board=join(tmp,'board');
await mkdir(board);await mkdir(join(board,'nest'));await mkdir(join(board,'portrait'));
const firmware=JSON.parse(await readFile(join(site,'image.json'),'utf8'));
await writeFile(join(board,'passport-public-v1'),firmware.version);
const env={...process.env,PET_NEST_DATA_DIR:join(tmp,'room'),PYTHONPATH:join(repo,'src'),PYTHONDONTWRITEBYTECODE:'1'};
const serverSource=`
import asyncio,json,socket,sys,uvicorn
from pathlib import Path
from cove_pet_nest.config import Settings
from cove_pet_nest.service import build_service
from cove_pet_nest.http import create_app
from cove_pet_nest.passport import pairing
from cove_pet_nest.auth import credentials
folder=Path(sys.argv[1]);service=build_service(Settings(folder))
for kind,name in [('cat','杏仁'),('dog','银杏')]:service.adopt(kind,name,'fixture-'+kind,actor='user')
listen=pairing.listen
def local(service,host,port,config):
 server=listen(service,'127.0.0.1',0,config)
 (folder/'fixture-port').write_text(str(server.server_address[1]))
 return server
pairing.listen=local
s=socket.socket();s.bind(('127.0.0.1',0));print(s.getsockname()[1],flush=True)
asyncio.run(uvicorn.Server(uvicorn.Config(create_app(service),log_level='error')).serve(sockets=[s]))
`;
const core=spawn(py,['-u','-c',serverSource,env.PET_NEST_DATA_DIR],{env,stdio:['ignore','pipe','inherit']});
const simSource=`
import sys,os,types,pathlib,json,contextlib,io,builtins
root=pathlib.Path(sys.argv[1]).resolve()
def path(p):
 p=(root/str(p).lstrip('/')).resolve();assert p==root or root in p.parents;return p
fs=types.SimpleNamespace(listdir=lambda p:os.listdir(path(p)),mkdir=lambda p:os.mkdir(path(p)),remove=lambda p:os.remove(path(p)),rmdir=lambda p:os.rmdir(path(p)),rename=lambda a,b:os.replace(path(a),path(b)),statvfs=lambda p:os.statvfs(path(p)))
def ledger(name,*_):
 records=[json.loads(path(name+str(i)).read_text()) for i in range(2) if path(name+str(i)).exists()]
 return types.SimpleNamespace(rows=max(records,key=lambda r:r[0])[1] if records else [])
journal=types.SimpleNamespace(Journal=ledger)
imp=builtins.__import__
def imported(name,*args):
 if name=='os':return fs
 if name=='wear_journal':return journal
 if name=='time':return types.SimpleNamespace(ticks_ms=lambda:0)
 return imp(name,*args)
sandbox={'__builtins__':dict(vars(builtins),__import__=imported,open=lambda p,*a,**k:open(path(p),*a,**k))}
for line in sys.stdin:
 src=json.loads(line);buf=io.StringIO();err=''
 try:
  with contextlib.redirect_stdout(buf):exec(src,sandbox)
 except Exception as e:err=type(e).__name__+': '+str(e)
 print(json.dumps([buf.getvalue(),err]),flush=True)
`;
const simulator=spawn(py,['-u','-c',simSource,board],{env,stdio:['pipe','pipe','inherit']});
const simulatorLines=createInterface({input:simulator.stdout})[Symbol.asyncIterator]();
async function deviceExec(src) {
  simulator.stdin.write(JSON.stringify(src)+'\n');
  const r=await simulatorLines.next();if(r.done)throw Error('USB fixture exited');
  return JSON.parse(r.value);
}
let browser;
try {
 const first=await createInterface({input:core.stdout})[Symbol.asyncIterator]().next();
 assert(!first.done,'local room did not start');const port=Number(first.value),base='http://127.0.0.1:'+port;
 for(let i=0;i<60;i++){try{if((await fetch(base)).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE||undefined});
 const ctx=await browser.newContext(), install='https://passport-fixture.example/install/';
 await ctx.route(install+'**',async r=>{
   const name=basename(new URL(r.request().url()).pathname)||'index.html';
   const filename=name==='install'?'index.html':name;
   await r.fulfill({body:await readFile(join(site,filename)),contentType:{html:'text/html',css:'text/css',js:'text/javascript',png:'image/png',json:'application/json'}[filename.split('.').at(-1)]});
 });
 let disconnect=false;
 await ctx.exposeBinding('fixtureExec',async(_,source)=>{
   if(disconnect&&source.startsWith('_pp_out.write')){disconnect=false;return {unplug:true};}
   const [out,err]=await deviceExec(source);if(err)console.error('Mock board command failed',err);return {out,err};
 });
 await ctx.addInitScript(()=>{
   // The mock has no hardware receive FIFO; elide inter-packet pacing only.
   const delay=window.setTimeout.bind(window);
   window.setTimeout=(fn,ms,...args)=>delay(fn,ms===10?0:ms,...args);
   Object.defineProperty(navigator,'serial',{value:{requestPort:async()=> {
     let controller,code='';
     return {open:async()=>{},close:async()=>{},
       readable:new ReadableStream({start(c){controller=c;}}),
       writable:new WritableStream({async write(bytes){
         const s=new TextDecoder().decode(bytes), put=text=>controller.enqueue(new TextEncoder().encode(text));
         if(s==='\r\x01'){code='';put('raw REPL; CTRL-B to exit\r\n>');return;}
         if(s.includes('\x03')||s.includes('\x02')){code='';return;}
         if(s!=='\x04'){code+=s;return;}
         if(!code)return;
         const r=await window.fixtureExec(code);code='';
         if(r.unplug){controller.close();throw new DOMException('disconnect','NetworkError');}
         put('OK'+r.out+'\x04'+r.err+'\x04>');
       }})};
   }}});
 });
 const installer=await ctx.newPage();await installer.goto(install);
 await installer.getByText('小屋打不开，或使用了其他端口？',{exact:true}).click();
 await installer.locator('#room-port').fill(String(port));
 const ready=ctx.waitForEvent('page');await installer.getByRole('button',{name:'连接我已有的灵宠屋'}).click();const page=await ready;
 await page.locator('#login').waitFor({state:'visible'});
 const creds=JSON.parse(await readFile(join(env.PET_NEST_DATA_DIR,'credentials.json')));
 await page.locator('#code').fill(creds.browser_token);await page.locator('#login-form button').click();
 await page.getByLabel('杏仁',{exact:true}).check();await page.getByLabel('银杏',{exact:true}).check();
 await page.locator('#ssid').fill('FixtureHome');await page.locator('#password').fill('only-fixture-secret');
 await page.locator('#address-details').evaluate(el=>el.open=true);
 await page.locator('#host').fill('192.168.1.23');
 const sends=[];
 page.on('request',r=>{if(r.method()==='POST')sends.push(r.postData()||'');});
 const click=async()=>{await page.locator('#write').click();await page.waitForFunction(()=>!document.querySelector('#write').disabled,{},{timeout:150000});};
 await click();
 assert.match(await page.locator('#notice').textContent(),/配对完成/);
 const slot=async()=>JSON.parse(await readFile(join(board,'pocket-pack.json'))).slot;
 assert.equal(await slot(),'a');
 const bank=join(board,'nest/link-a');
 const roster=JSON.parse(await readFile(join(bank,'roster.json'))).pets;
 assert.deepEqual(new Set(roster.map(p=>p.name)),new Set(['杏仁','银杏']));
 const art=JSON.parse(await readFile(join(bank,'portrait.json')));
 for(const pet of roster)assert((await readFile(join(board,'portrait',art[pet.id].file))).length>100);
 assert(!sends.join('').includes('FixtureHome'));assert(!sends.join('').includes('only-fixture-secret'));
 // First pairing must immediately-enable credential reuse, with no reload.
 assert(await page.locator('#reuse').isChecked());
 assert.equal(await page.locator('#password').inputValue(),'');
 const priorWifi=JSON.parse(await readFile(join(bank,'wifi.json')));
 const oldSecret=priorWifi.token;
 const journal=join(board,'wear-'+createHash('sha256').update(oldSecret).digest('hex').slice(0,16)+'1');
 const pendingPet=roster.find(p=>p.name==='银杏').id;
 const saved=JSON.stringify([23,[{id:'passport-'+'8'.repeat(32),pet:pendingPet,op:'wear',seconds:75,at:0,boot:'fixture',floor:null}],null]);
 await writeFile(journal,saved);
 // An unrelated household cannot adopt another home's saved credentials or records.
 const foreignToken='3'.repeat(64);
 const foreignJournal=join(board,'wear-'+createHash('sha256').update(foreignToken).digest('hex').slice(0,16)+'1');
 await writeFile(join(bank,'wifi.json'),JSON.stringify({...priorWifi,token:foreignToken,pairing_ticket:'0'.repeat(32)}));
 await writeFile(foreignJournal,saved);
 await click();assert.match(await page.locator('#notice').textContent(),/另一座小屋/);assert.equal(await slot(),'a');
 await rm(foreignJournal);await click();assert.match(await page.locator('#notice').textContent(),/没有保存这座小屋/);
 await writeFile(join(bank,'wifi.json'),JSON.stringify(priorWifi));
 await page.getByLabel('银杏',{exact:true}).uncheck();
 await click();assert.match(await page.locator('#notice').textContent(),/未选的灵宠/);assert.equal(await slot(),'a');
 // Recover Wi-Fi while keeping even uncalibrated journal rows and the old slot.
 await page.locator('#reuse').uncheck();await page.locator('#ssid').fill('NewFixtureHome');await page.locator('#password').fill('corrected-fixture');
 await page.locator('#repair').click();await page.getByRole('status').filter({hasText:'家庭 Wi-Fi 已更新'}).waitFor();
 assert.equal(await slot(),'a');assert.equal(await readFile(journal,'utf8'),saved);
 assert.equal(JSON.parse(await readFile(join(bank,'wifi.json'))).token,oldSecret);
 await page.getByLabel('银杏',{exact:true}).check();await page.getByLabel('杏仁',{exact:true}).uncheck();
 disconnect=true;await click();assert.match(await page.locator('#notice').textContent(),/中断|断开|占用/);
 assert.equal(await slot(),'a');assert.equal(JSON.parse(await readFile(join(bank,'roster.json'))).pets.length,2);
 // Lose the final HTTP request entirely, then recover from the active bank on reload.
 await page.route('**/api/passport/confirm',r=>r.abort('connectionreset'),{times:1});
 await click();assert.match(await page.locator('#notice').textContent(),/完成确认/);assert.equal(await slot(),'b');
 const fresh=JSON.parse(await readFile(join(board,'nest/link-b/roster.json'))).pets;
 assert.deepEqual(fresh.map(p=>p.name),['银杏']);
 const wifi=JSON.parse(await readFile(join(board,'nest/link-b/wifi.json')));
 assert.equal(wifi.ssid,'NewFixtureHome');assert.equal(wifi.password,'corrected-fixture');assert.equal(wifi.token,oldSecret);
 assert.equal(await readFile(journal,'utf8'),saved);
 await page.reload();await page.locator('#confirm').waitFor({state:'visible'});
 // A failed status query or a confirmation-only visit must checkpoint current wear.
 await deviceExec("def _save_test(_):\n with open('/fixture-saved','a') as file:file.write('saved\\n')\nclass Book:\n def advance(self,_):pass\n def choose(self,pet):_save_test(pet)\nclass Live:\n book=Book()\n starter=False\nsession=Live()");
 await page.route('**/api/passport/status',r=>r.abort('connectionreset'),{times:1});
 await page.locator('#confirm').click();await page.waitForFunction(()=>!document.querySelector('#confirm').disabled);
 assert.equal((await readFile(join(board,'fixture-saved'),'utf8')).trim(),'saved');
 await page.locator('#confirm').click();await page.getByRole('status').filter({hasText:'已确认当前挂件'}).waitFor();
 assert.equal((await readFile(join(board,'fixture-saved'),'utf8')).trim(),'saved\nsaved');
 assert(await page.getByLabel('银杏',{exact:true}).isChecked());assert(!await page.getByLabel('杏仁',{exact:true}).isChecked());
 assert(!sends.join('').includes('corrected-fixture'));
 const owned=fresh[0].id;
 await page.close();await installer.close();
 const gate='http://127.0.0.1:'+(await readFile(join(env.PET_NEST_DATA_DIR,'fixture-port'),'utf8'));
 const row={id:'passport-'+'2'.repeat(32),pet:owned,op:'wear',at:Math.floor(Date.now()/1000)-3610,seconds:3600};
 const record=async()=>{const r=await fetch(gate+'/companion',{method:'POST',headers:{Authorization:'Bearer '+wifi.token},body:JSON.stringify(row)});assert.equal(r.status,200);return r.json();};
 const one=await record();assert.equal(one.bonus,1);assert.deepEqual(await record(),one);
 console.log('Chrome + actual local HTTP room + fixture raw serial: 2 original pets/assets verified; no-reload re-pair; uncalibrated journal preserved; excluded pet protected; Wi-Fi repaired in place; disconnect preserved slot a; confirmed active slot b after lost acknowledgement and browser reload; after closing pages one offline growth receipt counted once.');
} finally {
 if(browser)await browser.close();simulator.stdin.end();core.kill();await Promise.all([core,simulator].map(c=>c.exitCode!==null||c.signalCode!==null?Promise.resolve():once(c,'exit')));await rm(tmp,{recursive:true,force:true});
}
