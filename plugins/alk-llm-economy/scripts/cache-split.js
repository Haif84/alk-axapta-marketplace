#!/usr/bin/env node
/*
 * cache-split.js — из чего складывается плата: записи кэша, чтения, вывод.
 *
 * session-cost.js отвечает «сколько стоила сессия». Этот скрипт отвечает
 * «куда ушли деньги» по всем проектам сразу: доля записей в кэш (часовых и
 * пятиминутных), чтений и вывода, и распределение TTL по моделям. Нужен для
 * калибровки правил в global/CLAUDE.md — спорить о TTL и паузах без этих
 * чисел бессмысленно.
 *
 * Использование:
 *   node cache-split.js                 # за последнюю неделю
 *   node cache-split.js 2026-09-12      # сессии, изменённые с даты
 *
 * Прайс и коэффициенты записи кэша — в `prices.js`, общие с `session-cost.js`.
 */
const fs = require('fs');
const path = require('path');

const { PRICE, normModel, CACHE_WRITE } = require('./prices');

const since = new Date(process.argv[2] || Date.now() - 7 * 864e5);  // без даты — последняя неделя
const root = path.join(process.env.USERPROFILE || process.env.HOME, '.claude', 'projects');

const tok = { in: 0, cw5: 0, cw1h: 0, cr: 0, out: 0 };
const usd = { in: 0, cw5: 0, cw1h: 0, cr: 0, out: 0 };
const perModel = {};

function walk(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) { walk(p); continue; }
    if (!e.name.endsWith('.jsonl') || fs.statSync(p).mtime < since) continue;
    const sub = /subagents/.test(p);
    const seen = new Set();            // один запрос пишется несколькими строками
    for (const line of fs.readFileSync(p, 'utf8').split('\n')) {
      if (!line.trim()) continue;
      let j; try { j = JSON.parse(line); } catch { continue; }
      const msg = j.message;
      if (!msg || !msg.usage) continue;
      const id = j.requestId || msg.id;
      if (id) { if (seen.has(id)) continue; seen.add(id); }
      const u = msg.usage, m = normModel(msg.model || ''), pr = PRICE[m];
      if (!pr) continue;
      const cc = u.cache_creation;
      const v = {
        in: u.input_tokens || 0,
        cw1h: (cc && cc.ephemeral_1h_input_tokens) || 0,
        cw5: cc ? (cc.ephemeral_5m_input_tokens || 0) : (u.cache_creation_input_tokens || 0),
        cr: u.cache_read_input_tokens || 0,
        out: u.output_tokens || 0,
      };
      for (const k of Object.keys(v)) tok[k] += v[k];
      usd.in += v.in * pr.in / 1e6;
      usd.cw5 += v.cw5 * pr.in * CACHE_WRITE['5m'] / 1e6;
      usd.cw1h += v.cw1h * pr.in * CACHE_WRITE['1h'] / 1e6;
      usd.cr += v.cr * pr.cr / 1e6;
      usd.out += v.out * pr.out / 1e6;
      const key = m + (sub ? ' [sub]' : '');
      const t = perModel[key] || (perModel[key] = { cw1h: 0, cw5: 0 });
      t.cw1h += v.cw1h; t.cw5 += v.cw5;
    }
  }
}

walk(root);

const total = Object.values(usd).reduce((a, b) => a + b, 0);
const pct = x => (total ? (100 * x / total).toFixed(1) : '0.0') + ' %';
const share = t => (100 * t.cw1h / ((t.cw1h + t.cw5) || 1)).toFixed(0) + ' %';

console.log(`с ${since.toISOString().slice(0, 10)}: всего $${total.toFixed(2)}`);
const NAME = { in: 'вход', cw5: 'запись 5m', cw1h: 'запись 1h', cr: 'чтение кэша', out: 'вывод' };
for (const k of ['in', 'cw5', 'cw1h', 'cr', 'out'])
  console.log(`  ${NAME[k].padEnd(12)} ${(tok[k] / 1e6).toFixed(1).padStart(6)}M  $${usd[k].toFixed(2).padStart(8)}  ${pct(usd[k])}`);
console.log(`  записи всего  $${(usd.cw5 + usd.cw1h).toFixed(2)}  ${pct(usd.cw5 + usd.cw1h)}`);
console.log(`  если бы все записи были 5m: $${(total - usd.cw1h / 2 * 0.75).toFixed(2)} (оценка сверху, без перезаписей; точный счёт — cost-structure.js --ttl)`);

console.log('\nдоля часового TTL в записях, по моделям:');
for (const [k, v] of Object.entries(perModel).sort())
  if (v.cw1h + v.cw5 > 0)
    console.log(`  ${k.padEnd(26)} 1h ${(v.cw1h / 1e6).toFixed(2)}M  5m ${(v.cw5 / 1e6).toFixed(2)}M  → ${share(v)}`);
