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

  // FR-70：无论上次停在哪一步，启动一律落第 1 步（index 0）—— 进度只体现在导航轨解锁
  check('FR-70 startup always lands on step 1 (index 0)',
    await page.evaluate(() => STATE.current_step) === 0);

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
  // FR-67：datalist → select。除了「有选项」，还必须验证**每个模型项真能选中**
  // —— 原 bug 正是「DOM 里 2 个 option，但下拉只显示 1 个」，只看 children.length 会漏。
  const mo = await page.evaluate(() => [...document.getElementById('cfgModelSel').options]
    .map(o => o.value).filter(v => v && v !== '__custom__'));
  check('fetch models fills model select (' + mo.length + ')', mo.length > 0);
  const mtext = await page.evaluate(() => [...document.getElementById('cfgModelSel').options]
    .map(o => o.textContent).filter(t => t && t.includes('__custom__') === false));
  check('model options carry visible text (not blank)', mtext.length > 0 && mtext.every(t => t.trim().length > 0));
  let selectable = true;
  for (const m of mo) {
    await page.selectOption('#cfgModelSel', m);
    await page.waitForTimeout(120);
    const cur = await page.evaluate(() => curModel());
    if (cur !== m) selectable = false;
  }
  check('every model in dropdown is really selectable', selectable);
  await page.selectOption('#cfgModelSel', '__custom__');
  await page.waitForTimeout(150);
  check('custom option reveals manual input', await page.evaluate(() =>
    !document.getElementById('cfgModel').classList.contains('hidden')));
  await page.selectOption('#cfgModelSel', mo[0]);
  await page.waitForTimeout(150);

  // FR-71：切换提供方必须清空上一家的模型列表 —— 选 Claude 不能还挂着本地 Ollama 模型
  await page.click('.prov[data-k="claude"]');
  await page.waitForTimeout(250);
  const fr71 = await page.evaluate(() => ({
    opts: [...document.getElementById('cfgModelSel').options].map(o => o.value),
    model: curModel(),
  }));
  check('FR-71 provider switch clears foreign model list',
    fr71.opts.length <= 2 && fr71.opts.every(v => v === '' || v === '__custom__'));
  check('FR-71 provider switch falls back to preset model (' + fr71.model + ')',
    fr71.model === 'claude-3-5-sonnet-latest');
  // 切回 ollama 并重拉列表（列表被 FR-71 清空了，后续步骤还要用）
  await page.click('.prov[data-k="ollama"]');
  await page.waitForTimeout(150);
  await page.click('#btnModels');
  await page.waitForTimeout(2500);
  const mo2 = await page.evaluate(() => [...document.getElementById('cfgModelSel').options]
    .map(o => o.value).filter(v => v && v !== '__custom__'));
  check('FR-71 re-fetch after switching back (' + mo2.length + ')', mo2.length > 0);
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
  // FR-73：冻结表头必须实底 —— 透明底会让滚动行从表头底下透出来（首行文字压列表项）
  const thBg = await page.evaluate(() =>
    getComputedStyle(document.querySelector('.tblwrap thead th')).backgroundColor);
  check('FR-73 sticky thead has opaque background (' + thBg + ')',
    thBg !== 'rgba(0, 0, 0, 0)' && thBg !== 'transparent');
  // FR-74：统计带压缩 —— 注释行整个不显示，把高度还给校对列表
  const mnDisp = await page.evaluate(() =>
    getComputedStyle(document.querySelector('#p4metrics .metric-n')).display);
  check('FR-74 step4 metrics note hidden (compact band)', mnDisp === 'none');
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
  // v0.5.1/0.5.2：FR-62/FR-63 修复 + FR-64 校验弹窗（版本断言用正则，升版不必改测试）
  // ===================================================================
  // 11. 齿轮菜单：点得开、6 项齐全、能真拉到数据（v0.5.0 事故：设置菜单点不开没内容）
  await page.evaluate(() => showPage(0));
  const gearHidden0 = await page.evaluate(() => getComputedStyle(document.getElementById('gearMenu')).display);
  check('gearMenu hidden initially', gearHidden0 === 'none');
  await page.click('#gearBtn');
  await page.waitForTimeout(200);
  check('gearMenu opens on click', await page.evaluate(() => getComputedStyle(document.getElementById('gearMenu')).display) !== 'none');
  const gearTxt = await page.textContent('#gearMenu');
  // 版本号曾显示成「v—」（打开菜单那一刻 STATE 还没载入完）——FR-62 修
  await page.waitForTimeout(300);
  const gearVer = (await page.textContent('#gearVer')).trim();
  // v0.5.2 起齿轮只留 4 项：「回到配置翻译服务」与「明暗模式」已删
  // （前者是导航不是设置；后者与标题栏 #themeBtn 功能重叠）
  for (const item of ['翻译提示词', '校验注入工具', '运行日志', '重置流程'])
    check(`gear menu has ${item}`, gearTxt.includes(item));
  for (const gone of ['回到配置翻译服务', '明暗模式'])
    check(`gear menu dropped ${gone}`, !gearTxt.includes(gone));
  check('themeBtn kept in titlebar', await page.locator('#themeBtn').count() === 1);
  check('gear version is a real semver (not v—): ' + gearVer, /^v\d+\.\d+\.\d+$/m.test(gearVer));
  // FR-66：同類占位符全库清扫 —— 界面不许再出现没自解释的破折号占位符
  const shownHtml = await page.evaluate(() => document.body.innerText);
  check('no bare dash placeholder on screen (' + 'v—' + ')', !shownHtml.includes('v—'));
  check('p4eta not a dash placeholder', !shownHtml.includes('预计剩余 ——'));
  const etaTxt = (await page.textContent('#p4eta')).trim();
  check('p4eta static text is readable: ' + etaTxt, etaTxt.includes('翻译开始后显示预计剩余时间'));
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
  check('log has version line', /G-POT 翻译器 v\d+\.\d+\.\d+/.test(logTxt));
  check('log has game dir line', logTxt.includes('游戏目录'));
  check('log has dictionary line', logTxt.includes('译文词典'));
  await page.click('#logModal button:has-text("关闭")');
  await page.waitForTimeout(200);
  check('logModal closes', await page.evaluate(() => getComputedStyle(document.getElementById('logModal')).display) === 'none');

  // 13. 「校验注入工具」开弹窗（FR-64：按引擎逐项核对，不是一句话结论）
  await page.click('#gearBtn');
  await page.click('#gearMenu button:has-text("校验注入工具")');
  await page.waitForTimeout(900);
  check('kitModal opens', await page.evaluate(() => getComputedStyle(document.getElementById('kitModal')).display) === 'flex');
  const kitHead = await page.textContent('#kitHead');
  const kitBody = await page.textContent('#kitBody');
  check('kitModal states engine or missing prereq', /Unity|RPG|未识别|还没/.test(kitHead));
  check('kitModal lists per-tool rows', /落点|判定文件|没有需要部署/.test(kitBody));
  check('kitModal shows no path slash mess', !kitBody.includes('//') && !kitBody.includes('\\\\'));
  await page.click('#kitModal button:has-text("关闭")');
  await page.waitForTimeout(200);
  check('kitModal closes', await page.evaluate(() => getComputedStyle(document.getElementById('kitModal')).display) === 'none');

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

  // 16. FR-69：选完游戏必须明确落第 2 步，不随 current_step 漂移 overshoot；
  //     部署/跳过必须明确落第 3 步。旧实现 selectGame 用 goNext(=current+1)，
  //     恢复到靠后步骤后回第 1 步重选游戏会越级被拦，第 2 步看着像锁死。
  await page.evaluate(async () => {
    await api('POST', '/api/reset', {});
    await loadState();
    STATE.current_step = 3;   // 模拟「恢复到靠后步骤」后用户回第 1 步重选游戏
    const gp = 'F:\\erogame\\Starmaker_Story\\Starmaker Story(1.8e\\Starmaker 1.8E';
    document.getElementById('gamePath').value = gp;
    await selectGame();       // 修复后走 goto(2)，不会去 nav(4) 越级
  });
  await page.waitForTimeout(600);
  const fr69a = await page.evaluate(() => ({
    cur: STATE.current_step,
    page: [...document.querySelectorAll('.page.active')].map(x => x.dataset.page)[0],
    sb: document.getElementById('sbMsg').innerText,
  }));
  check('FR-69 selectGame lands on step 2 (no overshoot)', fr69a.cur === 2 && fr69a.page === '2');
  check('FR-69 no "这一步还没解锁" left on step2', !fr69a.sb.includes('这一步还没解锁'));

  // 第 2 步识别引擎 → 跳过（不下载，安全）→ 必须落第 3 步
  await page.evaluate(() => { const b = document.getElementById('btnDetect'); if (b) b.click(); });
  await page.waitForTimeout(2200);
  await page.evaluate(() => {
    const bs = [...document.querySelectorAll('.page[data-page="2"] button')];
    const t = bs.find(x => x.textContent.includes('跳过'));
    if (t) t.click();
  });
  await page.waitForTimeout(1200);
  const fr69b = await page.evaluate(() => ({
    cur: STATE.current_step,
    page: [...document.querySelectorAll('.page.active')].map(x => x.dataset.page)[0],
  }));
  check('FR-69 skip lands on step 3', fr69b.cur === 3 && fr69b.page === '3');

  // FR-75：非当前引擎只给切换提示，不摆别家的指标/落点/白名单详情
  await page.evaluate(() => loadSink('rm'));
  await page.waitForTimeout(700);
  const fr75 = await page.evaluate(() => ({
    html: document.getElementById('sinkView').innerHTML,
    metrics: document.querySelectorAll('#sinkView .metric').length,
  }));
  check('FR-75 non-current engine shows switch prompt', fr75.html.includes('回到当前管线'));
  check('FR-75 non-current engine hides detail metrics', fr75.metrics === 0);
  await page.evaluate(() => loadSink('unity'));   // 还原到当前引擎视图
  await page.waitForTimeout(400);

  await page.screenshot({ path: 'I:/AIcoding/gpot-loc/_smoke_v056.png', fullPage: false });
  await browser.close();
  console.log(results.join('\n'));
  const fails = results.filter(r => r.startsWith('FAIL')).length;
  console.log(fails ? `RESULT: ${fails} FAILED` : 'RESULT: ALL PASS');
  process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
