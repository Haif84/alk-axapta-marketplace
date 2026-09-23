#!/usr/bin/env node
/*
 * session-cost.js — стоимость сессий Claude Code по локальным транскриптам.
 *
 * /cost в этой сборке недоступен; счётчики usage есть в каждой строке
 * ассистента в ~/.claude/projects/<проект>/<session>.jsonl. Скрипт суммирует
 * токены по моделям (дедупликация по requestId — один запрос пишется
 * несколькими строками) и считает цену по прайсу API.
 *
 * Использование:
 *   node session-cost.js                      # текущая папка проекта, последняя сессия
 *   node session-cost.js --all                # все сессии проекта, по одной строке на сессию
 *   node session-cost.js --since 2026-09-08   # сессии, изменённые с даты
 *   node session-cost.js <файл.jsonl|папка>   # явный путь
 *   node session-cost.js --agents             # плюс строка на каждый вызов
 *                                             # сабагента: модель и effort
 *   node session-cost.js --prompts            # плюс строка на каждый ход
 *                                             # владельца: цена его сообщения
 *
 * Прайс и коэффициенты записи кэша — в `prices.js`, общие с `cache-split.js`.
 */
const fs = require('fs');
const path = require('path');

const { PRICE, normModel, CACHE_WRITE } = require('./prices');
const { projectDirs, listSessions } = require('./transcripts');

const args = process.argv.slice(2);
const all = args.includes('--all');
const perCall = args.includes('--agents');
const perPrompt = args.includes('--prompts');
const sinceIdx = args.indexOf('--since');
const since = sinceIdx >= 0 ? new Date(args[sinceIdx + 1]) : null;
const explicit = args.find(a => !a.startsWith('--') && a !== (sinceIdx >= 0 ? args[sinceIdx + 1] : null));

function sessionFiles() {
  if (explicit && fs.statSync(explicit).isFile()) return [explicit];
  let dirs;
  // Каталогов у проекта бывает несколько: работа из подпапки заводит свой.
  try { dirs = explicit ? [explicit] : projectDirs(); }
  catch (e) { console.error(e.message); process.exit(1); }
  let files = listSessions(dirs);
  if (since) files = files.filter(x => x.mtime >= since);
  if (!all && !since) files = files.slice(-1);
  return files.map(x => x.file);
}

// Транскрипты сабагентов лежат в <папка>/<сессия>/subagents/*.jsonl —
// их стоимость относится к сессии, которая их запустила. Тип агента
// (Explore, general-purpose, …) хранится рядом в agent-<id>.meta.json.
function sessionParts(file) {
  const sub = path.join(path.dirname(file), path.basename(file, '.jsonl'), 'subagents');
  if (!fs.existsSync(sub)) return [{ part: file, sub: false }];
  const meta = f => {
    try {
      const m = JSON.parse(fs.readFileSync(path.join(sub, f.replace(/\.jsonl$/, '.meta.json')), 'utf8'));
      return { agent: m.agentType || '?', desc: m.description || '' };
    }
    catch { return { agent: '?', desc: '' }; }
  };
  return [{ part: file, sub: false },
    ...fs.readdirSync(sub).filter(f => f.endsWith('.jsonl'))
      .map(f => ({ part: path.join(sub, f), sub: true, ...meta(f) }))];
}

// Счётчики хода. Строка модели в сессии несёт сверх них долю сабагентов и
// effort; в разрезе по типу агента эти два поля оставались бы нулями.
const zeroModel = () => ({ req: 0, in: 0, cw5: 0, cw1h: 0, cr: 0, out: 0,
  think: 0, ws: 0, wf: 0, maxCtx: 0 });
const zero = () => ({ ...zeroModel(), subReq: 0, effort: new Set() });

// Ход владельца открывает только его собственное сообщение. Критерий взят из
// анализатора `analyze-sessions.mjs` (docs/scripts.md): служебные записи ходят
// тем же типом `user` — результат инструмента, впрыск хука, сводка сжатия,
// прерывание. Уведомление о готовности сабагента продолжает предыдущий ход:
// владелец за него не платил отдельным сообщением.
function addPrompt(prompts, line) {
  let o; try { o = JSON.parse(line); } catch { return; }
  if (o.type !== 'user' || o.isMeta || o.isCompactSummary || o.isSidechain) return;
  const c = o.message && o.message.content;
  let text = null;
  if (typeof c === 'string') text = c;
  // Вставленный скриншот приходит блоком перед текстом, поэтому берётся
  // первый текстовый блок, а не нулевой; записи с tool_result ходом не
  // считаются, и текст в них не ищется.
  else if (Array.isArray(c) && !c.some(b => b && b.type === 'tool_result'))
    text = ((c.find(b => b && b.type === 'text') || {}).text) || '';
  if (!text) return;
  if (/^(<task-notification|<scheduled-wakeup|<background-task|\[Request interrupted)/.test(text)) return;
  prompts.push({ ts: (o.timestamp && Date.parse(o.timestamp)) || 0,
    text: text.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 60),
    req: 0, subReq: 0, models: {} });
}

function sumFile(file) {
  const byReq = new Map();
  const prompts = [];
  const meta = { branch: new Set(), t0: null, t1: null };
  const byAgent = {};
  const byCall = new Map();
  const lines = sessionParts(file).flatMap(({ part, sub, agent, desc }) =>
    fs.readFileSync(part, 'utf8').split('\n').map(line => ({ line, sub, agent, desc, part })));
  for (const { line, sub, agent, desc, part } of lines) {
    if (perPrompt && !sub && line.includes('"type":"user"')) addPrompt(prompts, line);
    if (!line.includes('"usage"')) continue;
    let o; try { o = JSON.parse(line); } catch { continue; }
    const m = o.message; if (!m || !m.usage) continue;
    // <synthetic> — строка самого CLI (ошибка API, «No response requested»),
    // а не ход модели: счётчики нулевые, в прайсе её нет.
    if (m.model === '<synthetic>') continue;
    // Ход сабагента виден и по файлу, и по флагу isSidechain — берём любой.
    byReq.set(o.requestId || o.uuid, { model: normModel(m.model), u: m.usage,
      sub: sub || o.isSidechain === true, effort: o.perTurnEffort || o.effort,
      agent: sub ? agent : undefined, desc, part,
      ts: (o.timestamp && Date.parse(o.timestamp)) || 0 });
    if (o.gitBranch) meta.branch.add(o.gitBranch);
    const t = o.timestamp && Date.parse(o.timestamp);
    if (t) { if (!meta.t0 || t < meta.t0) meta.t0 = t; if (!meta.t1 || t > meta.t1) meta.t1 = t; }
  }
  const per = {};
  const add = (p, u) => {
    const cc = u.cache_creation;
    p.req++;
    p.in += u.input_tokens || 0;
    // Разбивка по TTL есть не всегда; без неё вся запись считается пятиминутной.
    p.cw1h += (cc && cc.ephemeral_1h_input_tokens) || 0;
    p.cw5 += cc ? (cc.ephemeral_5m_input_tokens || 0)
                : (u.cache_creation_input_tokens || 0);
    p.cr += u.cache_read_input_tokens || 0;
    p.out += u.output_tokens || 0;
    p.think += (u.output_tokens_details && u.output_tokens_details.thinking_tokens) || 0;
    const st = u.server_tool_use || {};
    p.ws += st.web_search_requests || 0;
    p.wf += st.web_fetch_requests || 0;
    // Контекст хода: всё, за что платим на входе. Максимум показывает,
    // насколько сессия разрослась к концу.
    const ctx = (u.input_tokens || 0) + (u.cache_read_input_tokens || 0)
      + (cc ? (cc.ephemeral_5m_input_tokens || 0) + (cc.ephemeral_1h_input_tokens || 0)
            : (u.cache_creation_input_tokens || 0));
    if (ctx > p.maxCtx) p.maxCtx = ctx;
  };
  // Ход владельца длится до следующего его сообщения: всё, что модель и её
  // сабагенты успели за это время, оплачено этим сообщением. Привязка по
  // времени, а не по связям запросов, одинаково ловит и водителя, и сабагентов.
  const head = { ts: 0, text: '', req: 0, subReq: 0, models: {} };
  const bucket = ts => {
    for (let i = prompts.length - 1; i >= 0; i--) if (ts >= prompts[i].ts) return prompts[i];
    return head;
  };
  for (const { model, u, sub, effort, agent, desc, part, ts } of byReq.values()) {
    if (perPrompt) {
      const b = bucket(ts);
      b.req++; if (sub) b.subReq++;
      add(b.models[model] || (b.models[model] = zeroModel()), u);
    }
    const p = per[model] || (per[model] = zero());
    if (effort) p.effort.add(effort);
    if (sub) p.subReq++;
    add(p, u);
    if (agent) {
      const a = byAgent[agent] || (byAgent[agent] = { calls: new Set(), models: {} });
      a.calls.add(part);
      add(a.models[model] || (a.models[model] = zeroModel()), u);
      // Вызов — один файл транскрипта: модель и effort у него свои.
      let c = byCall.get(part);
      if (!c) byCall.set(part, c = { agent, desc, models: {}, effort: new Set() });
      if (effort) c.effort.add(effort);
      add(c.models[model] || (c.models[model] = zeroModel()), u);
    }
  }
  return { per, meta, byAgent, calls: [...byCall.values()],
    prompts: head.req ? [head, ...prompts] : prompts };
}

// Цена по статьям: видно, куда именно уходят деньги.
function costParts(model, p) {
  const pr = PRICE[model];
  if (!pr) return null;
  const c = {
    in: p.in * pr.in, cw5: p.cw5 * pr.in * CACHE_WRITE['5m'],
    cw1h: p.cw1h * pr.in * CACHE_WRITE['1h'], cr: p.cr * pr.cr, out: p.out * pr.out,
  };
  for (const key of Object.keys(c)) c[key] /= 1e6;
  c.total = c.in + c.cw5 + c.cw1h + c.cr + c.out;
  return c;
}

const cost = (model, p) => { const c = costParts(model, p); return c ? c.total : NaN; };

const k = n => (n / 1000).toFixed(1).padStart(8) + 'k';
// Ход владельца тянет за собой миллионы токенов: в тысячах строка нечитаема.
const tok = x => (x >= 1e6 ? (x / 1e6).toFixed(1) + 'M' : (x / 1000).toFixed(1) + 'k').padStart(8);
const n = x => String(Math.round(x)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ').padStart(12);
const d = x => '$' + x.toFixed(2).padStart(7);
const pct = (a, b) => (b ? (100 * a / b).toFixed(1) : '0.0') + '%';
// Средний контекст на запрос: вход + запись в кэш + чтение кэша. Плата за ход
// равна всему накопленному контексту, поэтому avg — мера длины сессии.
const avg = p => k(p.req ? (p.in + p.cw5 + p.cw1h + p.cr) / p.req : 0);
const dur = m => {
  if (!m.t0 || m.t1 === m.t0) return '';
  const min = Math.round((m.t1 - m.t0) / 60000);
  return min < 60 ? `${min}м` : `${Math.floor(min / 60)}ч ${String(min % 60).padStart(2, '0')}м`;
};

function report(model, p) {
  const c = costParts(model, p);
  const D = x => (c ? d(x) : '      $?');
  const head = [`  ${model.padEnd(18)} req ${String(p.req).padStart(4)}`];
  if (p.subReq) head.push(`(водитель ${p.req - p.subReq} / сабагенты ${p.subReq})`);
  head.push(`effort ${[...p.effort].join(',') || '—'}`);
  console.log(head.join('  '));
  console.log(`      вход      ${n(p.in)}  ${D(c && c.in)}`);
  // Запись кэша идёт либо по пятиминутному TTL, либо по часовому — пустую
  // строку не печатаем, чтобы видно было, какой режим работал.
  if (p.cw5 || !p.cw1h) console.log(`      запись 5m ${n(p.cw5)}  ${D(c && c.cw5)}`);
  if (p.cw1h) console.log(`      запись 1h ${n(p.cw1h)}  ${D(c && c.cw1h)}`);
  console.log(`      чтение    ${n(p.cr)}  ${D(c && c.cr)}  кэш-чтение ${pct(p.cr, p.in + p.cw5 + p.cw1h + p.cr)}`);
  console.log(`      выход     ${n(p.out)}  ${D(c && c.out)}  думанье ${n(p.think).trim()} (${pct(p.think, p.out)})`);
  const tot = p.in + p.cw5 + p.cw1h + p.cr + p.out;
  console.log(`      всего     ${n(tot)}   avg${avg(p)} max${k(p.maxCtx)}  $/ход ${c ? (c.total / (p.req || 1)).toFixed(3) : '?'}`);
  if (p.ws || p.wf) console.log(`      web: search ${p.ws}  fetch ${p.wf}  (сверх токенов, в сумму не входит)`);
}

// Разрез сабагентов по типу агента: вызов — файл транскрипта, запрос — ход.
function reportAgents(byAgent) {
  const rows = Object.entries(byAgent).map(([t, a]) => {
    let req = 0, inp = 0, sum = 0; const unpriced = [];
    for (const [model, p] of Object.entries(a.models)) {
      req += p.req; inp += p.in + p.cw5 + p.cw1h + p.cr;
      // Модель без прайса дала бы $0.00 молча — её называем в конце строки.
      const c = cost(model, p);
      if (isNaN(c)) unpriced.push(model); else sum += c;
    }
    return { t, calls: a.calls.size, req, inp, sum, unpriced };
  }).sort((x, y) => y.sum - x.sum);
  if (!rows.length) return;
  console.log('      сабагенты по типам:');
  for (const r of rows) {
    // Пробел в типе разорвал бы колонку, по которой разрез читают замеры.
    const t = r.t.replace(/\s+/g, '_');
    console.log(`        ${t.padEnd(18)}  вызовов ${r.calls}  req ${r.req}  вход ${n(r.inp).trim()}  на вызов ${k(r.inp / r.calls).trim()}  $${r.sum.toFixed(2)}  ($${(r.sum / r.calls).toFixed(2)}/вызов)`
      + (r.unpriced.length ? `  — без прайса: ${r.unpriced.join(',')}` : ''));
  }
}

// Разрез по вызовам (--agents): у агентов одного типа модель и effort бывают
// разные, в строке типа они сливаются. Отвечает на вопрос «кто на чём шёл».
function reportCalls(calls) {
  if (!calls.length) return;
  const rows = calls.map(c => {
    let inp = 0, sum = 0; const models = [];
    for (const [model, p] of Object.entries(c.models)) {
      inp += p.in + p.cw5 + p.cw1h + p.cr;
      const x = cost(model, p); if (!isNaN(x)) sum += x;
      models.push(model);
    }
    // Агент без meta.json остаётся без описания — показываем хотя бы тип.
    return { desc: c.desc || c.agent, agent: c.agent, models: models.join(','),
      effort: [...c.effort].join(',') || '—', inp, sum };
  }).sort((x, y) => y.sum - x.sum);
  console.log('      сабагенты по вызовам:');
  for (const r of rows) {
    console.log(`        ${r.desc.slice(0, 28).padEnd(28)}  ${r.agent.padEnd(16)}`
      + `  ${r.models.padEnd(18)}  ${r.effort.padEnd(6)}  вход ${k(r.inp).trim().padStart(7)}  $${r.sum.toFixed(2)}`);
  }
}

// Разрез по ходам (--prompts): сколько стоило одно сообщение владельца вместе
// со всем, что модель сделала в ответ. Отвечает на вопрос «почём шаг цикла».
function reportPrompts(prompts) {
  if (!prompts.length) return;
  console.log('      ходы владельца:');
  for (const p of prompts) {
    let inp = 0, out = 0, cr = 0, sum = 0, unpriced = false;
    for (const [model, m] of Object.entries(p.models)) {
      inp += m.in + m.cw5 + m.cw1h + m.cr; out += m.out; cr += m.cr;
      const c = cost(model, m); if (isNaN(c)) unpriced = true; else sum += c;
    }
    // Ход до первого сообщения владельца бывает у возобновлённой сессии:
    // времени начала у него нет, но токены его есть.
    const t = p.ts ? new Date(p.ts) : null;
    const time = t ? `${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}` : '—';
    console.log(`        ${time.padEnd(5)}  req ${String(p.req).padEnd(3)}  саб ${String(p.subReq).padEnd(2)}`
      + `  вход ${tok(inp)}  выход ${tok(out)}  кэш ${pct(cr, inp)}  ${unpriced ? '      $?' : d(sum)}  ${p.text}`);
  }
}

const total = {};
const totalAgents = {};
for (const file of sessionFiles()) {
  const { per, meta, byAgent, calls, prompts } = sumFile(file);
  let fileCost = 0;
  console.log([path.basename(file, '.jsonl'), [...meta.branch].join(','), dur(meta)]
    .filter(Boolean).join('   '));
  for (const [model, p] of Object.entries(per)) {
    const c = cost(model, p); fileCost += c || 0;
    report(model, p);
    const t = total[model] || (total[model] = zero());
    for (const key of Object.keys(t)) {
      if (key === 'effort') p.effort.forEach(e => t.effort.add(e));
      else t[key] = key === 'maxCtx' ? Math.max(t[key], p[key]) : t[key] + p[key];
    }
  }
  reportAgents(byAgent);
  if (perCall) reportCalls(calls);
  if (perPrompt) reportPrompts(prompts);
  for (const [t, a] of Object.entries(byAgent)) {
    const ta = totalAgents[t] || (totalAgents[t] = { calls: new Set(), models: {} });
    a.calls.forEach(c => ta.calls.add(c));
    for (const [model, p] of Object.entries(a.models)) {
      const tp = ta.models[model] || (ta.models[model] = zeroModel());
      for (const key of Object.keys(tp)) {
        tp[key] = key === 'maxCtx' ? Math.max(tp[key], p[key]) : tp[key] + p[key];
      }
    }
  }
  console.log(`  итого $${fileCost.toFixed(2)}`);
}
if (Object.keys(total).length > 1 || all || since) {
  let sum = 0;
  console.log('ВСЕГО');
  // Строка на модель — та же, что раньше уходила в docs/costs.md.
  for (const [model, p] of Object.entries(total)) { const c = cost(model, p); sum += c || 0;
    console.log(`  ${model.padEnd(18)} req ${String(p.req).padStart(4)}  in${k(p.in)} cw${k(p.cw5 + p.cw1h)} cr${k(p.cr)} out${k(p.out)} (think${k(p.think)}) avg${avg(p)}  $${isNaN(c) ? '?' : c.toFixed(2)}`); }
  reportAgents(totalAgents);
  console.log(`  $${sum.toFixed(2)}`);
}
