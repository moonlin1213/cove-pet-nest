import test from 'node:test';
import assert from 'node:assert/strict';
import { pair, validateFiles, RawPort } from '../../src/cove_pet_nest/web/passport-serial.mjs';

const file={path:'/nest/link-b/roster.json',data:'e30=',sha256:'44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'};
const complete=['/nest/link-b/roster.json','/nest/link-b/portrait.json','/nest/link-b/moods.json','/portrait/link-b/p0.bin',...[0,1,3,5].map(i=>'/nest/link-b/p0/pose'+i+'.rgb')].map(path=>({...file,path}));
function fixture(fail=''){
  const events=[], pets=['fox'];
  const device={inspect:async()=>({slot:'a',public:true}),checkpoint:async()=>{events.push('checkpoint');if(fail==='pending')throw Error('pending')},prepare:async()=>events.push('prepare'),stage:async()=>{events.push('stage');if(fail==='hash')throw Error('hash')},commit:async()=>{events.push('commit');if(fail==='unplug')throw Error('unplug')},close:async()=>events.push('close')};
  const api=async(path,body)=>{events.push(path.split('/').pop());if(path.endsWith('status'))return {pending_ticket:null};if(path.endsWith('pack')){assert.deepEqual(body,{pets,slot:'b',host:'192.168.1.2'});return {files:complete,wifi:{host:body.host,port:8768,token:'a'.repeat(64)},ticket:'ticket'}};if(fail==='bind'&&path.endsWith('activate'))throw Error('bind');return {}};
  return {events,device,api,options:{pets,host:'192.168.1.2',network:{ssid:'home',password:'testing'}}};
}
test('old slot stays active until staged files verify and the LAN bridge acknowledges',async()=>{
 const f=fixture();await pair(f.device,f.api,f.options);
 assert.deepEqual(f.events,['status','checkpoint','pack','prepare','stage','activate','commit','confirm','close']);
});
test('failed writes and incomplete household records do not activate a bank',async()=>{
 for(const fail of ['pending','hash','bind','unplug']){
  const f=fixture(fail);await assert.rejects(pair(f.device,f.api,f.options));
  assert.equal(f.events.at(-1),'close');
  if(['hash','pending','bind'].includes(fail))assert(!f.events.includes('commit'));
  assert(!f.events.includes('confirm'));
 }
});
test('unknown firmware is not modified',async()=>{
 const f=fixture();f.device.inspect=async()=>({public:false});await assert.rejects(pair(f.device,f.api,f.options));assert.deepEqual(f.events,['close']);
});
test('pack is restricted to the inactive bank and never supplies wifi or system files',()=>{
 for(const path of ['/nest/link-a/roster.json','/nest/link-b/wifi.json','/nest/link-b/../main.py','/main.py']){
  assert.throws(()=>validateFiles([{...file,path}],'b'));
 }
 assert.throws(()=>validateFiles([file,file],'b'));
});

test('partial manifest cannot switch the current pack',()=>{
  assert.throws(()=>validateFiles(complete.slice(1),'b',1));
  assert.throws(()=>validateFiles(complete.slice(0,-1),'b',1));
  assert.doesNotThrow(()=>validateFiles(complete,'b',1));
});
test('refusing the chooser, insufficient disk, and lost final confirmation are recoverable',async()=>{
  let f=fixture();f.device.inspect=async()=>{throw new DOMException('cancel','NotFoundError');};
  await assert.rejects(pair(f.device,f.api,f.options));assert.deepEqual(f.events,['close']);
  f=fixture();f.device.prepare=async()=>{throw Error('space');};await assert.rejects(pair(f.device,f.api,f.options));assert(!f.events.includes('activate'));
  f=fixture();const api=async(path,body)=>{if(path.endsWith('confirm'))throw Error('lost');return f.api(path,body)};
  assert.deepEqual(await pair(f.device,api,f.options),{pendingConfirmation:'ticket'});
  assert(f.events.includes('commit'));assert.equal(f.events.at(-1),'close');
});

test('re-opening the USB session confirms only the active slot in this household',async()=>{
  for(const [ticket,hash,expected] of [['current','owned',true],['other','owned',false],['current','foreign',false]]){
    const f=fixture();
    f.device.inspect=async()=>({public:true,slot:'a',ticket,tokenHash:hash});
    const api=async(path,body)=>{
      if(path.endsWith('/status'))return {pending_ticket:'current',token_sha256:'owned'};
      return f.api(path,body);
    };
    await pair(f.device,api,f.options);
    assert.equal(f.events[0]==='confirm',expected);
  }
});
