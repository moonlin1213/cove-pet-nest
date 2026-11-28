import { test } from 'node:test';
import assert from 'node:assert/strict';

test('diagnostic refreshes the household state while preserving an unsaved form', async () => {
  const elements = new Map();
  function field(id) {
    if (!elements.has(id)) elements.set(id, {value:'', replaceChildren() {}});
    return elements.get(id);
  }
  globalThis.document = {getElementById:field};
  const config = {
    text:{ready:true}, image:{ready:true}, notes_enabled:false, toys_enabled:false, daily_text_limit:3,
    sources:{relationship:false, life:false, care:false}, feature_status:{notes:'off',toys:'off'}
  };
  const current = {...config, notes_enabled:true, toys_enabled:true, sources:{...config.sources,care:true},
    feature_status:{notes:'waiting_opportunity',toys:'needs_shared_interaction'}};
  globalThis.fetch = async url => Response.json(url.endsWith('jobs') ? [] : url.endsWith('diagnostic')
    ? {stored:true,deduplicated:true,isolated:true,settings:current} : config);
  await import('../../src/cove_pet_nest/web/creation.js');
  await new Promise(setImmediate);
  field('dailyTextLimit').value='8';
  field('notesEnabled').checked=false;
  field('textKey').value='unsaved-fixture';
  await field('diagnose').onclick();
  assert.match(field('sources').textContent,/宠物照顾已收到/);
  assert.match(field('activity').textContent,/惊喜玩具.*互动摘要/);
  assert.equal(field('dailyTextLimit').value,'8');
  assert.equal(field('notesEnabled').checked,false);
  assert.equal(field('textKey').value,'unsaved-fixture');
});
