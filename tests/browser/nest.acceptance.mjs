import {createRequire} from 'node:module';
import {readFile, mkdir} from 'node:fs/promises';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const base=process.env.NEST_URL||'http://127.0.0.1:8767';
const dir=process.env.NEST_TEST_DATA_DIR;
assert(dir,'NEST_TEST_DATA_DIR must point to a new test instance, never your personal data');
const creds=JSON.parse(await readFile(`${dir}/credentials.json`,'utf8'));
const output=process.env.NEST_SCREENSHOT_DIR||`${dir}/screenshots`;
await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||undefined});
try {
  for (const [label,width,height] of [['desktop',1280,800],['mobile',390,844]]) {
    const context=await browser.newContext({viewport:{width,height},reducedMotion:'reduce'});
    const errors=[];
    const page=await context.newPage();
    page.on('pageerror',e=>errors.push(e.message));
    const login=await context.request.post(`${base}/api/session`,{headers:{Authorization:`Bearer ${creds.browser_token}`}});
    assert.equal(login.status(),200);
    await page.goto(base); await page.locator('#room').waitFor({state:'visible'});
    await page.getByRole('button',{name:'领养宝宝',exact:true}).click();
    await page.locator('#kind').selectOption(label==='desktop'?'cat':'dog');
    await page.locator('#petName').fill(label==='desktop'?'团团':'绒绒');
    await page.getByRole('button',{name:'接回家',exact:true}).click();
    await page.locator('#adoptDialog').waitFor({state:'hidden'});
    await page.getByRole('button',{name:label==='desktop'?'照顾团团':'照顾绒绒',exact:true}).last().click();
    await page.getByRole('button',{name:'喂食',exact:true}).click();
    await page.locator('#careDialog').waitFor({state:'hidden'});
    assert.match(await page.locator('#message').innerText(),/吃饱/);
    await page.reload(); await page.locator('#room').waitFor({state:'visible'});
    const before=await page.locator('#grains').innerText();
    await page.getByRole('button',{name:label==='desktop'?'照顾团团':'照顾绒绒',exact:true}).last().click();
    await page.getByRole('button',{name:'喂食',exact:true}).click();
    await page.locator('#careDialog').waitFor({state:'hidden'});
    assert.match(await page.locator('#message').innerText(),/已经吃饱/);
    assert.equal(await page.locator('#grains').innerText(),before);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.deepEqual(errors,[]);
    await page.screenshot({path:`${output}/${label}.png`,fullPage:true});
    await context.close();
  }
  console.log('desktop/mobile: adoption, care receipts, persistence, full/no-debit, no horizontal overflow passed');
} finally {await browser.close();}
