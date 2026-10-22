// Explicit real-browser QA; invoked by tools/qa_native_kernel.py.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const directory = process.env.RUSHU_QA_DIR;
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH,
    headless: true, args: process.platform === 'linux' ? ['--no-sandbox'] : []});
  const context = await browser.newContext({acceptDownloads: true, viewport: {width: 1280, height: 960}});
  const page = await context.newPage(), errors = [], requests = [], passed = [];
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', request => requests.push(new URL(request.url()).pathname));
  page.on('dialog', async dialog => { errors.push('unexpected dialog: '+dialog.message()); await dialog.dismiss(); });
  const ready = () => page.waitForFunction(() => !document.querySelector('#run-all').disabled);
  const text = async cell => (await cell.locator('.cell-output pre.stdout').allTextContents()).join('');
  const run = async (cell, source, expected) => {
    await cell.locator('textarea').fill(source);
    await cell.locator('.cell-head .run-cell').click();
    await ready();
    if (expected !== undefined) assert.equal(await text(cell), expected);
  };
  try {
    await page.goto(process.env.RUSHU_QA_URL);
    await page.locator('#start-blank').click();
    await ready();
    const first = page.locator('.cell.code').first();
    await run(first, "值 取 40. 显 '你好😀'.", '你好😀\n');
    await page.locator('#add-code').click();
    const second = page.locator('.cell.code').nth(1);
    await run(second, '值+2.', '42\n');
    passed.push('native cells share state through the real browser');

    await run(second, '若 假 则 值 取 99. 另若 真 则 值 取 42. 另若 1/0 则 显 98. 然. 显 值.', '42\n');
    passed.push('upstream 另若 syntax executes lazily in the native kernel');

    await run(second, '显 1/0.');
    assert((await second.locator('.cell-output pre.error').innerText()).includes('除数不能为零'));
    await run(second, '显 值+3.', '45\n');
    passed.push('runtime error preserves the session and navigable diagnostics');

    await run(first, '算 造: 值 取 0. 算 加: 值 取 值+1. 得 值. 法. 得 算 加. 法. 计 取 造.', '');
    await run(second, '显 计(). 显 计().', '1\n2\n');
    passed.push('closures retain mutable lexical bindings across cells');

    await second.locator('textarea').fill("显 读 提示:'输入😀：'.");
    await second.locator('.cell-head .run-cell').click();
    await second.locator('.input-form input').fill('原生回声');
    await second.locator('.input-form button[type=submit]').click();
    await ready();
    assert.equal(await text(second), '输入😀：原生回声\n');
    passed.push('Unicode prompt and input use the existing browser flow');

    await run(second, `观 取 外言 '如:观'. 图 取 观 其 画布 160 100. 次数 取 [0].
像 取 图 其 缓存 20 20 (作 层: 层 其 填色 '#ff0000'. 层 其 描边 空. 层 其 矩形 0 0 20 20. 为).
图 其 背景 '#ffffff'. 图 其 贴图 像 10 10.
图 其 鼠标按下 (作 横 纵 键: 次数[0] 取 次数[0]+1. 图 其 背景 '#ffffff'. 图 其 贴图 像 横 纵. 显 '点'+(次数[0] 为 句). 为).
图 其 按键 (作 键: 图 其 背景 '#ffffff'. 图 其 贴图 像 40 40. 显 '键：'+键. 为).`, '');
    const canvas = second.locator('.scene-output canvas');
    await canvas.waitFor();
    const pixel = (x, y) => canvas.evaluate((element, point) =>
      [...element.getContext('2d').getImageData(...point, 1, 1).data], [x, y]);
    assert.deepEqual(await pixel(15, 15), [255, 0, 0, 255]);
    await canvas.click({position: {x: 30, y: 35}});
    await page.waitForFunction(() => [...document.querySelectorAll('.cell.code')][1].textContent.includes('点1'));
    await canvas.press('k');
    await page.waitForFunction(() => [...document.querySelectorAll('.cell.code')][1].textContent.includes('键：k'));
    assert.equal(await text(second), '点1\n键：k\n');
    assert.deepEqual(await pixel(45, 45), [255, 0, 0, 255]);
    await page.screenshot({path: path.join(directory, 'native-graphics-live.png'), fullPage: true});
    passed.push('native cached drawing renders pixels and handles real pointer and keyboard input');
    await second.getByRole('button', {name: '停止画布', exact: true}).click();
    await second.getByText('画布已停止', {exact: true}).waitFor();
    passed.push('closing a native canvas completes without restarting the notebook');

    const graphicsDownload = page.waitForEvent('download');
    await page.locator('#save-book').click();
    const graphicsSaved = path.join(directory, 'native-graphics.rushu.json');
    await (await graphicsDownload).saveAs(graphicsSaved);
    const graphicsBook = JSON.parse(await fs.readFile(graphicsSaved, 'utf8'));
    const savedScene = graphicsBook.cells[1].outputs.find(output => output.type === 'graphics');
    assert(savedScene && savedScene.scene.resources?.length === 1);
    const beforeReplay = requests.filter(value => value.endsWith('/graphics')).length;
    const beforeReopen = requests.filter(value => value.endsWith('/execute')).length;
    await page.locator('#file-picker').setInputFiles(graphicsSaved);
    await second.getByText('历史画布 · 重新运行后可交互', {exact: true}).waitFor();
    assert.deepEqual(await pixel(45, 45), [255, 0, 0, 255]);
    await canvas.click({position: {x: 50, y: 50}});
    await page.waitForTimeout(250);
    assert.equal(requests.filter(value => value.endsWith('/graphics')).length, beforeReplay);
    assert.equal(requests.filter(value => value.endsWith('/execute')).length, beforeReopen);
    await page.screenshot({path: path.join(directory, 'native-graphics-history.png'), fullPage: true});
    passed.push('saved native cache recipes replay as static history without callbacks or execution');

    await second.locator('textarea').fill('循 环');
    await second.locator('.cell-head .run-cell').click();
    await page.waitForFunction(() => !document.querySelector('#stop').disabled);
    await page.locator('#stop').click();
    await ready();
    await run(second, '显 值.');
    assert((await second.locator('.cell-output pre.error').innerText()).includes('未定义名称'));
    await run(second, "显 '重启后可用'.", '重启后可用\n');
    passed.push('stop terminates an infinite native loop and resets state');

    await page.locator('#book-title').fill('原生解释核验');
    const download = page.waitForEvent('download');
    await page.locator('#save-book').click();
    const saved = path.join(directory, 'native-book.rushu.json');
    await (await download).saveAs(saved);
    const data = JSON.parse(await fs.readFile(saved, 'utf8'));
    assert.equal(data.cells.length, 2);
    const executions = requests.filter(value => value.endsWith('/execute')).length;
    await page.locator('#file-picker').setInputFiles(saved);
    await page.getByText('历史输出 · 未在本会话执行').first().waitFor();
    await ready();
    assert.equal(requests.filter(value => value.endsWith('/execute')).length, executions);
    passed.push('save and reopen retain history without automatic execution');

    await page.screenshot({path: path.join(directory, 'native-desktop.png'), fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    await page.screenshot({path: path.join(directory, 'native-mobile.png'), fullPage: true});
    assert.deepEqual(errors, []);
    assert(!requests.some(value => value.endsWith('/generate')));
    const report = {browser: browser.version(), platform: process.platform, passed, errors,
      execution_requests: executions, automatic_execution_on_reopen: false};
    await fs.writeFile(path.join(directory, 'report.json'), JSON.stringify(report, null, 2)+'\n');
    console.log(JSON.stringify(report));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
