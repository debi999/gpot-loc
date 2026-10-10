const { chromium } = require('playwright-core');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const results = [];
  const check = (name, ok) => results.push((ok ? 'PASS' : 'FAIL') + ' ' + name);

  const PORT = process.env.GPOT_PORT || '8731';
  await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'networkidle' });
  await page.evaluate(() => showPage(0));   // 流程状态可能停在别的步 → 强制回第 0 步
  await page.waitForTimeout(300);

  // 1. 三个弹窗初始全部隐藏（v0.4.6 回归 + 新增两个）
  for (const id of ['replModal', 'promptModal', 'fullModal']) {
    const d = await page.evaluate(id => getComputedStyle(document.getElementById(id)).display, id);
    check(`modal ${id} hidden on load`, d === 'none');
  }
  // 2. 第 0 步新控件存在
  for (const id of ['cfgSrc', 'cfgDst', 'cfgConc', 'cfgDelay', 'btnModels']) {
    check(`step0 ${id} exists`, await page.locator('#' + id).count() === 1);
  }
  // 注意：第 0 步内用 #btnPrompt 定位（齿轮菜单里也有「翻译提示词」，
// 用 has-text 会命中 2 个，Playwright 严格模式直接报错）
  check('step0 提示词 button', await page.locator('#btnPrompt').count() === 1);
  // 3. 提示词弹窗交互：打开 → 恢复默认有内容 → 关闭
  await page.click('#btnPrompt');
  check('promptModal opens', await page.evaluate(() => getComputedStyle(document.getElementById('promptModal')).display) === 'flex');
  await page.click('#promptModal button:has-text("恢复默认")');
  const pv = await page.inputValue('#promptTxt');
  check('prompt reset fills default', pv.length > 50);
  await page.click('#promptModal button:has-text("保存")');
  await page.waitForTimeout(400);
  check('prompt saved to config', await page.evaluate(() => (STATE.config.prompt || '').length > 50));
  // 4. 获取模型（本机 Ollama 在跑）
  await page.click('#btnModels');
  await page.waitForTimeout(3000);
  const mo = await page.evaluate(() => document.getElementById('modelList').children.length);
  check('fetch models fills datalist (' + mo + ')', mo > 0);
  // 5. 第 4 步：TXT 按钮 / 排序表头 / 勾选列
  await page.click('.step[data-i="0"]'); await page.waitForTimeout(200);
  // 直接调 nav 到第 4 步需要解锁——走 API 快速解锁再进
  await page.evaluate(async () => {
    await fetch('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: 'ollama', model: 'x', address: 'http://127.0.0.1:11434/v1' }) });
    await fetch('/api/game', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: 'F:\\erogame\\Starmaker_Story\\Starmaker Story(1.8e\\Starmaker 1.8E' }) });
    for (const s of [2, 3, 4]) await fetch('/api/nav', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ step: s }) }).catch(() => {});
  });
  await page.reload({ waitUntil: 'networkidle' });
  await page.evaluate(() => showPage(4));
  await page.waitForTimeout(600);
  check('TXT import button', await page.locator('button:has-text("导入 TXT")').count() === 1);
  check('checkbox column', await page.locator('#p4tbody input[type=checkbox]').count() > 0);
  // 6. 排序：点原文表头 → 第一行变化且箭头出现
  const firstBefore = await page.evaluate(() => document.querySelector('#p4tbody tr td:nth-child(4)').textContent);
  await page.click('th:has-text("原文")');
  await page.waitForTimeout(500);
  const firstAfter = await page.evaluate(() => document.querySelector('#p4tbody tr td:nth-child(4)').textContent);
  const mark = await page.textContent('#sm-original');
  check('sort click reorders + arrow (' + mark + ')', mark === '↑');
  check('sort changes first row', firstBefore !== firstAfter);
  // 7. 右键菜单：查看全文 + 删除条目
  await page.locator('#p4tbody tr[data-ei]').first().click({ button: 'right' });
  await page.waitForTimeout(200);
  const ctxTxt = await page.textContent('#ctxMenu');
  check('ctx has 查看全文', ctxTxt.includes('查看全文'));
  check('ctx has 删除条目', ctxTxt.includes('删除条目'));
  // 8. 查看全文弹窗
  await page.click('#ctxMenu button:has-text("查看全文")');
  await page.waitForTimeout(200);
  check('fullModal opens', await page.evaluate(() => getComputedStyle(document.getElementById('fullModal')).display) === 'flex');
  await page.click('#fullModal button:has-text("关闭")');
  // 9. 勾选 → 下拉显示计数
  await page.locator('#p4tbody input[type=checkbox]').first().check();
  const ddTxt = await page.textContent('#ddSelected');
  check('selected count in dropdown (' + ddTxt + ')', /（\d+）/.test(ddTxt));
  // 10. 截图存档
  await page.screenshot({ path: 'I:/AIcoding/gpot-loc/_smoke_m4.png', fullPage: false });

  // ===================================================================
  // v0.5.1：本轮 4 项修复（FR-62/FR-63）
  // ===================================================================
  // 11. 齿轮菜单：点得开、6 项齐全、能真拉到数据（v0.5.0 事故：设置菜单点不开没内容）
  await page.evaluate(() => showPage(0));
  const gearHidden0 = await page.evaluate(() => getComputedStyle(document.getElementById('gearMenu')).display);
  check('gearMenu hidden initially', gearHidden0 === 'none');
  await page.click('#gearBtn');
  await page.waitForTimeout(200);
  check('gearMenu opens on click', await page.evaluate(() => getComputedStyle(document.getElementById('gearMenu')).display) !== 'none');
  const gearTxt = await page.textContent('#gearMenu');
  for (const item of ['翻译提示词', '回到配置翻译服务', '校验注入工具', '运行日志', '明暗模式', '重置流程'])
    check(`gear menu has ${item}`, gearTxt.includes(item));
  check('gear menu shows version', /v0\.5\.1/.test(gearTxt));
  // 点别处应收起（避免遮挡操作）
  await page.mouse.click(400, 500);
  await page.waitForTimeout(200);
  check('gearMenu closes on outside click', await page.evaluate(() => getComputedStyle(document.getElementById('gearMenu')).display) === 'none');

  // 12. 「运行日志」弹窗真能拉到内容（v0.5.1 前该端点错放在 POST → GET 404）
  await page.click('#gearBtn');
  await page.click('#gearMenu button:has-text("运行日志")');
  await page.waitForTimeout(500);
  check('logModal opens', await page.evaluate(() => getComputedStyle(document.getElementById('logModal')).display) === 'flex');
  const logTxt = await page.textContent('#logTxt');
  check('log has version line', /G-POT 翻译器 v0\.5\.1/.test(logTxt));
  check('log has game dir line', logTxt.includes('游戏目录'));
  check('log has dictionary line', logTxt.includes('译文词典'));
  await page.click('#logModal button:has-text("关闭")');
  await page.waitForTimeout(200);
  check('logModal closes', await page.evaluate(() => getComputedStyle(document.getElementById('logModal')).display) === 'none');

  // 13. 「校验注入工具」也走 GET（同样修过方法错位）
  await page.click('#gearBtn');
  await page.click('#gearMenu button:has-text("校验注入工具")');
  await page.waitForTimeout(600);
  const sbAfterKit = await page.textContent('#sbMsg');
  check('kit check reports a verdict', sbAfterKit.length > 0 && !sbAfterKit.includes('404'));

  // 14. 跳步被拦时状态栏说真实原因（FR-63 事实闸）
  // 必须打**后端**（页面里改 STATE 是假象，后端 prereq_ok 仍看真目录/引擎）
  await page.evaluate(async () => {
    await api('POST', '/api/reset', {});
    await loadState();
  });
  await page.waitForTimeout(400);
  await page.evaluate(() => showPage(0));
  await page.evaluate(async () => { await goto(3); });
  await page.waitForTimeout(300);
  const sbNav = await page.textContent('#sbMsg');
  check('blocked nav states a reason', /还没解锁|先完成/.test(sbNav));
  check('blocked nav stays on step 0', await page.evaluate(() => STATE.current_step) !== 3);

  // 15. 提取未执行时如实报红，不渲染一排 0（FR-63 早退）
  await page.evaluate(async () => { await runExtract(); });
  await page.waitForTimeout(500);
  const p3 = await page.textContent('#p3result');
  check('extract refuses without game dir', p3.includes('提取未执行'));
  check('extract refusal names the cause', p3.includes('第 1 步'));

  await page.screenshot({ path: 'I:/AIcoding/gpot-loc/_smoke_v051.png', fullPage: false });
  await browser.close();
  console.log(results.join('\n'));
  const fails = results.filter(r => r.startsWith('FAIL')).length;
  console.log(fails ? `RESULT: ${fails} FAILED` : 'RESULT: ALL PASS');
  process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
