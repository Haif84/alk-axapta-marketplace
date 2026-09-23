#!/usr/bin/env node
/*
 * skill-usage.js — какие скиллы вызывались и во что обходится их листинг.
 * Замена встроенного /skill-doctor: тот считает отчёт локально, но не отдаёт
 * его на части соединений («Skill usage reports are not available on this
 * connection»). Данные те же — транскрипты ~/.claude/projects.
 *
 *   node scripts/skill-usage.js [--since <дата>]   — кто сколько раз вызывался
 *   node scripts/skill-usage.js --listing          — цена листинга по скиллам
 *   node scripts/skill-usage.js --cost [--since <дата>]  — деньги за работу скиллов
 */
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const { projectDir } = require('./transcripts');
const { PRICE, normModel, CACHE_WRITE } = require('./prices');

const LISTING_HEAD = 'The following skills are available';

// Имена скиллов, вызванных в одной строке транскрипта.
function skillUsesOf(obj) {
  const content = obj && obj.message && obj.message.content;
  if (!Array.isArray(content)) return [];
  return content
    .filter(b => b && b.type === 'tool_use' && b.name === 'Skill' && b.input && b.input.skill)
    .map(b => b.input.skill);
}

// Листинг скиллов из системного промпта → длина описания каждого.
// Строка «- имя: описание» начинает скилл, продолжение идёт в него же.
function listingSkills(text) {
  const rows = [];
  let cur = null;
  for (const line of text.split('\n')) {
    const m = line.match(/^- ([A-Za-z0-9_:./-]+):/);
    if (m) {
      cur = { name: m[1], chars: 0, plugin: m[1].includes(':') };
      rows.push(cur);
    }
    if (cur) cur.chars += line.length + 1;
  }
  return rows;
}

// Ход владельца закрывает отрезок скилла. Критерий тот же, что в
// session-cost.js: служебные записи ходят тем же типом `user` — результат
// инструмента (им возвращается и сам скилл), впрыск хука, сводка сжатия,
// уведомление о готовности сабагента.
const NOT_OWNER = /^(<task-notification|<scheduled-wakeup|<background-task|\[Request interrupted)/;
function isOwnerTurn(o) {
  if (!o || o.type !== 'user' || o.isMeta || o.isSidechain || o.isCompactSummary) return false;
  const c = o.message && o.message.content;
  if (Array.isArray(c)) {
    if (c.some(b => b && b.type === 'tool_result')) return false;
    const text = (c.find(b => b && b.type === 'text') || {}).text || '';
    return !NOT_OWNER.test(text);
  }
  return !NOT_OWNER.test(typeof c === 'string' ? c : '');
}

// Отрезок скилла — от вызова Skill до сообщения владельца или до следующего
// вызова. Ход с самим вызовом скиллу не приписывается: решение позвать его
// принято до того, как текст скилла попал в контекст.
function attributeTurns(objects, since) {
  const rows = new Map();
  const seen = new Set();
  let cur = null;
  for (const o of objects) {
    if (isOwnerTurn(o)) { cur = null; continue; }
    const names = skillUsesOf(o);
    const u = o && o.message && o.message.usage;
    // Отрезок размечается по всем строкам файла, а деньги и вызовы считаются
    // только внутри периода: фильтр по дню на чтении рвал отрезок, начатый до
    // --since, и его ходы становились ничьими.
    const day = ((o && o.timestamp) || '').slice(0, 10);
    const inRange = !since || !day || day >= since;
    // Ход приходит несколькими строками — текст и каждый инструмент отдельно,
    // requestId и usage у них общие. Платим за него один раз.
    const fresh = u && !seen.has(o.requestId);
    if (u) seen.add(o.requestId);
    if (!names.length) {
      if (cur && fresh && inRange) cur.turns.push({ model: normModel(o.message.model), usage: u });
      continue;
    }
    for (const name of names) {
      let row = rows.get(name);
      if (!row) rows.set(name, row = { skill: name, calls: 0, turns: [] });
      if (inRange) row.calls += 1;
      cur = row;
    }
  }
  return [...rows.values()].filter(r => r.calls || r.turns.length);
}

// Цена хода. session-cost.js считает то же самое, но это CLI-скрипт без
// обёртки require.main: подключить его — значит запустить.
function turnCost(model, u) {
  const pr = PRICE[model];
  if (!pr || !u) return 0;
  const cc = u.cache_creation;
  const cw1h = (cc && cc.ephemeral_1h_input_tokens) || 0;
  const cw5 = cc ? (cc.ephemeral_5m_input_tokens || 0) : (u.cache_creation_input_tokens || 0);
  return ((u.input_tokens || 0) * pr.in
    + cw5 * pr.in * CACHE_WRITE['5m'] + cw1h * pr.in * CACHE_WRITE['1h']
    + (u.cache_read_input_tokens || 0) * pr.cr + (u.output_tokens || 0) * pr.out) / 1e6;
}
function homeProjects() {
  const home = process.env.USERPROFILE || process.env.HOME;
  return path.join(home, '.claude', 'projects');
}

function transcriptsUnder(dir) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...transcriptsUnder(p));
    else if (e.name.endsWith('.jsonl')) out.push(p);
  }
  return out;
}

async function eachLine(file, fn) {
  const rl = readline.createInterface({ input: fs.createReadStream(file), crlfDelay: Infinity });
  for await (const line of rl) fn(line);
}

async function reportUsage(since) {
  const root = homeProjects();
  const files = transcriptsUnder(root);
  const use = new Map();
  for (const f of files) {
    const project = path.relative(root, f).split(path.sep)[0];
    await eachLine(f, line => {
      if (!line.includes('"Skill"')) return;
      let o; try { o = JSON.parse(line); } catch { return; }
      const day = (o.timestamp || '').slice(0, 10);
      if (since && day && day < since) return;
      for (const name of skillUsesOf(o)) {
        const rec = use.get(name) || { n: 0, last: '', projects: new Set() };
        rec.n += 1;
        if (day > rec.last) rec.last = day;
        rec.projects.add(project);
        use.set(name, rec);
      }
    });
  }
  const rows = [...use.entries()].sort((a, b) => b[1].n - a[1].n);
  console.log(`Вызовы скиллов — ${files.length} транскриптов, ${rows.length} скиллов${since ? `, с ${since}` : ''}`);
  for (const [name, v] of rows) {
    console.log(`${String(v.n).padStart(5)}  ${v.last}  ${name}  (${v.projects.size} проектов)`);
  }
  if (!rows.length) console.log('  ни одного вызова');
}

// Расход по скиллам: сколько стоили ходы внутри их отрезков и какая это доля
// всех денег за период. Сабагенты сюда не входят — их ходы лежат отдельными
// файлами, разрез по типам агента даёт session-cost.js.
async function reportCost(since) {
  const root = homeProjects();
  const files = transcriptsUnder(root);
  // В памяти держатся только поля, нужные разметке: сессии бывают по сотне МБ.
  const slim = o => ({ type: o.type, isMeta: o.isMeta, isSidechain: o.isSidechain, timestamp: o.timestamp,
    isCompactSummary: o.isCompactSummary, requestId: o.requestId || o.uuid,
    message: { model: o.message && o.message.model, usage: o.message && o.message.usage,
      content: isOwnerTurn(o) ? [] : [{ type: 'tool_result' },
        ...skillUsesOf(o).map(skill => ({ type: 'tool_use', name: 'Skill', input: { skill } }))] } });
  const rows = new Map();
  let total = 0;
  for (const f of files) {
    const objs = [];
    const seen = new Set();
    await eachLine(f, line => {
      let o; try { o = JSON.parse(line); } catch { return; }
      const day = (o.timestamp || '').slice(0, 10);
      const u = o.message && o.message.usage;
      const id = o.requestId || o.uuid;
      if (u && !seen.has(id) && !(since && day && day < since)) {
        seen.add(id);
        total += turnCost(normModel(o.message.model), u);
      }
      objs.push(slim(o));
    });
    for (const r of attributeTurns(objs, since)) {
      const rec = rows.get(r.skill) || { calls: 0, cost: 0 };
      rec.calls += r.calls;
      rec.cost += r.turns.reduce((s, t) => s + turnCost(t.model, t.usage), 0);
      rows.set(r.skill, rec);
    }
  }
  const sorted = [...rows.entries()].sort((a, b) => b[1].cost - a[1].cost);
  const skills = sorted.reduce((s, [, v]) => s + v.cost, 0);
  const d = x => ('$' + x.toFixed(2)).padStart(8);
  const pct = x => ((total ? 100 * x / total : 0).toFixed(1) + '%').padStart(6);
  console.log(`Расход по скиллам — ${files.length} транскриптов${since ? `, с ${since}` : ''}`);
  for (const [name, v] of sorted) {
    const per = v.calls ? d(v.cost / v.calls) : '       —';
    console.log(`${d(v.cost)} ${pct(v.cost)} ${String(v.calls).padStart(4)} выз ${per}/выз  ${name}`);
  }
  if (!sorted.length) console.log('  ни одного вызова');
  console.log(`Всего за период ${d(total)}, на скиллы ${d(skills)} (${pct(skills).trim()}).`);
  console.log('Ходы сабагентов лежат отдельными файлами и в долю скилла не попали: session-cost.js.');
  console.log('Отрезок идёт до следующего слова владельца: если тот молчал весь прогон' +
    ' пакета, в долю скилла попала и работа после него (2026-09-18-subagent-templates-and-plan-cost.md).');
}

// Свежий снимок листинга берётся из последнего транскрипта текущего проекта:
// он собран уже с действующими skillOverrides.
async function reportListing() {
  const dir = projectDir(process.cwd());
  if (!dir) { console.error('Транскриптов этого проекта нет'); process.exitCode = 1; return; }
  const files = fs.readdirSync(dir).filter(f => f.endsWith('.jsonl')).map(f => path.join(dir, f))
    .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
  let text = null;
  for (const f of files) {
    await eachLine(f, line => {
      if (text || !line.includes(LISTING_HEAD)) return;
      let o; try { o = JSON.parse(line); } catch { return; }
      const found = findListing(o);
      if (found) text = found.slice(found.indexOf(LISTING_HEAD));
    });
    if (text) { console.log(`Снимок: ${path.basename(f)}`); break; }
  }
  if (!text) { console.error(`Листинг не найден в ${files.length} транскриптах`); process.exitCode = 1; return; }
  const rows = listingSkills(text).sort((a, b) => b.chars - a.chars);
  const sum = k => rows.filter(r => r.plugin === k).reduce((s, r) => s + r.chars, 0);
  for (const r of rows) console.log(`${String(r.chars).padStart(6)}  ${r.plugin ? 'плагин ' : 'встроен'}  ${r.name}`);
  console.log(`Всего ${text.length} знаков: плагины ${sum(true)}, встроенные ${sum(false)}`);
}

function findListing(value) {
  if (typeof value === 'string') return value.includes(LISTING_HEAD) ? value : null;
  if (Array.isArray(value)) {
    for (const v of value) { const f = findListing(v); if (f) return f; }
    return null;
  }
  if (value && typeof value === 'object') {
    for (const k of Object.keys(value)) { const f = findListing(value[k]); if (f) return f; }
  }
  return null;
}

if (require.main === module) {
  const args = process.argv.slice(2);
  const since = args.includes('--since') ? args[args.indexOf('--since') + 1] : null;
  const run = args.includes('--listing') ? reportListing()
    : args.includes('--cost') ? reportCost(since) : reportUsage(since);
  run.catch(e => {
    console.error(e.message);
    process.exitCode = 1;
  });
}

module.exports = { skillUsesOf, listingSkills, attributeTurns, turnCost };
