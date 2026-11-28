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
  for (const width of [1100,390]) {
    const c=await br.newContext({viewport:{width,height:850}});
    const page=await c.newPage(), errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(url);
    const box=page.getByRole('dialog',{name:'玩具箱'});
    await page.getByRole('button',{name:'打开玩具箱'}).click();
    await box.getByText('一起读过花园的故事').waitFor();
    await box.getByRole('button',{name:'换个模样'}).click();
    await box.getByRole('button',{name:'摆出来'}).click();
    await box.getByLabel('和谁玩').selectOption({label:'蒲公英'});
    await box.getByRole('button',{name:'给宝宝玩'}).click();
    await box.getByText(/蒲公英.*玩过.*次/).waitFor();
    await box.getByRole('button',{name:'关上'}).click();
    const toy=page.getByRole('button',{name:'移动花园铃'});
    await toy.focus();await Promise.all([page.waitForResponse(r=>r.url().includes('/api/toys/')&&r.request().method()==='PATCH'),toy.press('ArrowRight')]);
    await page.getByRole('button',{name:'打开玩具箱'}).click();
    await box.getByRole('button',{name:'收进箱子'}).click();
    await box.getByRole('button',{name:'关上'}).click();
    await page.getByRole('button',{name:'宠物纸条',exact:true}).click();
    const paper=page.getByRole('dialog',{name:'宠物纸条'});
    await paper.getByText('今天听见了花园铃。').waitFor();
    if(await paper.getByRole('button',{name:'标为已读'}).count())await paper.getByRole('button',{name:'标为已读'}).first().click();
    if(await paper.getByRole('button',{name:'收藏',exact:true}).count())await paper.getByRole('button',{name:'收藏',exact:true}).first().click();
    await paper.getByRole('button',{name:'关上'}).click();
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
