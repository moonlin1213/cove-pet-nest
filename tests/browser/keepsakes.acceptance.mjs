/* Start a private keepsakes fixture with keepsakes_fixture.py, then set NEST_TEST_URL.
   Reuses the installed software and fixtures, never an existing room. */
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const url=process.env.NEST_TEST_URL;
assert(url && new URL(url).hostname==='127.0.0.1');
const br=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE||undefined});
try {
  let firstPlayTime;
  for (const width of [1100,390]) {
    const c=await br.newContext({viewport:{width,height:850}});
    const page=await c.newPage(), errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(()=>{
      const interval=window.setInterval.bind(window);
      window.setInterval=(fn,ms,...args)=>{
        if(ms===10000)window.fixtureRoomPoll=fn;
        return interval(fn,ms,...args);
      };
    });
    await page.goto(url);
    const box=page.getByRole('dialog',{name:'玩具箱'});
    await page.getByRole('button',{name:'打开玩具箱'}).click();
    await box.getByText('一起读过花园的故事').waitFor();
    await box.getByRole('button',{name:'换个模样'}).click();
    await box.getByRole('button',{name:'摆出来'}).click();
    await box.getByLabel('和谁玩').selectOption({label:'蒲公英'});
    if(width===1100){
      let committedId;
      await page.route('**/api/toys/*/play',async route=>{
        committedId=route.request().postDataJSON().request_id;
        assert.equal((await route.fetch()).status(),200);
        firstPlayTime=Date.now();
        await route.abort('failed');
      },{times:1});
      await box.getByRole('button',{name:'给宝宝玩'}).click();
      await page.waitForFunction(()=>document.querySelector('#collectionStatus').textContent.length>0);
      await page.reload();await page.getByRole('button',{name:'打开玩具箱'}).click();
      const next=page.waitForRequest(r=>r.url().endsWith('/play'));
      await box.getByRole('button',{name:'给宝宝玩'}).click();
      assert.equal((await next).postDataJSON().request_id,committedId,'lost receipt must replay the same request after reload');
    }else{
      // The same fictional room carries one confirmed play across both viewports.
      const remainingCooldown=firstPlayTime+5100-Date.now();
      if(remainingCooldown>0)await new Promise(done=>setTimeout(done,remainingCooldown));
      const receipt=page.waitForResponse(r=>r.url().endsWith('/play'));
      await box.getByRole('button',{name:'给宝宝玩'}).click();
      const response=await receipt;
      assert.equal(response.status(),200);
      assert.equal((await response.json()).count,2);
    }
    const expectedPlays=width===1100?1:2;
    await box.getByText('蒲公英玩过 '+expectedPlays+' 次',{exact:true}).waitFor();
    await box.getByRole('button',{name:'关上'}).click();
    const toy=page.getByRole('button',{name:'移动花园铃'});
    await toy.focus();
    const initialLeft=await toy.evaluate(el=>el.style.left);
    await page.keyboard.press('ArrowRight');
    await page.waitForFunction(previous=>document.querySelector('.room-toy').style.left!==previous,initialLeft);
    assert(await toy.evaluate(el=>el===document.activeElement),'arrow movement must retain focus after rendering its receipt');
    const nextLeft=await toy.evaluate(el=>el.style.left);
    await page.keyboard.press('ArrowRight');
    await page.waitForFunction(previous=>document.querySelector('.room-toy').style.left!==previous,nextLeft);
    const toyHandle=await toy.elementHandle(),rect=await toy.boundingBox();
    await page.mouse.move(rect.x+rect.width/2,rect.y+rect.height/2);await page.mouse.down();
    await page.mouse.move(rect.x+rect.width/2+20,rect.y+rect.height/2);
    await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/keepsakes')),page.evaluate(()=>window.fixtureRoomPoll())]);
    await page.evaluate(()=>new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done))));
    assert(await toyHandle.evaluate(el=>el.isConnected && el.matches(':active')),'periodic refresh must preserve dragged element');
    await Promise.all([page.waitForResponse(r=>r.url().includes('/api/toys/')&&r.request().method()==='PATCH'),page.mouse.up()]);
    await page.getByRole('button',{name:'打开玩具箱'}).click();
    await box.getByRole('button',{name:'收进箱子'}).click();
    await box.getByRole('button',{name:'关上'}).click();
    await page.getByRole('button',{name:'宠物纸条',exact:true}).click();
    const paper=page.getByRole('dialog',{name:'宠物纸条'});
    await paper.getByText('今天听见了花园铃。').waitFor();
    if(await paper.getByRole('button',{name:'标为已读'}).count())await paper.getByRole('button',{name:'标为已读'}).first().click();
    if(await paper.getByRole('button',{name:'收藏',exact:true}).count())await paper.getByRole('button',{name:'收藏',exact:true}).first().click();
    if(width===1100){
      let release,started;
      const hold=new Promise(resolve=>release=resolve),pending=new Promise(resolve=>started=resolve);
      await page.route('**/api/notes/*',async r=>{const reply=await r.fetch();started();await hold;await r.fulfill({response:reply});},{times:1});
      const mark=paper.locator('.nest-note button').first();
      await mark.evaluate(el=>{
        const run=el.onclick;
        el.onclick=function(...args){return window.fixtureMutationSettled=run.apply(this,args);};
      });
      await mark.click();await pending;
      await paper.getByRole('button',{name:'关上'}).click();await page.getByRole('button',{name:'打开玩具箱'}).click();
      await box.getByText('一起读过花园的故事').waitFor();
      const acknowledged=page.waitForResponse(r=>r.url().includes('/api/notes/'));
      release();await acknowledged;
      await page.evaluate(()=>window.fixtureMutationSettled);
      assert(await box.getByRole('button',{name:'换个模样'}).isVisible(),'old note callback cannot paint over toy box');
      await box.getByRole('button',{name:'关上'}).click();
    }else await paper.getByRole('button',{name:'关上'}).click();
    await page.getByRole('button',{name:'细雨 · 蛇'}).click();
    await page.getByRole('button',{name:'布置栖息地'}).click();
    const habitat=page.getByRole('dialog',{name:'细雨的栖息地'});
    await habitat.getByLabel('主题').selectOption('moss_forest');
    await habitat.getByLabel('添加装饰').selectOption('fern');await habitat.getByRole('button',{name:'加入'}).click();
    await habitat.getByRole('button',{name:'保存布置'}).click();
    await habitat.getByText('布置已保存。').waitFor();await habitat.getByRole('button',{name:'关上'}).click();
    await page.reload();await page.getByRole('button',{name:'细雨 · 蛇'}).click();await page.getByRole('button',{name:'布置栖息地'}).click();
    assert.equal(await habitat.getByLabel('主题').inputValue(),'moss_forest');assert(await habitat.getByRole('button',{name:'蕨类',exact:true}).count()>=1);
    assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)));assert.deepEqual(errors,[]);
    await c.close();console.log('Keepsake controls PASS at',width);
  }
}finally{await br.close();}
