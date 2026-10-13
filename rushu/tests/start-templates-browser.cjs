// Real Chromium integration QA. Start the local Rushu service first.
// RUSHU_QA_URL supports an isolated test server; artifacts go to RUSHU_QA_DIR.
// No real provider keys or external model requests are used.
const {chromium}=require('playwright');
const fs=require('node:fs/promises');
const path=require('node:path');
const os=require('node:os');
const assert=require('node:assert/strict');
const base=process.env.RUSHU_QA_URL||'http://127.0.0.1:18812/#token=start-template-local-qa';
const out=process.env.RUSHU_QA_DIR||path.join(os.tmpdir(),'rushu-start-template-qa');
(async()=>{
 await fs.mkdir(out,{recursive:true});
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 const context=await browser.newContext({acceptDownloads:true,viewport:{width:1280,height:960}});
 const page=await context.newPage(),errors=[],requests=[],dialogs=[],results=[];
 page.on('pageerror',e=>errors.push(String(e)));
 page.on('request',r=>requests.push({url:r.url(),method:r.method()}));
 // Never accept a destructive dialog. Unexpected dialogs cause the test to fail.
 page.on('dialog',async d=>{dialogs.push(d.message());await d.dismiss();});
 const save=async name=>{const pending=page.waitForEvent('download');await page.locator('#save-book').click();const p=path.join(out,'startqa-'+name+'.rushu.json');await(await pending).saveAs(p);return JSON.parse(await fs.readFile(p,'utf8'));};
 const controlsReady=()=>page.waitForFunction(()=>!document.querySelector('#run-all').disabled);
 const select=async id=>{await page.locator('#new-book').click();await page.locator('#template-dialog').waitFor({state:'visible'});await page.locator(`#template-dialog [data-template="${id}"]`).click();await page.locator('#template-dialog').waitFor({state:'hidden'});await controlsReady();};
 const noAutomaticActions=()=>assert(!requests.some(r=>/\/(execute|generate)(?:$|\?)/.test(r.url)),JSON.stringify(requests));
 try {
  await page.goto(base);await page.locator('#start-templates [data-template=basics]').waitFor();
  assert(await page.locator('#start-page').isVisible());assert(await page.locator('#book-workspace').isHidden());assert(await page.locator('#save-book').isDisabled());
  assert.equal(await page.locator('#start-templates [data-template]').count(),6);
  assert(!requests.some(r=>r.method==='POST'));noAutomaticActions();
  await page.screenshot({path:path.join(out,'startqa-start-page.png'),fullPage:true});results.push('start page has six choices and creates no kernel/book automatically');
  await page.locator('#start-templates [data-template=basics]').focus();await page.keyboard.press('Enter');await controlsReady();
  assert(await page.locator('.cell.code textarea').first().evaluate(e=>e===document.activeElement));
  const first=await save('basics-first');assert(first.cells.every(c=>c.execution_count===null&&c.outputs.length===0));noAutomaticActions();
  await page.locator('.cell.code textarea').first().fill("显 '保留原书中文内容'.");
  const oldIds=await page.locator('.cell').evaluateAll(es=>es.map(e=>e.dataset.cellId));
  await page.locator('#new-book').click();await page.locator('#close-templates').click();
  assert.equal(await page.locator('.cell.code textarea').first().inputValue(),"显 '保留原书中文内容'.");assert.deepEqual(await page.locator('.cell').evaluateAll(es=>es.map(e=>e.dataset.cellId)),oldIds);
  assert(await page.locator('#new-book').evaluate(e=>e===document.activeElement));
  await page.locator('#new-book').click();await page.keyboard.press('Escape');assert(await page.locator('#template-dialog').isHidden());
  assert.equal(await page.locator('.cell.code textarea').first().inputValue(),"显 '保留原书中文内容'.");
  await page.locator('#new-book').click();await page.locator('#template-dialog [data-template=text]').click();
  assert.equal(dialogs.length,1);assert(dialogs[0].includes('尚未保存'));assert(await page.locator('#template-dialog').isVisible());
  assert.equal(await page.locator('.cell.code textarea').first().inputValue(),"显 '保留原书中文内容'.");await page.keyboard.press('Escape');await save('basics-edited');results.push('close, Escape, and rejecting unsaved replacement preserve current content and IDs');
  for(const id of ['text','contest','graphics','generation','blank','basics']) {
   await select(id);const saved=await save(id);assert(saved.cells.every(c=>c.execution_count===null&&c.outputs.length===0));
   assert(!saved.cells.some(c=>first.cells.some(old=>old.id===c.id)));noAutomaticActions();
   if(id==='blank'){assert.equal(saved.cells.length,1);assert.equal(saved.cells[0].source,'');}
   if(id==='generation'){assert(saved.cells.some(c=>c.generation));assert.equal(saved.cells.find(c=>c.generation).source,'');}
  }
  results.push('all templates instantiate without execution or model calls; blank has one empty cell; repeated templates have unique IDs');
  // Browser-native composition via CDP, with real textarea and keyboard handlers.
  await select('blank');const input=page.locator('.cell.code textarea').first();await input.focus();
  const cdp=await context.newCDPSession(page);await cdp.send('Input.imeSetComposition',{text:'中文输入',selectionStart:4,selectionEnd:4});await page.keyboard.press('Shift+Enter');
  assert((await input.inputValue()).startsWith('中文输入'));noAutomaticActions();await input.fill('');await cdp.send('Input.imeSetComposition',{text:'中文输入',selectionStart:4,selectionEnd:4});await cdp.send('Input.insertText',{text:'中文输入'});assert.equal(await input.inputValue(),'中文输入');
  await page.keyboard.press('Escape');await page.keyboard.press('Tab');assert(!(await input.evaluate(e=>e===document.activeElement)));await save('ime');results.push('Chromium IME composition does not execute on Shift+Enter; Chinese text commits; Escape then Tab exits editor');
  await select('basics');await page.locator('#run-all').click();await controlsReady();assert((await page.locator('.cell-output').allTextContents()).join('\n').includes('你好，如书'));assert((await page.locator('.cell-output').allTextContents()).join('\n').includes('今天开始写如言'));await save('basics-run');
  await select('text');await page.locator('#run-all').click();await controlsReady();assert((await page.locator('.cell-output').allTextContents()).join('\n').includes('小明喜欢梨'));await save('text-run');
  await select('contest');await page.locator('#run-all').click();await controlsReady();assert((await page.locator('.cell-output').allTextContents()).join('\n').includes('8'));await save('contest-run');results.push('basic, text, contest examples execute with expected output');
  await select('graphics');await page.locator('.cell.code .cell-head .run-cell').click();await controlsReady();const canvas=page.locator('.cell-output canvas');await canvas.waitFor();
  const pixel=async(x,y)=>canvas.evaluate((c,{x,y})=>[...c.getContext('2d').getImageData(x,y,1,1).data],{x,y});assert.deepEqual(await pixel(180,100),[70,119,255,255]);
  await canvas.click({position:{x:70,y:60}});await page.waitForFunction(()=>{const c=document.querySelector('.cell-output canvas');const p=c.getContext('2d').getImageData(70,60,1,1).data;return p[0]===70&&p[1]===119;});
  await page.keyboard.press('r');await page.waitForFunction(()=>{const c=document.querySelector('.cell-output canvas');const p=c.getContext('2d').getImageData(70,60,1,1).data;return p[0]===244&&p[1]===246;});
  const graphicBook=await save('graphics-run');assert(graphicBook.cells.some(c=>c.outputs.some(o=>o.type==='graphics')));await page.screenshot({path:path.join(out,'startqa-graphics.png'),fullPage:true});results.push('graphics template renders correct pixels, mouse callback moves circle, keyboard r clears, and save retains graphics');
  const oldSessionPath=new URL(requests.filter(r=>r.url.includes('/events?')).at(-1).url).pathname.replace(/\/events$/,'');
  await page.locator('#new-book').click();await page.locator('#dialog-blank').click();await controlsReady();
  assert(requests.some(r=>r.method==='DELETE'&&new URL(r.url).pathname===oldSessionPath));
  const mixed=page.locator('.cell.code');await mixed.locator('textarea').fill("显 '图前'. 观 取 外言 '如:观'. 图 取 观 其 画布 160 120. 图 其 背景 '#ff0000'. 循 40 次 显 '图后中文😀'. 环");await mixed.locator('.cell-head .run-cell').click();await controlsReady();
  assert((await mixed.locator('.output-controls').innerText()).includes('预览前 8 行'));
  const mixedPixel=()=>mixed.locator('canvas').evaluate(c=>[...c.getContext('2d').getImageData(150,110,1,1).data]);assert.deepEqual(await mixedPixel(),[255,0,0,255]);
  await mixed.getByRole('button',{name:'展开或收起已保留的原文'}).click();assert.deepEqual(await mixedPixel(),[255,0,0,255]);await mixed.getByRole('button',{name:'展开或收起已保留的原文'}).click();assert.deepEqual(await mixedPixel(),[255,0,0,255]);
  const mixedSaved=await save('mixed-run');assert.equal(mixedSaved.cells[0].outputs.filter(o=>o.text).map(o=>o.text).join(''),'图前\n'+'图后中文😀\n'.repeat(40));
  await page.locator('#file-picker').setInputFiles(path.join(out,'startqa-mixed-run.rushu.json'));await page.getByText('历史输出 · 未在本会话执行').waitFor();await controlsReady();assert.deepEqual(await mixedPixel(),[255,0,0,255]);assert((await mixed.locator('.output-controls').innerText()).includes('预览前 8 行'));
  const reopened=await save('mixed-reopened');assert.deepEqual(reopened.cells,mixedSaved.cells);results.push('changing templates closes old canvas session; mixed long text folds/expands without losing canvas; saved and reopened content, IDs, text and graphics match exactly');
  const oldTitle=await page.locator('#book-title').inputValue(),oldContent=await page.locator('.cell.code textarea').inputValue(),oldCellId=await page.locator('.cell').getAttribute('data-cell-id');
  await page.route('**/api/sessions',route=>route.request().method()==='POST'?route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'QA simulated session creation failure'})}):route.continue());
  await select('text');assert.equal(await page.locator('#book-title').inputValue(),oldTitle);assert.equal(await page.locator('.cell.code textarea').inputValue(),oldContent);assert.equal(await page.locator('.cell').getAttribute('data-cell-id'),oldCellId);assert((await page.locator('#notice').innerText()).includes('原书内容仍保留'));await page.unroute('**/api/sessions');results.push('failed new-session request preserves existing saved book and gives retry notice');
  const offlineContext=await browser.newContext({acceptDownloads:true,viewport:{width:390,height:844}}),offline=await offlineContext.newPage(),offlineDownloads=[],offlineRequests=[];offline.on('download',d=>offlineDownloads.push(d));offline.on('request',r=>offlineRequests.push(r.url()));await offline.goto(new URL(base).origin);await offline.locator('#start-blank').waitFor();await offline.keyboard.press('Control+s');
  await offline.locator('#start-blank').click();await offline.locator('.cell.code textarea').fill("显 '离线中文'.");assert.equal(offlineDownloads.length,0);assert(await offline.locator('#run-all').isDisabled());
  const offlineDownload=offline.waitForEvent('download');await offline.locator('#save-book').click();const offlinePath=path.join(out,'startqa-offline.rushu.json');await(await offlineDownload).saveAs(offlinePath);assert.equal(JSON.parse(await fs.readFile(offlinePath,'utf8')).cells[0].source,"显 '离线中文'.");assert(!offlineRequests.some(url=>url.includes('/api/')));assert(await offline.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));await offlineContext.close();results.push('without token, start Ctrl+S produces no phantom book; direct blank shortcut edits and saves locally without API calls');
  await page.setViewportSize({width:390,height:844});await page.locator('#new-book').click();assert(await page.locator('#template-dialog [data-template=blank]').isVisible());
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));await page.screenshot({path:path.join(out,'startqa-mobile.png'),fullPage:true});await page.keyboard.press('Escape');results.push('390px template picker has no horizontal document overflow');
  assert.equal(dialogs.length,1);assert.deepEqual(errors,[]);assert(!requests.some(r=>!r.url.startsWith(new URL(base).origin)&&!r.url.startsWith('data:')));
  console.log(JSON.stringify({status:'PASS',browser:'real Chromium',artifactDirectory:out,results,pageErrors:errors,unexpectedDialogs:dialogs.slice(1),requestCount:requests.length},null,2));
 }catch(e){console.error('FAIL',e);console.error('DOM',await page.locator('body').innerText());await page.screenshot({path:path.join(out,'startqa-failure.png'),fullPage:true});throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
