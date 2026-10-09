/* ===========================================================================
 * G-POT Loc 前端 —— 纯静态，只通过 fetch() 与本地 API 对话。
 * 本文件不含任何业务规则：导航锁、解锁链、引擎识别、落盘分流全在后端。
 * ========================================================================= */
'use strict';

const API = '';                 // 同源，留空即可
let STATE = null;               // 最近一次 /api/state
let SEL_PROV = 'ollama';        // 当前选中的提供方
let TRANS_JOB = null;           // 进行中的翻译任务 id

/* ---------------- 底层 ---------------- */
async function api(method, path, body) {
  const opt = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opt.body = JSON.stringify(body);
  const r = await fetch(API + path, opt);
  return r.json().catch(() => ({}));
}
function sb(msg) { document.getElementById('sbMsg').textContent = msg; }
function setSbProg(pct) {
  document.getElementById('sbBar').style.width = pct + '%';
  document.getElementById('sbPct').textContent = Math.round(pct) + '%';
}

/* ---------------- 状态加载与渲染 ---------------- */
async function loadState() {
  STATE = await api('GET', '/api/state');
  renderRail();
  renderGameCard();
  renderStep4Metrics();
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
  const pct = Math.round(t.done / t.total * 100);
  const box = document.getElementById('p4metrics');
  box.innerHTML = `
    <div class="metric"><div class="metric-l">总条目</div><div class="metric-v">${t.total.toLocaleString()}</div><div class="metric-n">1,424,251 B</div></div>
    <div class="metric"><div class="metric-l">已翻译</div><div class="metric-v" id="m-done">${t.done.toLocaleString()}</div><div class="metric-n">${pct}%</div></div>
    <div class="metric"><div class="metric-l">未翻译</div><div class="metric-v" id="m-todo">${todo.toLocaleString()}</div><div class="metric-n">本次目标</div></div>
    <div class="metric"><div class="metric-l">失败</div><div class="metric-v" id="m-fail">${t.failed}</div><div class="metric-n">多为超长/超时</div></div>`;
  const bar = document.getElementById('p4bar');
  bar.firstElementChild.style.width = pct + '%';
  document.getElementById('p4txt').textContent = pct + '%';
}

function showPage(i) {
  document.querySelectorAll('.page').forEach(p => {
    p.classList.toggle('active', +p.dataset.page === i);
  });
  document.querySelector('.content').scrollTop = 0;
}
function curPage() { return STATE.current_step; }

/* ---------------- 导航 ---------------- */
async function goto(i) {
  const r = await api('POST', '/api/nav', { step: i });
  if (r && r.max_step !== undefined && i <= r.max_step) {
    STATE = r; renderRail(); showPage(i);
    if (i === 5) await loadSink(curEngineKey());
    if (i === 6) await loadVerify();
  } else sb('这一步还没解锁');
}
async function goNext() {
  const next = STATE.current_step + 1;
  const r = await api('POST', '/api/nav', { step: next });
  if (r && r.max_step !== undefined && next <= r.max_step) {
    STATE = r; renderRail(); showPage(next);
    if (next === 5) await loadSink(curEngineKey());
    if (next === 6) await loadVerify();
  } else sb('先完成本步，下一步才解锁');
}
async function resetAll() {
  await api('POST', '/api/reset');
  await loadState();
  sb('演示已重置 · 从第 0 步开始');
}

/* ---------------- Step 0：配置 ---------------- */
async function loadProviders() {
  const r = await api('GET', '/api/providers');
  const grid = document.getElementById('provGrid');
  grid.innerHTML = (r.providers || []).map(p => `
    <button class="prov ${p.key === SEL_PROV ? 'on' : ''}" data-k="${p.key}" onclick="pickProv(this)">
      <div class="prov-tick"><svg width="10" height="10"><use href="#i-check"/></svg></div>
      <div class="prov-n">${p.name}</div>
      <div class="prov-d">${p.desc}</div>
    </button>`).join('');
}
function pickProv(el) {
  document.querySelectorAll('.prov').forEach(x => x.classList.remove('on'));
  el.classList.add('on');
  SEL_PROV = el.dataset.k;
}
async function saveConfig() {
  const r = await api('POST', '/api/config', {
    provider: SEL_PROV,
    model: document.getElementById('cfgModel').value,
    address: document.getElementById('cfgAddr').value,
  });
  STATE.config = r.config;
  renderCfgStatus(r);
  if (r.connected) { sb('翻译服务已连通'); goNext(); }
}
async function testConn() {
  const r = await api('POST', '/api/config', {
    provider: SEL_PROV,
    model: document.getElementById('cfgModel').value,
    address: document.getElementById('cfgAddr').value,
  });
  renderCfgStatus(r);
}
function renderCfgStatus(r) {
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
async function selectGame() {
  const path = document.getElementById('gamePath').value;
  const g = await api('POST', '/api/game', { path });
  STATE.game = g;
  renderGameCard();
  const info = document.getElementById('gameInfo');
  info.innerHTML = `<div class="infobar ib-info"><svg class="ib-ico" width="17" height="17"><use href="#i-info"/></svg>
    <div>已有 <b>${g.existing.toLocaleString()}</b> 条译文 · 继续只做增量，不覆盖</div></div>`;
  sb('已选择 ' + g.name);
  goNext();
}
function pickFolder() {
  // WebView2 内无原生对话框；此处提示用户直接粘贴路径
  sb('请在输入框粘贴游戏根目录路径');
}

/* ---------------- Step 2：识别引擎 ---------------- */
async function detectEngine() {
  const btn = document.getElementById('btnDetect');
  btn.disabled = true; btn.textContent = '识别中…';
  const eng = await api('POST', '/api/detect');
  STATE.engine = eng;
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
      <button class="btn btn-accent btn-lg" id="btnDeploy" onclick="deployKit()">部署注入工具</button>
      <button class="btn btn-ghost" onclick="goNext()">跳过，我手动装</button>
    </div>`;
  sb('识别为 ' + eng.name);
}
async function deployKit() {
  const btn = document.getElementById('btnDeploy');
  btn.disabled = true; btn.textContent = '部署中…';
  const kit = await api('POST', '/api/deploy');
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
  btn.textContent = '重新校验';
  btn.disabled = false;
  sb('注入工具已就位');
  goNext();
}

/* ---------------- Step 3：提取 ---------------- */
async function runExtract() {
  const btn = document.getElementById('btnExtract');
  btn.disabled = true; btn.textContent = '扫描中…';
  document.getElementById('p3prog').classList.remove('hidden');
  const r = await api('POST', '/api/extract');
  document.getElementById('p3result').classList.remove('hidden');
  document.getElementById('p3result').innerHTML = `
    <div class="metric"><div class="metric-l">本轮新增</div><div class="metric-v">${r.added.toLocaleString()}</div><div class="metric-n">新提取到的原文</div></div>
    <div class="metric"><div class="metric-l">已存在</div><div class="metric-v">${r.existing.toLocaleString()}</div><div class="metric-n">跳过，不覆盖原译文</div></div>
    <div class="metric"><div class="metric-l">护栏拦截</div><div class="metric-v">${r.guarded.toLocaleString()}</div><div class="metric-n">疑似碎片/污染</div></div>
    <div class="metric"><div class="metric-l">在表总数</div><div class="metric-v">${r.total.toLocaleString()}</div><div class="metric-n">当前全部条目</div></div>`;
  btn.textContent = '重新提取'; btn.disabled = false;
  document.getElementById('btnNext3').disabled = false;
  sb('提取完成 · 新增 ' + r.added + ' 条');
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
  ok:  '<span class="badge b-ok">已翻译</span>',
  warn:'<span class="badge b-warn">英文残留</span>',
  todo:'<span class="badge b-danger">未翻译</span>',
  fail:'<span class="badge b-danger">失败</span>'
};
function fillTable() {
  const tb = document.getElementById('p4tbody');
  if (tb.dataset.filled) return;
  tb.innerHTML = ROWS.map((r, i) => {
    const dst = (r[2] === 'todo' || r[2] === 'fail')
      ? '<span style="color:#8A93A3">（未翻译）</span>' : r[1];
    return `<tr><td class="c-num">${i+1}</td><td class="c-stat">${STATMAP[r[2]]}</td><td>${r[0]}</td><td>${dst}</td></tr>`;
  }).join('');
  tb.dataset.filled = '1';
}
async function runTranslate(retry) {
  const btn = document.getElementById('btnTrans');
  btn.disabled = true;
  document.getElementById('btnStop').disabled = false;
  const r = await api('POST', '/api/translate/start', { retry: !!retry });
  TRANS_JOB = r.job_id;
  pollJob();
}
async function pollJob() {
  if (!TRANS_JOB) return;
  const j = await api('GET', '/api/jobs/' + TRANS_JOB);
  if (!j || j.error) return;
  // FR-43: 翻译与人工校对 —— 渲染进度与逐条结果，供人工确认/重试
  const done = j.done, total = STATE.translate.total;
  const todo = Math.max(0, total - done - STATE.translate.failed);
  document.getElementById('p4bar').firstElementChild.style.width = j.progress + '%';
  document.getElementById('p4txt').textContent = Math.round(j.progress) + '%';
  const md = document.getElementById('m-done'); if (md) md.textContent = done.toLocaleString();
  const mt = document.getElementById('m-todo'); if (mt) mt.textContent = todo.toLocaleString();
  setSbProg(j.progress);
  sb('翻译进行中 · ' + done.toLocaleString() + ' / ' + total.toLocaleString());
  if (j.progress >= 100 || !j.running) {
    document.getElementById('p4bar').classList.add('ok');
    document.getElementById('btnTrans').textContent = '已全部翻译';
    document.getElementById('btnStop').disabled = true;
    document.getElementById('m-fail').textContent = STATE.translate.failed;
    document.getElementById('btnNext4').disabled = false;
    sb('翻译完成 · 失败 ' + STATE.translate.failed + ' 条，可单独重试');
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
  document.getElementById('p5lockedTo').textContent =
    '锁定：' + engineName(detected) + '（当前游戏识别结果）';
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
  const restore = v.can_restore
    ? `<button class="btn btn-danger" onclick="restoreOriginal()">还原原文</button>` : '';
  // 选了非当前引擎时，保存按钮禁用（锁死到当前游戏管线）
  const applyBtn = locked
    ? `<button class="btn btn-accent btn-lg" disabled title="当前游戏识别为 ${engineName(detected)}，不能按 ${engineName(engineKey)} 管线写入">${v.title}</button>`
    : `<button class="btn btn-accent btn-lg" onclick="applySink()">${v.title}</button>`;
  const lockNote = locked
    ? `<div class="infobar ib-warn"><svg class="ib-ico" width="17" height="17"><use href="#i-warn"/></svg>
        <div>当前游戏识别为 <b>${engineName(detected)}</b>，不能按 <b>${engineName(engineKey)}</b> 管线写入。点回上方「${engineName(detected)}」即可解锁保存。</div></div>`
    : '';
  document.getElementById('sinkView').innerHTML = `
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
  return { unity: 'Unity (Mono)', rm: 'RPG Maker MV', manual: '无方案引擎' }[k] || k;
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
async function restoreOriginal() { sb('已还原到原文备份'); }

/* ---------------- Step 6：验证 ---------------- */
async function loadVerify() {
  const r = await api('GET', '/api/verify');
  document.getElementById('p6hint').innerHTML = '<b>' + r.hint + '</b>';
  document.getElementById('p6checks').innerHTML = (r.checks || []).map(c =>
    `<div class="rowitem"><div class="ri-main"><div class="ri-t">${c.t}</div><div class="ri-s mono">${c.s}</div></div>
     <div class="ri-side"><span class="badge b-ok">通过</span></div></div>`).join('');
  document.getElementById('btnRestore').hidden = !(STATE.sink && STATE.sink.backup);
}

/* ---------------- 启动 ---------------- */
(async function init() {
  await loadProviders();
  await loadState();
  fillTable();
})();
