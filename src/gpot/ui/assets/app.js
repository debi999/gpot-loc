/* ===========================================================================
 * G-POT Loc 前端 —— 纯静态，只通过 fetch() 与本地 API 对话。
 * 本文件不含任何业务规则：导航锁、解锁链、引擎识别、落盘分流全在后端。
 * ========================================================================= */
'use strict';

const API = '';                 // 同源，留空即可
let STATE = null;               // 最近一次 /api/state
let SEL_PROV = 'ollama';        // 当前选中的提供方
let TRANS_JOB = null;           // 进行中的翻译任务 id
let DEMO = false;               // 离线预览模式：API 不可达（如 file:// 双击打开）时自动启用

/* ---------------- 底层 ---------------- */
/* 离线预览模式的固定应答（纯展示数据；业务规则仍只在后端 core/ 中）。
   注：原先还有 _demoComplete/_DEMO_NEXT 两个符号，但零调用方（codegraph 孤儿），
   且与后端 pipeline._NEXT 双份会漂移 —— v0.5.1 删除。 */
let _demoJobPct = 0;
function _demoState() {
  return {
    steps: [
      { n: 0, title: '配置翻译服务', sub: '一次性准备' },
      { n: 1, title: '选择游戏', sub: '一次性准备' },
      { n: 2, title: '识别引擎', sub: '一次性准备' },
      { n: 3, title: '提取文本', sub: '每轮迭代' },
      { n: 4, title: '翻译校对', sub: '每轮迭代' },
      { n: 5, title: '保存并应用', sub: '每轮迭代' },
      { n: 6, title: '启动验证', sub: '每轮迭代' }
    ],
    current_step: 0, max_step: 0,
    game: null, engine: null, config: null,
    translate: { total: 14679, done: 14204, failed: 12 },
    sink: { backup: false }
  };
}
function _demoApi(method, path, body) {
  if (path === '/api/providers')
    return Promise.resolve({ providers: [
      { key: 'ollama', name: '本地 Ollama', desc: '离线 · 本机模型' },
      { key: 'openai', name: 'OpenAI 兼容', desc: '任意兼容端点' },
      { key: 'deepl', name: 'DeepL API', desc: '云端高质量' }
    ]});
  if (path === '/api/state') { if (!STATE) STATE = _demoState(); return Promise.resolve(STATE); }
  if (path === '/api/nav') {
    const to = body && body.step;
    if (to <= STATE.max_step) { STATE.current_step = to; return Promise.resolve(STATE); }
    return Promise.resolve({ error: 'locked' });
  }
  if (path === '/api/reset') { STATE = _demoState(); _demoJobPct = 0; return Promise.resolve({}); }
  if (path === '/api/config')
    return Promise.resolve({ connected: true, message: '演示模式 · 未真正连通', config: {} });
  if (path === '/api/game')
    return Promise.resolve({ name: 'Starmaker Story（演示）', path: 'F:\\erogame\\...', existing: 14679 });
  if (path === '/api/detect')
    return Promise.resolve({ key: 'unity', name: 'Unity (Mono)', confidence: 0.79,
      verdict: '可自动翻译', evidence: ['BepInEx 5.4.23', 'XUnity.AutoTranslator', 'Assembly-CSharp.dll'],
      sink_desc: 'XUnity 词典保存即生效' });
  if (path === '/api/deploy')
    return Promise.resolve({ tools: [{ name: 'XUnity.AutoTranslator', version: '5.4.3',
      size: '1.2 MB', verified: true, status: '已部署' }] });
  if (path === '/api/extract')
    return Promise.resolve({ added: 312, existing: 14679, guarded: 24, total: 14991 });
  if (path === '/api/translate/start') { _demoJobPct = 0; return Promise.resolve({ job_id: 'demo' }); }
  if (path.startsWith('/api/jobs/')) {
    _demoJobPct = Math.min(100, _demoJobPct + 17);
    return Promise.resolve({ running: _demoJobPct < 100, progress: _demoJobPct, done: Math.round(14679 * _demoJobPct / 100) });
  }
  // 注：原先紧跟其后还有一行 `startsWith('/api/jobs/') && method==='POST'`，永远不可达
  // （上面已 return）—— v0.5.1 删除，别再补回来。
  if (path.startsWith('/api/sink')) {
    const ek = (path.match(/engine=([a-z]+)/) || [])[1] || 'unity';
    if (ek === 'rm') return Promise.resolve({ kind: 'rewrite', title: '保存并写入工作副本', warn: 'RPG Maker：保存只是工作副本，还需「应用到游戏」',
      metrics: [{ l: '在表条目', v: '14,679', n: '全部' }, { l: '待写入', v: '787', n: '本轮新增' }, { l: '备份', v: '3', n: '历史代数' }],
      files: [{ path: 'www/data/Map001.json', note: '事件文本', badge: 'warn', action: '回写' }],
      whitelist: ['notes', 'description'], blacklist: 'characterName / faceName / switches', can_restore: true });
    if (ek === 'manual') return Promise.resolve({ kind: 'none', title: '保存（无自动方案）', warn: '该引擎没有可靠的自动注入方案',
      metrics: [{ l: '在表条目', v: '14,679', n: '全部' }],
      reasons: [{ t: '无公开注入工具', s: '需要手动处理', badge: 'danger' }] });
    return Promise.resolve({ kind: 'runtime', title: '保存并写入词典', warn: 'Unity/XUnity：保存即生效，重启游戏可见',
      metrics: [{ l: '在表条目', v: '14,679', n: '全部' }, { l: '本轮新增', v: '312', n: '待写入' }, { l: '词典大小', v: '1.4 MB', n: 'Translation.txt' }],
      files: [{ path: 'BepInEx/Translation/Translation.txt', note: 'XUnity 词典', badge: 'ok', action: '写入' }],
      can_restore: false });
  }
  if (path.startsWith('/api/sink/apply')) return Promise.resolve({ files: [{}, {}, {}] });
  if (path === '/api/verify')
    return Promise.resolve({ hint: '启动游戏前确认注入工具已就位', checks: [
      { t: 'BepInEx 目录完整', s: 'BepInEx/core 存在' }, { t: 'XUnity 词典就位', s: 'Translation.txt · 1.4 MB' }] });
  if (path === '/api/launch')
    return Promise.resolve({ ok: true, exe: '演示模式 · 不真启动' });
  if (path === '/api/open-dir')
    return Promise.resolve({ ok: true, dir: '演示模式 · 不真打开' });
  if (path === '/api/recent')
    return Promise.resolve({ recent: [{ path: 'F:\\erogame\\demo', name: 'Starmaker Story（演示）', entries: 14679, configured: true }] });
  if (path === '/api/export-csv')
    return Promise.resolve({ ok: true, path: '演示模式 · 不真导出', rows: 14679 });
  if (path === '/api/import-csv')
    return Promise.resolve({ canceled: true });
  if (path === '/api/replace')
    return Promise.resolve({ ok: true, replaced: 0 });
  if (path === '/api/dedup')
    return Promise.resolve({ ok: true, removed: 0, total: 14679 });
  return Promise.resolve({});
}
async function api(method, path, body) {
  if (DEMO) return _demoApi(method, path, body);
  const opt = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opt.body = JSON.stringify(body);
  try {
    const r = await fetch(API + path, opt);
    return r.json().catch(() => ({}));
  } catch (e) {
    // API 不可达（file:// 直接打开等）→ 永久切到离线预览模式
    DEMO = true;
    return _demoApi(method, path, body);
  }
}
function sb(msg) { document.getElementById('sbMsg').textContent = msg; }
let _sbIdleTimer = null;
function setSbProg(pct) {
  /* FR-47：任务进行时进度亮起，空闲 2.6s 后淡出 */
  const live = document.getElementById('sbLive');
  if (!live) return;
  live.classList.remove('off');
  document.getElementById('sbBar').style.width = pct + '%';
  document.getElementById('sbPct').textContent = Math.round(pct) + '%';
  clearTimeout(_sbIdleTimer);
  _sbIdleTimer = setTimeout(() => live.classList.add('off'), 2600);
}

/* ---------------- 明暗模式切换（默认暗色，localStorage 记忆；纯呈现层） ---------------- */
function applyThemeIcon() {
  const btn = document.querySelector('#themeBtn use');
  if (!btn) return;
  const light = document.documentElement.getAttribute('data-theme') === 'light';
  btn.setAttribute('href', light ? '#i-moon' : '#i-sun');
}
function toggleTheme() {
  const r = document.documentElement;
  const t = r.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  if (t === 'dark') r.removeAttribute('data-theme');
  else r.setAttribute('data-theme', 'light');
  try { localStorage.setItem('gpot-theme', t); } catch (e) {}
  applyThemeIcon();
  sb(t === 'light' ? '已切换到明亮模式（白粉基调）' : '已切换到暗色模式');
}
(function () {
  try {
    if (localStorage.getItem('gpot-theme') === 'light') document.documentElement.setAttribute('data-theme', 'light');
  } catch (e) {}
  applyThemeIcon();
})();

/* ---------------- 状态加载与渲染 ---------------- */
async function loadState() {
  STATE = await api('GET', '/api/state');
  renderRail();
  renderGameCard();
  renderStep4Metrics();
  _applyConfigToInputs();   // FR-53/55/58: 配置记忆值 → 第 0 步输入框
  if (STATE.current_step === 5) loadSink(STATE.engine ? STATE.engine.key : 'unity');
  if (curPage() === 6) loadVerify();
  showPage(STATE.current_step);
}

function renderRail() {
  const steps = STATE.steps;
  const cur = STATE.current_step, max = STATE.max_step;
  let html = '';
  for (const s of steps) {
    const i = s.n;
    const done = i < cur;
    const current = i === cur;
    const locked = i > max;
    const cls = done ? 'done' : (current ? 'current' : '');
    const mark = done
      ? '<svg width="13" height="13"><use href="#i-check"/></svg>'
      : (i + 1);
    // FR-46（单主按钮原则）& NFR-12（文案密度铁律）—— 每页导语≤1行、卡片副标题≤1行（UI 呈现层约束）
    html += `<button class="step ${cls}" data-i="${i}" ${locked ? 'disabled' : ''} onclick="goto(${i})">
      <span class="step-mark">${mark}</span>
      <span><span class="step-title">${s.title}</span>
      <span class="step-sub">${s.sub}</span></span></button>`;
  }
  document.getElementById('steps').innerHTML = html;
}

function renderGameCard() {
  const g = STATE.game;
  if (g && g.name) {
    document.getElementById('gcName').textContent = g.name;
    document.getElementById('gcMeta').textContent = g.path || '';
  }
}

function renderStep4Metrics() {
  const t = STATE.translate;
  const todo = Math.max(0, t.total - t.done - t.failed);
  const pct = t.total ? Math.round(t.done / t.total * 100) : 0;   // 0 条时防 NaN%
  const box = document.getElementById('p4metrics');
  box.innerHTML = `
    <div class="metric"><div class="metric-l">总条目</div><div class="metric-v">${(t.total || 0).toLocaleString()}</div><div class="metric-n">含已有译文</div></div>
    <div class="metric"><div class="metric-l">已翻译</div><div class="metric-v" id="m-done">${(t.done || 0).toLocaleString()}</div><div class="metric-n">${pct}%</div></div>
    <div class="metric"><div class="metric-l">未翻译</div><div class="metric-v" id="m-todo">${todo.toLocaleString()}</div><div class="metric-n">本次目标</div></div>
    <div class="metric"><div class="metric-l">失败</div><div class="metric-v" id="m-fail">${t.failed || 0}</div><div class="metric-n">多为超长/超时</div></div>`;
  const bar = document.getElementById('p4bar');
  bar.firstElementChild.style.width = pct + '%';
  document.getElementById('p4txt').textContent = pct + '%';
}

function showPage(i) {
  document.querySelectorAll('.page').forEach(p => {
    p.classList.toggle('active', +p.dataset.page === i);
  });
  document.querySelector('.content').scrollTop = 0;
  if (i === 3) renderStep3Base();   // 提取页先亮出「已有提取结果」基线
  if (i === 4) {                    // 校对页每次进入都刷新指标 + 真实条目
    renderStep4Metrics();
    if (!DEMO) { loadRows(); checkExternal(); }
  }
}
/* FR-60: 词典文件被外部（游戏/编辑器）改写过 → 第 4 步顶提示条 */
async function checkExternal() {
  const el = document.getElementById('p4ext');
  if (!el || DEMO) return;
  const s = await api('GET', '/api/state');
  el.classList.toggle('hidden', !(s && s.external_changed));
}
/* FR-60: 外部改动后重新载入词典（走 /api/game 同路径重载，不重跑提取） */
async function reloadRows() {
  const p = (STATE.game && STATE.game.path) || '';
  if (!p) return;
  const g = await api('POST', '/api/game', { path: p });
  STATE.game = g;
  STATE.translate.total = g.existing || 0;
  await api('GET', '/api/state').then(s => {
    if (s && s.translate) STATE.translate = { ...STATE.translate, ...s.translate };
  });
  renderStep4Metrics(); loadRows();
  document.getElementById('p4ext').classList.add('hidden');
  sb('已重新载入词典文件 · ' + (g.existing || 0).toLocaleString() + ' 条');
}

/* 第 3 步基线：进入即显示已有提取成果（FR-42 语义：提取优先认已有文本） */
function renderStep3Base() {
  const el = document.getElementById('p3base');
  if (!el) return;
  const t = STATE.translate || {};
  if (t.total) {
    el.innerHTML = `已在表 <b>${(t.total || 0).toLocaleString()}</b> 条（已译 ${(t.done || 0).toLocaleString()}）· 上次提取结果仍在，点「开始提取」只补增量，不覆盖`;
    el.classList.remove('hidden');
  } else {
    el.classList.add('hidden');
  }
}
function curPage() { return STATE.current_step; }

/* ---------------- 导航 ---------------- */
/* FR-63: 两道闸（数字 max_step + 前置事实）——被拦时如实说原因，不写「已解锁」 */
async function goto(i) {
  const r = await api('POST', '/api/nav', { step: i });
  if (r && r.max_step !== undefined && !r.blocked_reason) {
    STATE = r; renderRail(); showPage(i);
    if (i === 5) await loadSink(curEngineKey());
    if (i === 6) await loadVerify();
  } else sb((r && r.blocked_reason) || '这一步还没解锁');
}
async function goNext() {
  const next = STATE.current_step + 1;
  const r = await api('POST', '/api/nav', { step: next });
  if (r && r.max_step !== undefined && !r.blocked_reason) {
    STATE = r; renderRail(); showPage(next);
    if (next === 5) await loadSink(curEngineKey());
    if (next === 6) await loadVerify();
  } else sb((r && r.blocked_reason) || '先完成本步，下一步才解锁');
}
async function resetAll() {
  await api('POST', '/api/reset', {});
  await loadState();
  sb('已回到第 0 步 · 译文词典未删除');
}

/* ---------------- Step 0：配置 ---------------- */
let PROVS = [];                  // 真实提供方目录（含默认地址/模型/needs_key）
async function loadProviders() {
  const r = await api('GET', '/api/providers');
  PROVS = r.providers || [];
  const grid = document.getElementById('provGrid');
  grid.innerHTML = PROVS.map(p => `
    <button class="prov ${p.key === SEL_PROV ? 'on' : ''}" data-k="${p.key}" onclick="pickProv(this)">
      <div class="prov-tick"><svg width="10" height="10"><use href="#i-check"/></svg></div>
      <div class="prov-n">${p.name}</div>
      <div class="prov-d">${p.desc}</div>
    </button>`).join('');
  pickDefaults();
}
function _applyConfigToInputs() {
  // FR-53/55/58: 把 STATE.config 记忆值灌回第 0 步输入框（语言/并发/间隔/提示词）
  const c = STATE.config || {};
  const set = (id, v) => { const el = document.getElementById(id); if (el && v !== undefined && v !== '') el.value = v; };
  set('cfgSrc', c.src); set('cfgDst', c.dst);
  set('cfgConc', c.concurrency); set('cfgDelay', c.delay);
}
function pickDefaults() {
  // 选中提供方的默认地址/模型回填输入框；需要密钥时展开 Key 行
  const p = PROVS.find(x => x.key === SEL_PROV) || {};
  const addr = document.getElementById('cfgAddr');
  const model = document.getElementById('cfgModel');
  if (p.address) addr.value = p.address;
  if (p.model) model.value = p.model;
  document.getElementById('cfgSecretRow').hidden = !p.needs_key;
  document.getElementById('cfgAppidField').hidden = !p.needs_appid;
}
function pickProv(el) {
  document.querySelectorAll('.prov').forEach(x => x.classList.remove('on'));
  el.classList.add('on');
  SEL_PROV = el.dataset.k;
  pickDefaults();
}
function _cfgBody() {
  return {
    provider: SEL_PROV,
    model: document.getElementById('cfgModel').value,
    address: document.getElementById('cfgAddr').value,
    key: document.getElementById('cfgKey').value.trim(),
    appid: document.getElementById('cfgSecret').value.split('/')[0].trim(),
    secret: document.getElementById('cfgSecret').value.split('/')[1]?.trim() || '',
    // FR-55: 语言方向 / FR-58: 并发间隔 / FR-53: 提示词（弹窗编辑，存 STATE.config）
    src: document.getElementById('cfgSrc').value,
    dst: document.getElementById('cfgDst').value,
    concurrency: document.getElementById('cfgConc').value,
    delay: document.getElementById('cfgDelay').value,
    prompt: (STATE.config && STATE.config.prompt) || '',
  };
}
/* FR-54: 独立获取模型列表（不必先跑连接测试；后端带 Ollama /api/tags 兜底） */
async function fetchModels() {
  const btn = document.getElementById('btnModels');
  btn.disabled = true; btn.textContent = '获取中…';
  const r = await api('GET', '/api/models');
  btn.disabled = false; btn.textContent = '获取模型';
  if (r && r.ok && r.models && r.models.length) {
    document.getElementById('modelList').innerHTML =
      r.models.map(m => `<option value="${esc(m)}">`).join('');
    const model = document.getElementById('cfgModel');
    if (!model.value.trim() || !r.models.includes(model.value.trim())) {
      model.value = r.models[0];
      sb('已选中模型 ' + r.models[0]);
    } else {
      sb(r.message);
    }
  } else sb((r && r.message) || '未获取到模型列表');
}
async function saveConfig() {
  const r = await api('POST', '/api/config', _cfgBody());
  STATE.config = r.config;
  renderCfgStatus(r);
  if (r.connected) {
    // FR-59: 本地 Ollama 族连通后自动同步游戏内实时翻译（老版 save_settings 行为）
    if (r.injected_synced) sb('翻译服务已连通 · 游戏内实时翻译已同步使用模型 ' + r.config.model);
    else sb('翻译服务已连通');
    goNext();
  }
}
async function testConn() {
  const r = await api('POST', '/api/config', _cfgBody());
  renderCfgStatus(r);
}
function renderCfgStatus(r) {
  // FR-38:「保存并继续」在完成连接测试（成功）前保持禁用，悬停提示原因
  const save = document.getElementById('btnSaveCfg');
  if (save) {
    save.disabled = !r.connected;
    if (r.connected) save.removeAttribute('title');
  }
  // 探测到的模型列表 → 下拉（datalist）：可点选也可手输；当前值无效时自动选第一个
  if (r.models && r.models.length) {
    document.getElementById('modelList').innerHTML =
      r.models.map(m => `<option value="${esc(m)}">`).join('');
    const model = document.getElementById('cfgModel');
    if (!model.value.trim() || !r.models.includes(model.value.trim())) {
      model.value = r.models[0];
      sb('已选中模型 ' + r.models[0] + ' · 可在模型框下拉更换');
    }
  }
  const box = document.getElementById('cfgStatus');
  if (r.connected) {
    box.innerHTML = `<div class="infobar ib-ok"><svg class="ib-ico" width="17" height="17"><use href="#i-check"/></svg>
      <div><strong>连接正常</strong> · ${r.message}</div></div>`;
  } else {
    box.innerHTML = `<div class="infobar ib-warn"><svg class="ib-ico" width="17" height="17"><use href="#i-warn"/></svg>
      <div><strong>尚未连通</strong> · ${r.message}</div></div>`;
  }
}

/* ---------------- Step 1：游戏目录 ---------------- */
/* FR-39: 最近使用列表（游戏名 + 路径 + 已积累条数 + 已配置徽章） */
async function loadRecent() {
  const el = document.getElementById('recentBox');
  if (!el || DEMO) return;
  const r = await api('GET', '/api/recent');
  const list = (r && r.recent) || [];
  if (!list.length) { el.innerHTML = ''; return; }
  el.innerHTML = '<div class="subtle" style="margin-bottom:6px">最近使用</div>'
    + list.map(x => `
    <div class="rowitem" style="cursor:pointer" onclick="selectRecent('${esc(x.path).replace(/'/g, '&#39;')}')">
      <div class="ri-main"><div class="ri-t">${esc(x.name)}</div><div class="ri-s mono">${esc(x.path)}</div></div>
      <div class="ri-side">${x.configured
        ? `<span class="badge b-ok">已配置 · ${(x.entries || 0).toLocaleString()} 条</span>`
        : '<span class="badge b-muted">未配置</span>'}</div>
    </div>`).join('');
}
async function selectRecent(path) {
  document.getElementById('gamePath').value = path;
  await selectGame();
}
async function selectGame() {
  const path = document.getElementById('gamePath').value;
  const g = await api('POST', '/api/game', { path });
  STATE.game = g;
  renderGameCard();
  const info = document.getElementById('gameInfo');
  info.innerHTML = `<div class="infobar ib-info"><svg class="ib-ico" width="17" height="17"><use href="#i-info"/></svg>
    <div>已有 <b>${g.existing.toLocaleString()}</b> 条译文 · 继续只做增量，不覆盖</div></div>`
    + (g.relocated ? `<div class="infobar ib-warn" style="margin-top:8px"><svg class="ib-ico" width="17" height="17"><use href="#i-warn"/></svg>
    <div>所选目录不是游戏根，已自动定位到：<span class="mono">${esc(g.relocated)}</span></div></div>` : '');
  sb('已选择 ' + g.name + ' · 已有译文 ' + g.existing.toLocaleString() + ' 条');
  goNext();
}
async function pickFolder() {
  // FR-52: 第 1 步「浏览」——后端弹 Windows 现代版文件夹选择对话框（/api/pick-folder）
  if (DEMO) { sb('离线演示模式没有目录选择器 · 请直接粘贴路径'); return; }
  sb('正在打开文件夹选择器…');
  const r = await api('GET', '/api/pick-folder');
  if (r && r.path) {
    document.getElementById('gamePath').value = r.path;
    await selectGame();          // 选中即确认，少点一次
  } else if (r && r.canceled) {
    sb('已取消选择');
  } else {
    sb((r && r.message) || '无法打开选择器 · 请直接粘贴路径');
  }
}

/* ---------------- Step 2：识别引擎 ---------------- */
async function detectEngine() {
  const btn = document.getElementById('btnDetect');
  btn.disabled = true; btn.textContent = '识别中…';
  const eng = await api('POST', '/api/detect');
  STATE.engine = eng;
  STATE.kit = eng.kit || { deployed: false, tools: [] };   // FR-41: 工具清单随识别返回
  const ev = (eng.evidence || []).map(e => `<span class="chip"><span class="chip-mono">${e}</span></span>`).join('');
  document.getElementById('engineResult').innerHTML = `
    <div class="card">
      <div class="card-h">识别结果</div>
      <div class="btn-row spread" style="align-items:flex-start">
        <div>
          <div style="font-size:22px;font-weight:600">${eng.name}</div>
          <div class="subtle" style="margin-top:4px">置信度 ${Math.round(eng.confidence*100)}% · 由硬证据判定</div>
        </div>
        <span class="badge b-ok" style="font-size:12px;padding:4px 11px">${eng.verdict}</span>
      </div>
      <div style="margin-top:14px">${ev}</div>
    </div>
    <div class="card">
      <div class="card-h">这条管线会怎么跑</div>
      <div class="pipe">
        <div class="pipe-step"><div class="ps-t">文本从哪来</div><div class="ps-v">资源字节流提取</div></div>
        <div class="pipe-arrow">→</div>
        <div class="pipe-step"><div class="ps-t">译文写到哪</div><div class="ps-v">词典 txt（BepInEx）</div></div>
        <div class="pipe-arrow">→</div>
        <div class="pipe-step"><div class="ps-t">怎么才生效</div><div class="ps-v">${eng.sink_desc}</div></div>
      </div>
    </div>
    <div id="kitBox"></div>
      <div class="btn-row spread">
        <button class="btn btn-accent btn-lg" id="btnDeploy" onclick="deployKit()">下载并部署</button>
        <button class="btn btn-ghost" onclick="skipKit()">跳过，我手动装</button>
      </div>`;
  /* 主按钮移交（简报硬伤 2）：识别后底部「识别引擎」撤下，主按钮归部署区 */
  const detectRow = document.getElementById('detectRow');
  if (detectRow) detectRow.hidden = true;
  /* FR-41: 主按钮文案随状态变化 —— 无清单隐藏按钮；有清单显示「下载并部署（约 N MB）」 */
  const tools = (STATE.kit && STATE.kit.tools) || [];
  const dbtn = document.getElementById('btnDeploy');
  if (tools.length) {
    const total = tools.reduce((a, t) => a + (parseFloat(t.size) || 0), 0);
    dbtn.textContent = '下载并部署' + (total ? `（约 ${total.toFixed(1)} MB）` : '');
  } else {
    dbtn.hidden = true;
    document.getElementById('kitBox').innerHTML = `
      <div class="infobar ib-warn"><svg class="ib-ico" width="17" height="17"><use href="#i-warn"/></svg>
        <div>该引擎暂无可靠工具包清单 —— 请点「跳过，我手动装」，或用第 5 步给出的替代方案。</div></div>`;
  }
  sb('识别为 ' + eng.name);
}
async function deployKit() {
  const btn = document.getElementById('btnDeploy');
  btn.disabled = true; btn.textContent = '部署中…';
  const kit = await api('POST', '/api/deploy');
  STATE.kit = kit;   // FR-41: 记录部署态（重新校验文案用）
  const rows = (kit.tools || []).map(t => `
    <tr><td>${t.name}</td><td class="mono">${t.version}</td><td class="mono">${t.size}</td>
    <td>${t.verified ? '<span class="badge b-ok">已验证</span>' : '<span class="badge b-warn">仅查过</span>'}</td>
    <td><span class="badge b-ok">${t.status}</span></td></tr>`).join('');
  document.getElementById('kitBox').innerHTML = `
    <div class="card">
      <div class="card-h">需要部署的工具 <span class="badge b-muted" style="margin-left:6px">一次性</span></div>
      <div class="tblwrap"><table>
        <thead><tr><th>工具</th><th style="width:110px">版本</th><th style="width:80px">大小</th><th style="width:96px">校验</th><th style="width:88px">状态</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="5" class="subtle">该引擎暂无可靠工具包</td></tr>'}</tbody>
      </table></div>
    </div>`;
  btn.textContent = '重新校验';   // FR-41: 部署过 → 文案变「重新校验」
  btn.disabled = false;
  sb('注入工具已就位');
  goNext();
}
function skipKit() {   // FR-41: 「跳过，我手动装」→ 第 5 步顶部常驻提示
  STATE.kit = STATE.kit || {};
  STATE.kit.skipped = true;
  goNext();
}

/* ---------------- Step 3：提取 ---------------- */
async function runExtract() {
  const btn = document.getElementById('btnExtract');
  btn.disabled = true; btn.textContent = '扫描中…';
  document.getElementById('p3prog').classList.remove('hidden');
  // FR-42: 扫描选项 + 护栏开关接真实后端（重建=replace，仅标签=deep，护栏可关）
  const mode = (document.querySelector('input[name=mode]:checked') || {}).value || 'merge';
  const body = {
    mode: mode === 'replace' ? 'replace' : 'merge',
    deep: mode === 'labels',
    guard_frag: document.getElementById('gFrag').checked,
    guard_poll: document.getElementById('gPoll').checked,
  };
  const r = await api('POST', '/api/extract', body);
  document.getElementById('p3result').classList.remove('hidden');
  // FR-63: 没游戏目录/引擎时后端会 ok:false 早退——如实报红，别渲染一排 0
  // （v0.5.0 事故：目录没选却显示「提取完成 · 新增 0 条」+ 空表）
  if (r && r.ok === false) {
    document.getElementById('p3prog').classList.add('hidden');
    document.getElementById('p3result').innerHTML =
      `<div class="metric"><div class="metric-l">提取未执行</div>` +
      `<div class="metric-v" style="color:#e06c6c">${r.message || '前置条件不满足'}</div>` +
      `<div class="metric-n">${r.error === 'no_game' ? '回第 1 步选对游戏目录，再回第 2 步识别引擎' : '按提示补齐前置步骤'}</div></div>`;
    btn.textContent = '开始提取'; btn.disabled = false;
    sb(r.message || '提取未执行');
    return;
  }
  document.getElementById('p3result').innerHTML = `
    <div class="metric"><div class="metric-l">在表总数</div><div class="metric-v">${r.total.toLocaleString()}</div><div class="metric-n">全部条目（含已有 ${(r.translated || 0).toLocaleString()} 条译文）</div></div>
    <div class="metric"><div class="metric-l">本轮新增</div><div class="metric-v">${r.added.toLocaleString()}</div><div class="metric-n">新提取到的原文</div></div>
    <div class="metric"><div class="metric-l">已存在</div><div class="metric-v">${r.existing.toLocaleString()}</div><div class="metric-n">跳过，不覆盖原译文</div></div>
    <div class="metric"><div class="metric-l">护栏拦截</div><div class="metric-v">${r.guarded.toLocaleString()}</div><div class="metric-n">疑似碎片/污染</div></div>`;
  // 提取结果灌回全局状态：第 4 步指标和表格要靠它显示
  STATE.translate.total = r.total || 0;
  STATE.translate.done = r.translated || 0;
  btn.textContent = '重新提取'; btn.disabled = false;
  document.getElementById('btnNext3').disabled = false;
  sb(!r.added && r.total
    ? `未发现新文本 · 在表 ${r.total.toLocaleString()} 条（已译 ${(r.translated || 0).toLocaleString()}），直接下一步即可`
    : '提取完成 · 新增 ' + r.added + ' 条');
  goNext();
}

/* ---------------- Step 4：翻译 ---------------- */
const ROWS = [
  ['Are you sure you want to save the game?','确定要保存游戏进度吗？','ok'],
  ['I never thought I would see this place again.','我从没想过还能再回到这个地方。','ok'],
  ['The audition starts in ten minutes.','试镜十分钟后开始。','ok'],
  ['Thanks for waiting. Let us begin.','让大家久等了，我们开始吧。','ok'],
  ['You have unlocked a new outfit.','解锁了新服装。','ok'],
  ['Her voice echoed through the empty hall.','她的声音在空荡的大厅里回响。','ok'],
  ['Not bad. But you can do better.','还不错，不过你还能做得更好。','warn'],
  ['[System] Insufficient funds.','[系统] 资金不足。','ok'],
  ['Stage 3 - Clear!','第 3 关 —— 通关！','ok'],
  ['Do you really think you have what it takes?','你真的觉得自己够格吗？','todo'],
  ['I will be waiting at the usual place.','老地方等你。','ok'],
  ['Fame does not come cheap, you know.','要知道，成名的代价可不低。','warn'],
  ['Let me think about it for a moment...','让我再想想……','ok'],
  ['The producer wants to see you right now.','制作人现在就要见你。','todo'],
  ['Congratulations! You ranked first this week!','恭喜！本周排名第一！','ok'],
  ['Hmph. Typical.','哼，果然是这样。','ok'],
  ['Save completed successfully.','保存成功。','ok'],
  ['Are you sure? This cannot be undone.','确定吗？这一步无法撤销。','todo'],
  ['Maybe next time then.','那么下次吧。','warn'],
  ['I have never been this nervous before.','我从没这么紧张过。','fail']
];
const STATMAP = {
  ok:  '<span class="badge b-ok">✓ 已翻译</span>',
  warn:'<span class="badge b-warn">△ 英文残留</span>',
  todo:'<span class="badge b-warn">○ 未翻译</span>',
  fail:'<span class="badge b-danger">✕ 失败</span>'
};
function fillTable() {
  if (DEMO) { _fillTableRows(ROWS); return; }
  loadRows();
}
function _fillTableRows(rows) {
  const tb = document.getElementById('p4tbody');
  tb.innerHTML = rows.map(r => {
    const dst = (r[2] === 'todo' || r[2] === 'fail')
      ? '<span style="color:#9A8AA8">（未翻译）</span>' : r[1];
    const ei = r[3] ?? '';
    // FR-61: 行首勾选框（离线演示无条目序号 → 不渲染）
    const ck = ei === '' ? '' :
      `<input type="checkbox" data-i="${ei}" ${SEL_ROWS.has(+ei) ? 'checked' : ''} onclick="rowSel(event,this)">`;
    return `<tr data-ei="${ei}" data-t="${esc(r[1])}"><td class="c-num" style="width:30px">${ck}</td><td class="c-num"></td><td class="c-stat">${STATMAP[r[2]] || ''}</td><td>${esc(r[0])}</td><td>${dst === r[1] ? esc(r[1]) : dst}</td></tr>`;
  }).join('');
  // 序号跟随全表位置（分页第 2 页从 51 起算），而不是每页都从 1 开始
  tb.querySelectorAll('tr .c-num:nth-child(2)').forEach((td, k) => {
    td.textContent = rows[k][3] === '' || rows[k][3] === undefined
      ? k + 1 : rows[k][3] + 1;
  });
  tb.dataset.filled = '1';
  _updateSelCount();
}
/* FR-61: 勾选行状态（跨页保留；删重/导入等会改序号的操作后清空） */
const SEL_ROWS = new Set();
function rowSel(ev, ck) {
  ev.stopPropagation();
  const i = +ck.dataset.i;
  if (ck.checked) SEL_ROWS.add(i); else SEL_ROWS.delete(i);
  _updateSelCount();
}
function toggleAllRows(ck) {
  document.querySelectorAll('#p4tbody input[type=checkbox][data-i]').forEach(c => {
    c.checked = ck.checked;
    if (ck.checked) SEL_ROWS.add(+c.dataset.i); else SEL_ROWS.delete(+c.dataset.i);
  });
  _updateSelCount();
}
function _updateSelCount() {
  const dd = document.getElementById('ddSelected');
  if (dd) dd.textContent = SEL_ROWS.size ? `翻译勾选行（${SEL_ROWS.size}）` : '翻译勾选行';
}
function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/* ---------------- 第 4 步表格：真实分页 / 搜索 / 双击编辑 ---------------- */
const P4 = { page: 1, size: 50, matched: 0 };   // 分页状态（matched=筛选后总命中）
function p4Pages() { return Math.max(1, Math.ceil(P4.matched / P4.size)); }
function p4Go(p) {
  P4.page = Math.min(Math.max(1, p), p4Pages());
  loadRows();
}
function p4Size(v) {
  P4.size = Math.max(1, +v || 50);
  P4.page = 1;
  loadRows();
}
function onRowsFilter() { P4.page = 1; if (!DEMO) loadRows(); }

/* FR-57: 点表头列排序（original/translation/status，再点一次反向；空值恒沉底） */
const P4SORT = { col: '', rev: false };
function sortBy(col) {
  if (P4SORT.col === col) P4SORT.rev = !P4SORT.rev;
  else { P4SORT.col = col; P4SORT.rev = false; }
  document.querySelectorAll('.sortmark').forEach(s => s.textContent = '');
  const mk = document.getElementById('sm-' + col);
  if (mk) mk.textContent = P4SORT.rev ? '↓' : '↑';
  P4.page = 1;
  if (!DEMO) loadRows();
}

async function loadRows() {
  // 第 4 步表格：分页 + 搜索 + 状态筛选（/api/rows）
  const qEl = document.getElementById('p4q');
  const stEl = document.getElementById('p4filter');
  const q = (qEl && qEl.value || '').trim();
  const st = (stEl && stEl.value) || 'all';
  const r = await api('GET', '/api/rows?limit=' + P4.size
    + '&offset=' + (P4.page - 1) * P4.size
    + '&status=' + st + '&q=' + encodeURIComponent(q)
    + (P4SORT.col ? '&sort=' + P4SORT.col + '&rev=' + (P4SORT.rev ? 1 : 0) : ''));
  P4.matched = r.matched || 0;
  if ((P4.page - 1) * P4.size >= P4.matched && P4.matched > 0) {
    P4.page = p4Pages();          // 翻过头了（筛选后变少）→ 收回最后一页
    return loadRows();
  }
  const rows = (r.rows || []).map(x => [x.o, x.t, x.s, x.i]);
  if (!rows.length) rows.push(['（还没有条目）', '先在第 3 步提取文本', 'todo', '']);
  _fillTableRows(rows);
  const tb = document.getElementById('p4tbody');
  tb.dataset.total = r.total || rows.length;
  const cnt = document.getElementById('p4count');
  if (cnt) cnt.textContent = (q || st !== 'all')
    ? `命中 ${(P4.matched).toLocaleString()} / 共 ${(r.total || 0).toLocaleString()} 条`
    : `共 ${(r.total || 0).toLocaleString()} 条`;
  renderPager();
}
function renderPager() {
  const el = document.getElementById('p4pager');
  if (!el) return;
  const pages = p4Pages(), cur = Math.min(P4.page, pages);
  const b = (label, page, dis, strong) =>
    `<button class="btn${strong ? ' btn-accent' : ''}" style="min-width:34px;justify-content:center;padding:4px 8px"
      ${dis ? 'disabled' : ''} onclick="p4Go(${page})">${label}</button>`;
  el.innerHTML = `
    ${b('«', 1, cur <= 1)}${b('‹', cur - 1, cur <= 1)}
    <span class="subtle nowrap">${cur.toLocaleString()} / ${pages.toLocaleString()}</span>
    ${b('›', cur + 1, cur >= pages)}${b('»', pages, cur >= pages)}`;
}

/* 双击任意行 → 译文单元格变输入框，Enter/失焦保存（/api/row/edit 立即落盘） */
async function _commitRowEdit(inp, ei, cur) {
  const v = inp.value;
  const r = await api('POST', '/api/row/edit', { i: ei, translation: v });
  if (r && r.ok) {
    if (v !== cur) sb('已保存该条译文');
  } else {
    sb((r && r.message) || '保存失败');
  }
  loadRows();
}
function onRowDblClick(ev) {
  if (DEMO) { sb('离线演示不支持编辑 · 启动后端后可双击改译文'); return; }
  const tr = ev.target.closest && ev.target.closest('tr');
  if (!tr || tr.dataset.ei === undefined || tr.dataset.ei === '') return;
  const ei = +tr.dataset.ei;
  const cell = tr.cells[4];   // 第 5 列 = 译文（FR-61 加勾选列后顺延）
  if (!cell || cell.querySelector('input')) return;
  const cur = tr.dataset.t || '';
  cell.innerHTML = `<input class="inp" style="width:100%" value="${cur}">`;
  const inp = cell.querySelector('input');
  inp.focus(); inp.select();
  let done = false;
  const finish = save => {
    if (done) return;
    done = true;
    if (save) _commitRowEdit(inp, ei, cur);
    else loadRows();
  };
  inp.addEventListener('keydown', e => {
    if (e.key === 'Enter') finish(true);
    else if (e.key === 'Escape') finish(false);
  });
  inp.addEventListener('blur', () => finish(true));
}
/* FR-43: 翻译范围下拉（仅未翻译/当前筛选/全部/仅重试失败） */
function ddToggle(ev) {
  ev.stopPropagation();
  document.getElementById('ddScope').classList.toggle('hidden');
}
let _t0 = 0, _tBase = 0, _tBaseAt = 0;   // ETA 采样：起始 done 与时间点
async function runTranslate(scope) {
  document.getElementById('ddScope').classList.add('hidden');
  const btn = document.getElementById('btnTrans');
  btn.disabled = true;
  document.getElementById('btnStop').disabled = false;
  _t0 = Date.now(); _tBase = 0; _tBaseAt = _t0;
  // FR-43: 「当前筛选」要带上第 4 步工具栏的搜索词与状态筛选（后端同一套规则选条目）
  const body = { scope };
  if (scope === 'filtered') {
    body.q = (document.getElementById('p4q') || {}).value || '';
    body.status = (document.getElementById('p4filter') || {}).value || 'all';
  }
  if (scope === 'selected') {           // FR-61: 只翻勾选行
    if (!SEL_ROWS.size) { sb('先在表格里勾选要翻译的行'); btn.disabled = false; return; }
    body.indices = [...SEL_ROWS];
  }
  const r = await api('POST', '/api/translate/start', body);
  if (r.done_all) {           // 没有需要翻译的条目 → 直接完成
    document.getElementById('p4bar').classList.add('ok');
    document.getElementById('btnTrans').textContent = '已全部翻译';
    document.getElementById('btnNext4').disabled = false;
    sb('没有需要翻译的条目');
    return;
  }
  TRANS_JOB = r.job_id;
  pollJob();
}
function _etaText(job) {
  // FR-43: 预计剩余时间 —— 按本任务实测速度算，不给空白承诺
  const el = document.getElementById('p4eta');
  if (!el) return;
  const now = Date.now();
  if (job.done > _tBase) { _tBase = job.done; _tBaseAt = now; }
  const speed = job.done / Math.max(0.5, (now - _t0) / 1000);   // 条/秒（全程均值）
  const remain = Math.max(0, job.total - job.done);
  const eta = speed > 0 ? Math.ceil(remain / speed) : null;
  el.textContent = (eta !== null
    ? `预计剩余 ${eta >= 60 ? Math.ceil(eta / 60) + ' 分钟' : eta + ' 秒'}`
    : '计算中…') + ' · 已译文不会被覆盖';
}
async function pollJob() {
  if (!TRANS_JOB) return;
  const j = await api('GET', '/api/jobs/' + TRANS_JOB);
  if (!j || j.error) return;
  // FR-43: 翻译与人工校对 —— 渲染进度与逐条结果，供人工确认/重试
  const done = j.done, total = j.total || STATE.translate.total;
  const todo = Math.max(0, total - done - (j.failed || 0));
  document.getElementById('p4bar').firstElementChild.style.width = j.progress + '%';
  document.getElementById('p4txt').textContent = Math.round(j.progress) + '%';
  const md = document.getElementById('m-done'); if (md) md.textContent = (STATE.translate.done + done).toLocaleString();
  const mt = document.getElementById('m-todo'); if (mt) mt.textContent = todo.toLocaleString();
  _etaText({ done, total });
  setSbProg(j.progress);
  sb('翻译进行中 · ' + done.toLocaleString() + ' / ' + total.toLocaleString());
  if (j.progress >= 100 || !j.running) {
    document.getElementById('p4bar').classList.add('ok');
    document.getElementById('btnTrans').textContent = '已全部翻译';
    document.getElementById('btnStop').disabled = true;
    STATE.translate.done += done;
    STATE.translate.failed += (j.failed || 0);
    document.getElementById('m-fail').textContent = STATE.translate.failed;
    document.getElementById('btnNext4').disabled = false;
    renderStep4Metrics();
    if (!DEMO) loadRows();      // 任务结束 → 表格刷成真实条目
    sb('翻译完成 · 失败 ' + (j.failed || 0) + ' 条，可下拉选「仅重试失败」');
    TRANS_JOB = null;
    return;
  }
  setTimeout(pollJob, 150);
}
async function stopTranslate() {
  if (!TRANS_JOB) return;
  await api('POST', '/api/jobs/' + TRANS_JOB + '/cancel');
  document.getElementById('btnStop').disabled = true;
  document.getElementById('btnTrans').disabled = false;
  sb('已停止翻译');
  TRANS_JOB = null;
}

/* ---------------- 第 4 步表格工具（FR-43：CSV / 查找替换 / 清理重复 / 右键菜单） ---------------- */
async function exportCsv() {
  const r = await api('POST', '/api/export-csv');
  if (r && r.ok) sb('已导出 ' + r.rows.toLocaleString() + ' 条 → ' + r.path);
  else sb((r && r.message) || '导出失败');
}
async function importCsv() {
  const r = await api('POST', '/api/import-csv');
  if (r && r.canceled) return;
  if (r && r.ok) {
    STATE.translate.total = r.total;
    STATE.translate.done = r.translated;
    renderStep4Metrics(); loadRows();
    sb('CSV 导入完成 · 更新 ' + r.updated.toLocaleString() + ' 条');
  } else sb((r && r.message) || '导入失败');
}
/* FR-56: 导入 TXT（原文=译文 / Tab 分隔 / 纯原文三形态自动识别合并） */
async function importTxt() {
  const r = await api('POST', '/api/import-txt');
  if (r && r.canceled) return;
  if (r && r.ok) {
    STATE.translate.total = r.total;
    STATE.translate.done = r.translated;
    renderStep4Metrics(); loadRows();
    sb('TXT 导入完成 · 更新 ' + r.updated.toLocaleString() + ' 条');
  } else sb((r && r.message) || '导入失败');
}

/* ---------------- FR-53: 翻译提示词管理（编辑 / 恢复默认 / 保存） ---------------- */
function openPrompt() {
  document.getElementById('promptTxt').value = (STATE.config && STATE.config.prompt) || '';
  document.getElementById('promptModal').classList.remove('hidden');
  document.getElementById('promptTxt').focus();
}
function closePrompt() { document.getElementById('promptModal').classList.add('hidden'); }
function resetPrompt() {
  // 恢复默认 = 内置 LLM_SYSTEM（真源随 /api/state 的 prompt_default 下发）
  document.getElementById('promptTxt').value = STATE.prompt_default || '';
  sb('已恢复内置默认提示词 · 记得点「保存」');
}
function savePrompt() {
  STATE.config = STATE.config || {};
  STATE.config.prompt = document.getElementById('promptTxt').value.replace(/\s+$/, '');
  closePrompt();
  // 立即落盘（带完整 config 体；连通时顺带刷新步骤状态）
  api('POST', '/api/config', _cfgBody()).then(r => {
    if (r && r.config) STATE.config = r.config;
    sb('提示词已保存 · 下次翻译生效（缓存已随提示词失效）');
  });
}
function openReplace() {
  document.getElementById('replModal').classList.remove('hidden');
  document.getElementById('replFind').focus();
}
function closeReplace() { document.getElementById('replModal').classList.add('hidden'); }
async function doReplace() {
  const find = document.getElementById('replFind').value;
  if (!find) { sb('请输入要查找的内容'); return; }
  const r = await api('POST', '/api/replace', {
    find,
    replace: document.getElementById('replWith').value,
    field: document.getElementById('replField').value,
  });
  closeReplace();
  if (r && r.ok) {
    if (r.stats) { STATE.translate.total = r.stats.total; STATE.translate.done = r.stats.translated; }
    renderStep4Metrics(); loadRows();
    sb('查找替换完成 · 改动 ' + r.replaced.toLocaleString() + ' 条');
  } else sb((r && r.message) || '替换失败');
}
async function dedupRows() {
  if (!confirm('按原文清理重复条目（有译文的优先保留），确定执行？')) return;
  const r = await api('POST', '/api/dedup');
  if (r && r.ok) {
    if (r.stats) { STATE.translate.total = r.stats.total; STATE.translate.done = r.stats.translated; }
    renderStep4Metrics(); loadRows();
    sb('清理完成 · 删除重复 ' + r.removed.toLocaleString() + ' 条，剩 ' + r.total.toLocaleString() + ' 条');
  } else sb((r && r.message) || '清理失败');
}
/* 右键行菜单：复制原文 / 复制译文 / 查看全文 / 清空译文 / 删除条目 */
function _copy(text) {
  if (navigator.clipboard) navigator.clipboard.writeText(text).then(() => sb('已复制'));
  else sb('复制失败 · 浏览器不支持剪贴板');
}
function onRowCtx(ev) {
  const tr = ev.target.closest && ev.target.closest('tr');
  if (!tr || !tr.dataset.ei) return;
  ev.preventDefault();
  const ei = +tr.dataset.ei;
  const orig = tr.cells[3] ? tr.cells[3].textContent : '';   // 第 4 列 = 原文
  const trans = tr.dataset.t || '';
  const menu = document.getElementById('ctxMenu');
  menu.innerHTML = `
    <button class="dd-item" onclick="_copy(${JSON.stringify(orig)});_hideCtx()">复制原文</button>
    <button class="dd-item" onclick="_copy(${JSON.stringify(trans)});_hideCtx()">复制译文</button>
    <button class="dd-item" onclick="viewFull(${ei});_hideCtx()">查看全文</button>
    <button class="dd-item" onclick="_clearRow(${ei});_hideCtx()">清空译文</button>
    <button class="dd-item" style="color:#e0526e" onclick="deleteRows([${ei}]);_hideCtx()">删除条目</button>`;
  menu.classList.remove('hidden');
  menu.style.left = Math.min(ev.clientX, innerWidth - 150) + 'px';
  menu.style.top = Math.min(ev.clientY, innerHeight - 160) + 'px';
}
function _hideCtx() { document.getElementById('ctxMenu').classList.add('hidden'); }
async function _clearRow(ei) {
  const r = await api('POST', '/api/row/edit', { i: ei, translation: '' });
  if (r && r.ok) { sb('已清空该条译文（状态回「未翻译」）'); loadRows(); }
  else sb((r && r.message) || '操作失败');
}
/* FR-57: 查看全文（长句在行内看不全 → 弹窗完整展示） */
function viewFull(ei) {
  const tr = document.querySelector(`#p4tbody tr[data-ei="${ei}"]`);
  if (!tr) return;
  document.getElementById('fullOrig').textContent = tr.cells[3] ? tr.cells[3].textContent : '';
  document.getElementById('fullTrans').textContent = tr.dataset.t || '（未翻译）';
  document.getElementById('fullModal').classList.remove('hidden');
}
function closeFull() { document.getElementById('fullModal').classList.add('hidden'); }
/* FR-57: 删除条目（indices = 条目序号；序号会移位 → 删完清空勾选集） */
async function deleteRows(indices) {
  if (!indices || !indices.length) return;
  if (!confirm('删除选中的 ' + indices.length + ' 条条目？删除后不可恢复（备份轮转除外）。')) return;
  const r = await api('POST', '/api/row/delete', { indices });
  if (r && r.ok) {
    SEL_ROWS.clear();
    STATE.translate.total = r.total;
    STATE.translate.done = r.translated;
    renderStep4Metrics(); loadRows();
    sb('已删除 ' + r.deleted.toLocaleString() + ' 条 · 剩 ' + r.total.toLocaleString() + ' 条');
  } else sb((r && r.message) || '删除失败');
}

/* ---------------- Step 5：落盘（按引擎变脸） ---------------- */
let SEL_ENGINE = null;            // 保存步骤当前选中的管线
function curEngineKey() { return (STATE.engine && STATE.engine.key) || 'unity'; }

async function loadSink(engineKey) {
  SEL_ENGINE = engineKey;
  const detected = curEngineKey();
  const locked = engineKey !== detected;   // FR-48: 选了非当前引擎 → 锁死保存按钮（锁死到当前游戏管线）
  // 同步顶部 seg 高亮（找到 onclick 里带该引擎 key 的按钮）
  document.querySelectorAll('#engSeg button').forEach(b => {
    const m = (b.getAttribute('onclick') || '').match(/'([^']+)'/);
    b.classList.toggle('on', !!(m && m[1] === engineKey));
  });
  document.getElementById('p5engineName').textContent = engineName(engineKey);
  document.getElementById('p5lockedTo').textContent = locked
    ? '预览形态 · 锁定：' + engineName(detected) + '（当前游戏识别结果）'
    : '锁定：' + engineName(detected) + '（当前游戏识别结果）';
  // 徽章跟随当前所选管线（预览哪个引擎就显示哪个的首字母）
  const badge = document.getElementById('p5badge');
  if (badge) badge.textContent = (engineName(engineKey) || '?').trim()[0] || '?';
  // 识别依据（第 2 步硬证据）
  const evBox = document.getElementById('p5evidence');
  if (evBox) {
    const ev = (STATE.engine && STATE.engine.evidence) || [];
    evBox.innerHTML = ev.length
      ? `<div class="subtle" style="margin-bottom:6px">识别依据（第 2 步扫描到的硬证据）</div>
         <div>${ev.map(e => `<span class="chip"><span class="chip-mono">${esc(e)}</span></span>`).join('')}</div>`
      : '';
  }
  // 「Coming soon」管线：只显示一句话，别的不放（老板 2026-10-10 指定）
  if (engineKey === 'manual') {
    document.getElementById('sinkView').innerHTML = `
      <div class="card"><div class="card-h">Coming soon</div>
        <div style="padding:36px 0;text-align:center;font-size:19px;font-weight:600;letter-spacing:.04em">敬请期待</div></div>`;
    return;
  }
  const v = await api('GET', '/api/sink?engine=' + engineKey);
  const m = (v.metrics || []).map(x =>
    `<div class="metric"><div class="metric-l">${x.l}</div><div class="metric-v">${x.v}</div><div class="metric-n">${x.n}</div></div>`).join('');
  const files = (v.files || []).map(f =>
    `<div class="rowitem"><div class="ri-main"><div class="mono">${f.path}</div><div class="ri-s">${f.note}</div></div>
     <div class="ri-side"><span class="badge b-${f.badge}">${f.action}</span></div></div>`).join('');
  let extra = '';
  if (v.whitelist && v.whitelist.length) {
    extra += `<div class="card"><div class="card-h">字段白名单</div><div>${
      v.whitelist.map(w => `<span class="chip"><span class="chip-mono">${w}</span></span>`).join('')
    }</div>` +
    (v.blacklist ? `<div class="subtle" style="margin-top:12px"><b>不翻：</b>${v.blacklist}</div>` : '') + `</div>`;
  }
  if (v.reasons) {
    extra += `<div class="card"><div class="card-h">为什么做不了</div>${
      v.reasons.map(r => `<div class="rowitem"><div class="ri-main"><div class="ri-t">${r.t}</div><div class="ri-s">${r.s}</div></div>
        <div class="ri-side"><span class="badge b-${r.badge}">阻断</span></div></div>`).join('')}</div>`;
  }
  if (v.alternatives) {
    extra += `<div class="card"><div class="card-h">能做的替代</div>${
      v.alternatives.map(a => `<div class="rowitem"><div class="ri-main"><div class="ri-t">${a.t}</div><div class="ri-s">${a.s}</div></div>
        <div class="ri-side"><span class="badge b-${a.badge||'info'}">${a.badge?'推荐':''}</span></div></div>`).join('')}</div>`;
  }
  // 还原原文：只在「当前游戏管线」下出现；预览其它管线时不显示（老板 10-10 反馈 6）
  const restore = (!locked && v.can_restore)
    ? `<button class="btn btn-danger" onclick="restoreOriginal()">还原原文</button>` : '';
  // 选了非当前引擎时，保存按钮禁用（锁死到当前游戏管线）
  const applyBtn = locked
    ? `<button class="btn btn-accent btn-lg" disabled title="当前游戏识别为 ${engineName(detected)}，不能按 ${engineName(engineKey)} 管线写入">${v.title}</button>`
    : `<button class="btn btn-accent btn-lg" onclick="applySink()">${v.title}</button>`;
  const lockNote = locked
    ? `<div class="infobar ib-warn"><svg class="ib-ico" width="17" height="17"><use href="#i-warn"/></svg>
        <div>当前游戏识别为 <b>${engineName(detected)}</b>，不能按 <b>${engineName(engineKey)}</b> 管线写入。点回上方「${engineName(detected)}」即可解锁保存。</div></div>`
    : '';
  // FR-41: 第 2 步点了「跳过，我手动装」→ 本步顶部常驻提示
  const skipHint = (STATE.kit && STATE.kit.skipped)
    ? `<div class="infobar ib-warn"><svg class="ib-ico" width="17" height="17"><use href="#i-warn"/></svg>
        <div>注入工具为手动安装 —— 保存前请自行确认对应插件已在游戏目录就位，否则译文不生效。</div></div>`
    : '';
  document.getElementById('sinkView').innerHTML = `
    ${skipHint}
    <div class="grid3">${m}</div>
    <div class="infobar ib-${v.kind==='none'?'danger':(v.kind==='rewrite'?'warn':'ok')}">
      <svg class="ib-ico" width="17" height="17"><use href="#i-${v.kind==='none'?'warn':'info'}"/></svg>
      <div>${v.warn}</div></div>
    ${files ? `<div class="card"><div class="card-h">${v.kind==='rewrite'?'回写位置':'写入位置'}</div>${files}</div>` : ''}
    ${extra}
    ${lockNote}
    <div class="btn-row spread">
      ${restore}
      ${applyBtn}
    </div>`;
}
function engineName(k) {
  if (STATE.engine && STATE.engine.key === k && STATE.engine.name) return STATE.engine.name;
  return { unity: 'Unity (Mono)', rm: 'RPG Maker MV', manual: 'Coming soon' }[k] || k;
}
function previewEngine(k, el) {
  document.querySelectorAll('#engSeg button').forEach(b => b.classList.remove('on'));
  el.classList.add('on');
  loadSink(k);
}
async function applySink() {
  if (SEL_ENGINE !== curEngineKey()) {
    sb('请先选回当前游戏管线（' + engineName(curEngineKey()) + '）再保存');
    return;
  }
  const r = await api('POST', '/api/sink/apply', { engine: SEL_ENGINE });
  if (r.error) { sb(r.message || '保存被拒绝'); return; }
  sb('已应用 · ' + (r.files || []).length + ' 个落点');
  goNext();
}
async function restoreOriginal() {
  const r = await api('POST', '/api/restore');
  if (r.error) { sb(r.message || '还原失败'); return; }
  sb('已还原到原文备份（' + (r.restored_from || '') + '）');
}

/* ---------------- Step 6：验证 ---------------- */
async function loadVerify() {
  const r = await api('GET', '/api/verify');
  document.getElementById('p6hint').innerHTML = '<b>' + r.hint + '</b>';
  // FR-45: 自检三项按真实结果渲染「通过 / 失败」，失败给可操作线索而非一句报错
  document.getElementById('p6checks').innerHTML = (r.checks || []).map(c => {
    const ok = c.ok !== false;
    return `<div class="rowitem"><div class="ri-main"><div class="ri-t">${c.t}</div><div class="ri-s mono">${c.s}</div></div>
     <div class="ri-side"><span class="badge b-${ok ? 'ok' : 'danger'}">${ok ? '通过' : '失败'}</span></div></div>`;
  }).join('');
  document.getElementById('btnRestore').hidden = !(STATE.sink && STATE.sink.backup);
}
async function launchGame() {
  sb('正在启动游戏…');
  const r = await api('POST', '/api/launch');
  if (r && r.ok) sb('已启动游戏 · ' + r.exe);
  else sb((r && r.message) || '启动失败 · 请手动启动游戏');
}
async function openTransDir() {
  const r = await api('POST', '/api/open-dir');
  if (r && r.ok) sb('已打开译文目录');
  else sb((r && r.message) || '打开失败');
}

/* ---------------- 启动 ---------------- */
/* FR-50: 无边框窗口控制（v0.4）——仅 pywebview 宿主内显示（浏览器/DEMO 无桥自动隐藏） */
function initWinCtl() {
  const box = document.getElementById('winCtl');
  if (!box) return;
  const bind = () => {
    const api = window.pywebview && window.pywebview.api;
    if (!api || typeof api.minimize !== 'function') return false;
    document.getElementById('winMin').onclick = () => api.minimize();
    document.getElementById('winMax').onclick = () => api.toggle_max();
    document.getElementById('winClose').onclick = () => api.close();
    box.hidden = false;
    return true;
  };
  if (bind()) return;
  window.addEventListener('pywebviewready', bind, { once: true });
}

/* ---------------- FR-62: 设置菜单（齿轮统收设置类功能） ---------------- */
function toggleSettings() {
  const m = document.getElementById('gearMenu');
  m.classList.toggle('hidden');
  if (!m.classList.contains('hidden')) {
    // 贴着齿轮按钮右下角展开，并夹在窗口内
    const btn = document.getElementById('gearBtn');
    const r = btn.getBoundingClientRect();
    const w = 264, top = r.bottom + 6;
    m.style.top = Math.min(top, innerHeight - 340) + 'px';
    m.style.left = Math.max(8, Math.min(r.right - w, innerWidth - w - 8)) + 'px';
    const v = document.getElementById('gearVer');
    if (v) v.textContent = 'v' + ((STATE && STATE.app_version) || '—');
    const th = document.getElementById('gearThemeHint');
    if (th) th.textContent =
      document.documentElement.getAttribute('data-theme') === 'light'
        ? '当前：明亮模式 · 点击切换' : '当前：暗色模式 · 点击切换';
  }
}
/* 齿轮菜单各项动作 */
function gotoCfg() { goto(0); }
async function checkKit() {
  const r = await api('GET', '/api/kit/check');
  if (r && r.ok) sb('注入工具校验：' + r.message);
  else sb('注入工具校验：' + ((r && r.message) || '失败'));
}
async function openLogs() {
  const r = await api('GET', '/api/logs');
  const t = r && r.text ? r.text : '（暂无日志）';
  const ov = document.getElementById('logModal');
  document.getElementById('logTxt').textContent = t;
  ov.classList.remove('hidden');
  try { navigator.clipboard && navigator.clipboard.writeText(t).then(() => {}); } catch (e) {}
}
function closeLogs() { document.getElementById('logModal').classList.add('hidden'); }

(async function init() {
  await loadProviders();
  await loadState();
  fillTable();
  initWinCtl();
  loadRecent();                                             // FR-39: 最近使用列表
  // FR-38: 上次已连通（config 记忆）→ 保存按钮直接可用
  if (STATE.config && STATE.config.connected) {
    const save = document.getElementById('btnSaveCfg');
    if (save) { save.disabled = false; save.removeAttribute('title'); }
  }
  const tb4 = document.getElementById('p4tbody');
  if (tb4) tb4.addEventListener('dblclick', onRowDblClick);   // 双击行改译文
  if (tb4) tb4.addEventListener('contextmenu', onRowCtx);     // FR-43: 右键行菜单
  document.addEventListener('click', () => {                  // 点空白收起下拉/右键菜单
    const dd = document.getElementById('ddScope'); if (dd) dd.classList.add('hidden');
    const gm = document.getElementById('gearMenu'); if (gm) gm.classList.add('hidden');
    _hideCtx();
  });
  // FR-51: 版本号常显状态栏（真源 = server.APP_VERSION，随 /api/state 下发）
  if (!DEMO && STATE.app_version)
    document.getElementById('appVer').textContent = 'v' + STATE.app_version;
  if (DEMO) sb('离线预览模式 · 未连接后端（双击「启动 G-POT 翻译器.bat」为完整功能）');
})();
