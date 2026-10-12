// Run with a local test server and Playwright/Chromium. Never calls a real model.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1280,height:960}}),errors=[];
 let pending=[],calls=0;
 page.on('pageerror',error=>errors.push(String(error)));
 page.on('dialog',async dialog=>{
  if(dialog.message().startsWith('发送给 animation-mock.example？')||dialog.message().startsWith('生成仍在等待，继续会丢弃返回结果'))await dialog.accept();else await dialog.dismiss();
 });
 await page.route('**/api/generation/config',route=>route.fulfill({json:{configured:true,provider_host:'animation-mock.example'}}));
 await page.route('**/api/generate',route=>{calls++;pending.push(route);});
 const ready=()=>page.waitForFunction(()=>!document.querySelector('#run-all').disabled);
 const start=async()=>{
  await page.getByRole('button',{name:'给意图补上结语并发送本格意图与当前源码，生成新版本',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.generation-activity:not([hidden])'));
  const deadline=Date.now()+30000;while(!pending.length){assert(Date.now()<deadline,'mock generation request did not arrive');await page.waitForTimeout(10);}
 };
 const complete=async(ok=true)=>{const route=pending.shift();await route.fulfill({status:ok?200:500,json:ok?{source:'显 42.\n',valid:true}:{error:'mock failure'}}).catch(()=>{});await ready();};
 try{
  await page.goto(process.env.RUSHU_QA_URL||'http://127.0.0.1:18812/#token=start-template-local-qa');
  await page.locator('#start-templates [data-template=generation]').click();await ready();
  await start();
  const before=await page.evaluate(()=>{
   const status=document.querySelector('.generation-status'),text=status.querySelector('[role=status]'),indicator=status.querySelector('.generation-activity'),svg=indicator.querySelector('svg'),cell=status.closest('.cell');
   window.animationSnapshot={status,text,indicator,svg,cell,changes:0};
   const observer=new MutationObserver(records=>window.animationSnapshot.changes+=records.length);observer.observe(status,{subtree:true,childList:true,characterData:true});window.animationSnapshot.observer=observer;
   return {text:text.textContent,rect:JSON.stringify(status.getBoundingClientRect()),svgRect:JSON.stringify(svg.getBoundingClientRect()),transform:getComputedStyle(svg).transform,width:indicator.getBoundingClientRect().width,height:indicator.getBoundingClientRect().height};
  });
  assert.equal(before.width,16);assert.equal(before.height,16);
  await page.waitForTimeout(2250);
  const after=await page.evaluate(()=>{
   const s=window.animationSnapshot;
   return {same:s.status===document.querySelector('.generation-status')&&s.cell===s.status.closest('.cell')&&s.text===s.status.querySelector('[role=status]')&&s.svg===s.status.querySelector('svg'),text:s.text.textContent,rect:JSON.stringify(s.status.getBoundingClientRect()),transform:getComputedStyle(s.svg).transform,changes:s.changes,hidden:s.indicator.getAttribute('aria-hidden')};
  });
  assert(after.same);assert.equal(after.text,before.text);assert.equal(after.rect,before.rect);assert.equal(after.changes,0);assert.equal(after.hidden,'true');assert.notEqual(after.transform,before.transform);
  const out=process.env.RUSHU_QA_DIR||path.join(os.tmpdir(),'rushu-animation-qa');await fs.mkdir(out,{recursive:true});
  await page.screenshot({path:path.join(out,'generation-animation-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  const mobileRect=await page.locator('.generation-status').evaluate(e=>JSON.stringify(e.getBoundingClientRect()));
  await page.waitForTimeout(1250);
  assert.equal(await page.locator('.generation-status').evaluate(e=>JSON.stringify(e.getBoundingClientRect())),mobileRect);
  assert.equal(await page.evaluate(()=>window.animationSnapshot.changes),0);
  await page.screenshot({path:path.join(out,'generation-animation-mobile.png'),fullPage:true});
  await page.setViewportSize({width:1280,height:960});
  await page.emulateMedia({reducedMotion:'reduce'});assert.equal(await page.locator('.generation-activity svg').evaluate(e=>getComputedStyle(e).animationName),'none');
  await page.emulateMedia({reducedMotion:'no-preference'});await complete();assert(await page.locator('.generation-activity').isHidden());
  await start();await complete(false);assert(await page.locator('.generation-activity').isHidden());
  await start();await page.getByRole('button',{name:'丢弃尚未返回的生成结果，保留当前编辑',exact:true}).click();assert(await page.locator('.generation-activity').isHidden());await complete();
  await start();await page.locator('#new-book').click();await page.locator('#dialog-blank').click();await ready();assert.equal(await page.locator('.generation-activity').count(),0);await complete();
  assert.equal(calls,4);assert.deepEqual(errors,[]);
  console.log('PASS: fixed 16px SVG; changing transform with zero status DOM mutations or layout shift; reduced motion; success/error/cancel/repeat/book-switch cleanup; mock provider only.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
