// UI regression against real built assets, with isolated /api routes: no user credentials are read or written.
const {chromium} = require('../frontend/node_modules/playwright');
const assert = require('node:assert/strict');

(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  let saved={provider:'deepseek',base_url:'https://saved.example/custom/v1',model:'saved-model',has_key:true,secret_storage:'system',timeout:90,concurrency:2,max_tokens:4096,mcp:{connected:true,tools:['search','get_chunk_context']}};
  let saves=0,fetches=0,failFetch=false;
  const navigation=[];page.on('framenavigated',f=>{if(f===page.mainFrame())navigation.push(f.url())});
  await page.route('**/api/**',async route=>{
    const request=route.request(),pathname=new URL(request.url()).pathname,method=request.method();
    let body={};
    if(pathname==='/api/settings'&&method==='GET'){await new Promise(r=>setTimeout(r,120));body=saved;}
    else if(pathname==='/api/settings/models'&&method==='POST'){
      fetches++;
      const form=request.postDataJSON();
      assert.equal(form.base_url,'https://draft.example/custom/v1');
      assert.equal(form.api_key,'TEST_ONLY_DRAFT_KEY');
      assert.equal(form.model,'');
      if(failFetch)return route.fulfill({status:401,contentType:'application/json',body:JSON.stringify({detail:'API Key 无效，当前输入已保留'})});
      body={models:['model-a','model-b'],base_url:form.base_url};
    } else if(pathname==='/api/settings'&&method==='PUT'){
      saves++;const form=request.postDataJSON();
      assert.equal(form.api_key,'TEST_ONLY_DRAFT_KEY');
      saved={...saved,...form,has_key:true};delete saved.api_key;body=saved;
    } else if(pathname==='/api/settings/test'){
      body={tool_calling:true,structured_output:true};
    } else if(pathname==='/api/mcp/reconnect'){body={connected:true};}
    else if(pathname==='/api/projects'){body=[{id:'test-project',title:'Isolated settings test'}];}
    else if(pathname==='/api/projects/test-project'){body={project:{id:'test-project',title:'Isolated settings test'},documents:[],jobs:[],knowledge_points:[],vacancies:[]};}
    else return route.fulfill({status:404,contentType:'application/json',body:'{"detail":"Not found"}'});
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
  });
  await page.goto('http://127.0.0.1:8787');
  await page.getByRole('button',{name:'API 设置',exact:true}).click();
  const url=page.getByRole('textbox',{name:'API Base URL',exact:true});
  const key=page.locator('input[type=password]');
  const model=page.getByRole('textbox',{name:'模型 ID',exact:true});
  await url.waitFor();assert.equal(await url.inputValue(),saved.base_url);
  const startNavigations=navigation.length;
  // Same-provider click must not restore its preset or clear a custom URL/key.
  await key.fill('TEST_ONLY_DRAFT_KEY');await url.fill('https://draft.example/custom/v1');
  assert.equal(await key.inputValue(),'TEST_ONLY_DRAFT_KEY');
  await model.fill('');await page.getByRole('button',{name:'DeepSeek',exact:true}).click();
  assert.equal(await url.inputValue(),'https://draft.example/custom/v1');
  assert.equal(await key.inputValue(),'TEST_ONLY_DRAFT_KEY');
  // Change provider and return: preserve each provider's draft.
  await page.getByRole('button',{name:'GPT',exact:true}).click();
  await page.getByRole('button',{name:'DeepSeek',exact:true}).click();
  assert.equal(await url.inputValue(),'https://draft.example/custom/v1');
  assert.equal(await key.inputValue(),'TEST_ONLY_DRAFT_KEY');
  // Navigate away and back: parent holds the draft, not a resetting effect.
  await page.getByRole('button',{name:'返回工作台',exact:true}).click();
  await page.getByRole('button',{name:'API 设置',exact:true}).click();
  assert.equal(await url.inputValue(),'https://draft.example/custom/v1');
  assert.equal(await key.inputValue(),'TEST_ONLY_DRAFT_KEY');
  await page.getByRole('button',{name:'获取模型',exact:true}).click();
  await page.getByRole('combobox',{name:'可用模型（2 个）',exact:true}).waitFor();
  assert.equal(saves,0);assert.equal(fetches,1);assert.equal(navigation.length,startNavigations);
  assert.equal(await model.inputValue(),'');assert.equal(await key.inputValue(),'TEST_ONLY_DRAFT_KEY');
  failFetch=true;
  await page.getByRole('button',{name:'获取模型',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'API Key 无效'}).waitFor();
  assert.equal(await url.inputValue(),'https://draft.example/custom/v1');
  assert.equal(await key.inputValue(),'TEST_ONLY_DRAFT_KEY');assert.equal(saves,0);
  await page.getByRole('combobox',{name:'可用模型（2 个）',exact:true}).selectOption('model-b');
  await page.getByRole('button',{name:'测试连接与能力',exact:true}).click();
  await page.getByText('模型已通过能力测试',{exact:true}).waitFor();
  assert.equal(saves,0);assert.equal(await key.inputValue(),'TEST_ONLY_DRAFT_KEY');
  await page.getByRole('button',{name:'保存配置',exact:true}).click();
  await page.getByText('配置与密钥已保存。密钥不回显，留空不会删除已保存的密钥。',{exact:true}).waitFor();
  assert.equal(saves,1);assert.equal(await key.inputValue(),'');
  assert.equal(await url.inputValue(),'https://draft.example/custom/v1');
  assert.equal(await model.inputValue(),'model-b');
  await page.reload();
  await url.waitFor();
  assert.equal(await url.inputValue(),'https://draft.example/custom/v1');
  assert.equal(await model.inputValue(),'model-b');
  assert.equal(await key.getAttribute('placeholder'),'密钥已保存，留空保持不变');
  assert.deepEqual(errors,[]);
  await page.screenshot({path:'data/settings-regression.png',fullPage:true});
  await browser.close();
  console.log('PASS: no-model discovery, no implicit save/navigation, provider and page draft retention, failure retention, read-only test, explicit save and reload with saved key indicator.');
})().catch(e=>{console.error(e);process.exit(1)});
