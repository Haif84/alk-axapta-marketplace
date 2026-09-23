#!/usr/bin/env node
/*
 * context-composition.js — из чего состоит контекст сессий Claude Code.
 *
 * session-cost.js отвечает на вопрос «сколько заплачено», этот скрипт —
 * «за что»: какие части транскрипта занимают место, какие инструменты его
 * набивают и какие сессии выходят за бюджет контекста.
 *
 * Меряются символы записанного транскрипта, а не токены, помноженные на
 * число ходов: точной цены части отсюда не выйдет, но видно, что растёт.
 */

const fs = require('fs');
const path = require('path');

const { projectDirs, listSessions } = require('./transcripts');

// Записи CLI, которые лежат в транскрипте, но в запрос к API не уходят:
// в долях состава они только испортили бы проценты.
const CLI_ONLY = new Set(['file-history-snapshot', 'file-history-delta',
  'queue-operation', 'bridge-session', 'atis-latch', 'last-prompt', 'system']);

// Длина вложения — сколько текста оно впрыснуло в контекст. Весь объект мерить
// нельзя: у хука текст лежит и в `content`, и в `stdout`, да ещё с экранированием
// переводов строк, и статья завышается в разы (замер 2026-09-14: 428k против 176k).
function attachChars(a) {
  if (!a || typeof a !== 'object') return JSON.stringify(a || '').length;
  if (typeof a.content === 'string' && a.content) return a.content.length;
  if (typeof a.text === 'string') return a.text.length;
  if (typeof a.stdout === 'string' && a.stdout) {
    // Хук отдаёт впрыск полем `hookSpecificOutput.additionalContext`;
    // если вывод не JSON, впрыскивается он сам.
    try {
      const ctx = JSON.parse(a.stdout).hookSpecificOutput;
      if (ctx && typeof ctx.additionalContext === 'string') return ctx.additionalContext.length;
    } catch { /* не JSON */ }
    return a.stdout.length;
  }
  return JSON.stringify(a).length;
}

// Части одной строки транскрипта: [{part, chars, tool?}].
// Ход ассистента делится по элементам content — думанье, текст и вызовы
// инструментов растут по-разному, и смешивать их незачем.
function partsOf(obj) {
  const len = x => JSON.stringify(x || '').length;
  if (!obj || CLI_ONLY.has(obj.type)) return [{ part: 'cli', chars: len(obj) }];
  if (obj.type === 'attachment') {
    const t = (obj.attachment && obj.attachment.type) || 'прочее';
    return [{ part: 'attach:' + t, chars: attachChars(obj.attachment) }];
  }
  const c = obj.message && obj.message.content;
  if (typeof c === 'string') return [{ part: obj.type === 'user' ? 'user' : 'assistant', chars: c.length }];
  if (!Array.isArray(c)) return [{ part: 'cli', chars: len(obj) }];
  return c.map(item => {
    const chars = len(item);
    if (item.type === 'tool_result') return { part: 'tool_result', chars };
    if (item.type === 'tool_use') return { part: 'tool_use', chars, tool: item.name };
    if (item.type === 'thinking') return { part: 'thinking', chars };
    return { part: obj.type === 'user' ? 'user' : 'assistant', chars };
  });
}

// Вид команды Bash: показывает, чем набит хвост. Первое слово врёт — команды
// начинаются с `cd проект &&`, а объём даёт чтение файла дальше по строке.
const READERS = [['sed -n', /\bsed\s+-n\b/], ['cat', /\bcat\b/], ['head', /\bhead\b/],
  ['tail', /\btail\b/], ['grep', /\bgrep\b/], ['rg', /\brg\b/]];

function bashKind(command) {
  const c = String(command || '');
  for (const [kind, re] of READERS) if (re.test(c)) return kind;
  // Не чтение — довольно первого слова первой команды, без `cd` в начале.
  return c.replace(/^\s*cd\s+\S+\s*&&\s*/, '').trim().split(/\s+/)[0] || '—';
}

// Свод по строкам одной сессии: части контекста, объём по инструментам,
// хвост крупных вызовов. tailMin — граница «крупного» в символах.
function scan(lines, { tailMin = 8000 } = {}) {
  const parts = {}, tools = {}, tail = { calls: 0, chars: 0, byKind: {} }, snapshots = [];
  const calls = new Map();  // tool_use_id → {tool, kind}
  const bump = (obj, key, chars) => {
    const t = obj[key] || (obj[key] = { calls: 0, chars: 0 });
    t.chars += chars; return t;
  };
  for (const o of lines) {
    for (const { part, chars } of partsOf(o)) {
      // Снимок системного промпта в транскрипт пишется при каждой его смене, а
      // платится один раз на ход: в долях состава он лишь размывает остальные.
      if (part === 'attach:prompt_snapshot') { snapshots.push(chars); continue; }
      parts[part] = (parts[part] || 0) + chars;
    }
    const c = o.message && o.message.content;
    if (!Array.isArray(c)) continue;
    for (const item of c) {
      if (item.type === 'tool_use') {
        // Вид команды берётся при вызове: у результата своей команды нет.
        const kind = item.name === 'Bash'
          ? bashKind(item.input && item.input.command) : item.name;
        calls.set(item.id, { tool: item.name, kind });
        bump(tools, item.name, 0).calls++;
      }
      if (item.type !== 'tool_result') continue;
      const chars = JSON.stringify(item).length;
      const call = calls.get(item.tool_use_id) || { tool: '—', kind: '—' };
      bump(tools, call.tool, chars);
      if (chars < tailMin) continue;
      tail.calls++; tail.chars += chars;
      bump(tail.byKind, call.kind, chars).calls++;
    }
  }
  return { parts, tools, tail, snapshots };
}

// Контекст хода — всё, за что платят на входе (как в session-cost.js).
// Строки одного запроса склеиваются по requestId, служебные строки CLI
// с моделью <synthetic> ходом не считаются.
function sessionStats(lines) {
  const byReq = new Map();
  for (const o of lines) {
    const m = o.message;
    if (!m || !m.usage || m.model === '<synthetic>') continue;
    const u = m.usage, cc = u.cache_creation;
    const ctx = (u.input_tokens || 0) + (u.cache_read_input_tokens || 0)
      + (cc ? (cc.ephemeral_5m_input_tokens || 0) + (cc.ephemeral_1h_input_tokens || 0)
            : (u.cache_creation_input_tokens || 0));
    byReq.set(o.requestId || o.uuid, { ctx, cr: u.cache_read_input_tokens || 0 });
  }
  const turns = [...byReq.values()];
  const sum = turns.reduce((n, t) => n + t.ctx, 0);
  return {
    turns: turns.length,
    avg: turns.length ? sum / turns.length : 0,
    first: turns.length ? turns[0].ctx : 0,
    cacheRead: turns.reduce((n, t) => n + t.cr, 0),
  };
}

// Бюджет контекста — 100k по правилам, красный порог хука 150k.
const BUCKETS = [['до 100k', 0, 100e3], ['100–150k', 100e3, 150e3], ['от 150k', 150e3, Infinity]];

const median = xs => {
  const s = [...xs].sort((a, b) => a - b);
  if (!s.length) return 0;
  const i = s.length >> 1;
  return s.length % 2 ? s[i] : (s[i - 1] + s[i]) / 2;
};

// Раскладка сессий по среднему контексту хода: видно, какая доля чтений кэша
// приходится на сессии сверх бюджета. Короткие сессии (открыл и закрыл) шумят.
function budget(sessions, { minTurns = 5 } = {}) {
  const main = sessions.filter(s => s.turns > minTurns);
  const crAll = main.reduce((n, s) => n + s.cacheRead, 0);
  const buckets = BUCKETS.map(([label, lo, hi]) => {
    const inB = main.filter(s => s.avg >= lo && s.avg < hi);
    const cacheRead = inB.reduce((n, s) => n + s.cacheRead, 0);
    return {
      label, sessions: inB.length,
      turns: inB.reduce((n, s) => n + s.turns, 0),
      cacheRead, crShare: crAll ? cacheRead / crAll : 0,
    };
  });
  return { buckets, base: median(main.map(s => s.first)), sessions: main.length };
}

// Строки транскрипта. Обрыв записи на последней строке — обычное дело,
// битую строку пропускаем, а не роняем замер.
function readLines(file) {
  const out = [];
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    if (!line.trim()) continue;
    try { out.push(JSON.parse(line)); } catch { /* обрыв записи */ }
  }
  return out;
}

// Все папки проектов: режим недельного аудита, когда важна картина целиком.
function globalDirs(home = process.env.USERPROFILE || process.env.HOME) {
  const root = path.join(home, '.claude', 'projects');
  return fs.readdirSync(root).map(d => path.join(root, d))
    .filter(d => fs.statSync(d).isDirectory());
}

// Транскрипты сабагентов лежат рядом с сессией: их вывод набивает тот же
// контекст, что и вывод водителя, и в составе он должен быть виден.
function subagentFiles(file) {
  const sub = path.join(path.dirname(file), path.basename(file, '.jsonl'), 'subagents');
  if (!fs.existsSync(sub)) return [];
  return fs.readdirSync(sub).filter(f => f.endsWith('.jsonl')).map(f => path.join(sub, f));
}

module.exports = { partsOf, bashKind, scan, sessionStats, budget, readLines, globalDirs };

function main() {
  const args = process.argv.slice(2);
  const has = f => args.includes(f);
  const val = (f, d) => (args.indexOf(f) >= 0 ? args[args.indexOf(f) + 1] : d);
  const sinceArg = val('--since', null);
  const since = sinceArg ? new Date(sinceArg) : null;
  const tailMin = Number(val('--tail', 8000));
  const flagVals = new Set([sinceArg, val('--tail', null)]);
  const explicit = args.find(a => !a.startsWith('--') && !flagVals.has(a));

  let files;
  if (explicit && fs.statSync(explicit).isFile()) files = [{ file: explicit }];
  else {
    let dirs;
    try { dirs = has('--global') ? globalDirs() : projectDirs(explicit || process.cwd()); }
    catch (e) { console.error(e.message); process.exit(1); }
    files = listSessions(dirs);
    if (since) files = files.filter(x => x.mtime >= since);
    else if (!has('--all') && !has('--global')) files = files.slice(-1);
  }

  const total = { parts: {}, tools: {}, tail: { calls: 0, chars: 0, byKind: {} }, snapshots: [] };
  const sessions = [];
  let calls = 0;
  for (const { file } of files) {
    const own = readLines(file);
    const lines = [...own, ...subagentFiles(file).flatMap(readLines)];
    const s = scan(lines, { tailMin });
    merge(total, s);
    calls += Object.values(s.tools).reduce((n, t) => n + t.calls, 0);
    // Ход сабагента живёт в своей сессии — в бюджет водителя он не входит.
    const st = sessionStats(own);
    if (st.turns) sessions.push(st);
  }
  print(total, budget(sessions), { files: files.length, calls, tailMin });
}

function merge(total, s) {
  for (const [k, v] of Object.entries(s.parts)) total.parts[k] = (total.parts[k] || 0) + v;
  for (const [k, v] of Object.entries(s.tools)) {
    const t = total.tools[k] || (total.tools[k] = { calls: 0, chars: 0 });
    t.calls += v.calls; t.chars += v.chars;
  }
  total.snapshots.push(...s.snapshots);
  total.tail.calls += s.tail.calls; total.tail.chars += s.tail.chars;
  for (const [k, v] of Object.entries(s.tail.byKind)) {
    const t = total.tail.byKind[k] || (total.tail.byKind[k] = { calls: 0, chars: 0 });
    t.calls += v.calls; t.chars += v.chars;
  }
}

const M = c => (c >= 1e6 ? (c / 1e6).toFixed(1) + 'M' : Math.round(c / 1000) + 'k').padStart(7);
const P = (a, b) => ((b ? (100 * a) / b : 0).toFixed(1) + '%').padStart(7);
const K = t => (t / 1000).toFixed(1) + 'k';

function print(total, b, { files, calls, tailMin }) {
  const entries = Object.entries(total.parts).filter(([k]) => k !== 'cli');
  const inCtx = entries.reduce((n, [, v]) => n + v, 0);
  console.log(`Состав контекста — ${files} сессий, ${M(inCtx).trim()} символов, ${calls} вызовов инструментов`);
  for (const [k, v] of entries.sort((a, b2) => b2[1] - a[1])) {
    if (v / inCtx < 0.002) continue;  // мелочь ниже 0.2 % только мешает читать
    console.log(`  ${k.padEnd(26)} ${M(v)} ${P(v, inCtx)}`);
  }
  if (total.parts.cli) console.log(`  ${'(служебное, не в контексте)'.padEnd(26)} ${M(total.parts.cli)}`);
  // Системный промпт и схемы инструментов — постоянный вес каждого хода;
  // в долях его нет, потому что он не накапливается, а повторяется.
  if (total.snapshots.length) {
    console.log(`  ${'(системный промпт)'.padEnd(26)} ${M(median(total.snapshots))} на ход, снимков ${total.snapshots.length}`);
  }

  console.log('\nИнструменты — объём результата');
  for (const [k, v] of Object.entries(total.tools).sort((a, b2) => b2[1].chars - a[1].chars).slice(0, 8)) {
    console.log(`  ${k.padEnd(26)} ${M(v.chars)} ${P(v.chars, inCtx)}  вызовов ${String(v.calls).padStart(5)}  в среднем ${M(v.chars / (v.calls || 1)).trim()}`);
  }

  console.log(`\nХвост — вызовы длиннее ${K(tailMin)} символов`);
  console.log(`  ${String(total.tail.calls).padStart(5)} вызовов ${P(total.tail.calls, calls)} дают ${M(total.tail.chars)} ${P(total.tail.chars, inCtx)} всего контекста`);
  for (const [k, v] of Object.entries(total.tail.byKind).sort((a, b2) => b2[1].chars - a[1].chars).slice(0, 6)) {
    console.log(`  ${k.padEnd(26)} ${M(v.chars)}  вызовов ${String(v.calls).padStart(5)}`);
  }

  console.log(`\nБюджет контекста — ${b.sessions} основных сессий, базовый контекст ${K(b.base)}`);
  for (const x of b.buckets) {
    console.log(`  ${x.label.padEnd(26)} сессий ${String(x.sessions).padStart(4)}  ходов ${String(x.turns).padStart(5)}  чтений кэша ${P(x.crShare, 1)}`);
  }
}

if (require.main === module) main();
