#!/usr/bin/env node
/*
 * cost-structure.js — из чего сложился расход: чтение кэша, запись, выход,
 * и как чтение распределено по размеру контекста хода.
 *
 * session-cost.js отвечает «сколько», этот скрипт — «за что»: скиллы и модели
 * лежат внутри тех же денег, а рычаг виден только в разрезе по размеру
 * контекста (замер 2026-09-18: 40 % платы за чтение — ходы свыше 100k).
 *
 *   node scripts/cost-structure.js [--since <дата>]   — структура расхода
 *   node scripts/cost-structure.js --ttl [--since …]  — контрфакт promptCacheTtl
 */
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const { PRICE, normModel, CACHE_WRITE } = require('./prices');

const EDGES = [20e3, 40e3, 60e3, 80e3, 100e3];
const BUCKETS = ['0–20k', '20–40k', '40–60k', '60–80k', '80–100k', '100k+'];
const bucketOf = read => BUCKETS[EDGES.findIndex(e => read < e)] || BUCKETS[BUCKETS.length - 1];

// Запись кэша: в usage она разложена по TTL, старые ходы отдают одним полем —
// такие считаем пятиминутными, это нижняя оценка.
function writeTokens(u) {
  const cc = (u && u.cache_creation) || null;
  return {
    m5: cc ? (cc.ephemeral_5m_input_tokens || 0) : ((u && u.cache_creation_input_tokens) || 0),
    h1: (cc && cc.ephemeral_1h_input_tokens) || 0,
  };
}

function writeCost(model, u) {
  const pr = PRICE[normModel(model)];
  if (!pr || !u) return 0;
  const { m5, h1 } = writeTokens(u);
  return (m5 * pr.in * CACHE_WRITE['5m'] + h1 * pr.in * CACHE_WRITE['1h']) / 1e6;
}

// Что стоила бы та же запись при promptCacheTtl: "5m". Часовая запись дешевеет
// до ×1.25, но истёкший разрыв заставляет переписать весь префикс заново —
// его размер равен тому, что этот ход прочитал из кэша.
function ttlAlternative(model, u, expired) {
  const pr = PRICE[normModel(model)];
  if (!pr || !u) return 0;
  const { m5, h1 } = writeTokens(u);
  const rewrite = expired ? (u.cache_read_input_tokens || 0) : 0;
  return ((m5 + h1 + rewrite) * pr.in * CACHE_WRITE['5m']) / 1e6;
}

function parts(model, u) {
  const pr = PRICE[normModel(model)];
  if (!pr || !u) return null;
  return {
    in: (u.input_tokens || 0) * pr.in / 1e6,
    read: (u.cache_read_input_tokens || 0) * pr.cr / 1e6,
    write: writeCost(model, u),
    out: (u.output_tokens || 0) * pr.out / 1e6,
  };
}

function homeProjects() {
  return path.join(process.env.USERPROFILE || process.env.HOME, '.claude', 'projects');
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

// Ходы одного файла по порядку: {model, usage, ts, sub}. Ход приходит
// несколькими строками с общим requestId — платим за него один раз.
async function turnsOf(file, since) {
  const sub = file.includes(`${path.sep}subagents${path.sep}`);
  const seen = new Set();
  const turns = [];
  const rl = readline.createInterface({ input: fs.createReadStream(file), crlfDelay: Infinity });
  for await (const line of rl) {
    if (!line.includes('"usage"')) continue;
    let o; try { o = JSON.parse(line); } catch { continue; }
    const u = o.message && o.message.usage;
    const id = o.requestId || o.uuid;
    if (!u || seen.has(id)) continue;
    seen.add(id);
    const day = (o.timestamp || '').slice(0, 10);
    if (since && day && day < since) continue;
    turns.push({ model: o.message.model, usage: u, ts: Date.parse(o.timestamp) || 0, sub });
  }
  return turns;
}

const d = x => ('$' + x.toFixed(2)).padStart(9);

async function report(since, ttlMode) {
  const files = transcriptsUnder(homeProjects());
  const sum = { in: 0, read: 0, write: 0, out: 0 };
  const buckets = new Map(BUCKETS.map(b => [b, { cost: 0, turns: 0, driver: 0, driverCost: 0 }]));
  let alt = 0, gaps = 0, expiredGaps = 0, turns = 0;
  for (const f of files) {
    const rows = await turnsOf(f, since);
    let prev = null;
    for (const t of rows) {
      const p = parts(t.model, t.usage);
      if (!p) continue;
      turns += 1;
      for (const k of Object.keys(sum)) sum[k] += p[k];
      const b = buckets.get(bucketOf(t.usage.cache_read_input_tokens || 0));
      b.cost += p.read; b.turns += 1;
      if (!t.sub) { b.driver += 1; b.driverCost += p.read; }
      // Разрыв меряется между соседними оплаченными ходами файла: именно
      // столько кэш простаивал до следующего чтения префикса.
      const expired = prev !== null && t.ts - prev > 5 * 60 * 1000;
      if (prev !== null) { gaps += 1; if (expired) expiredGaps += 1; }
      alt += ttlAlternative(t.model, t.usage, expired);
      prev = t.ts;
    }
  }
  const total = sum.in + sum.read + sum.write + sum.out;
  const pct = x => ((total ? 100 * x / total : 0).toFixed(1) + '%').padStart(6);
  console.log(`Структура расхода — ${files.length} транскриптов, ${turns} ходов${since ? `, с ${since}` : ''}`);
  if (ttlMode) {
    console.log(`Запись кэша как есть (promptCacheTtl 1h) ${d(sum.write)}`);
    console.log(`То же при 5m                             ${d(alt)}`);
    console.log(`Разрывов между ходами ${gaps}, из них длиннее пяти минут ${expiredGaps}`);
    console.log(alt > sum.write ? 'Часовой кэш дешевле: короткие разрывы берут своё.'
      : 'Пятиминутный кэш дешевле: длинные разрывы гасят экономию.');
    return;
  }
  console.log(`Вход без кэша ${d(sum.in)} ${pct(sum.in)}`);
  console.log(`Чтение кэша   ${d(sum.read)} ${pct(sum.read)}`);
  console.log(`Запись кэша   ${d(sum.write)} ${pct(sum.write)}`);
  console.log(`Выход         ${d(sum.out)} ${pct(sum.out)}`);
  console.log(`Всего         ${d(total)}`);
  console.log('\nЧтение кэша по размеру контекста хода:');
  const read = sum.read;
  for (const b of BUCKETS) {
    const v = buckets.get(b);
    const share = ((read ? 100 * v.cost / read : 0).toFixed(1) + '%').padStart(6);
    console.log(`${b.padEnd(8)} ${d(v.cost)} ${share} ${String(v.turns).padStart(5)} ходов, из них водителя ${String(v.driver).padStart(5)} на ${d(v.driverCost)}`);
  }
}

if (require.main === module) {
  const args = process.argv.slice(2);
  const since = args.includes('--since') ? args[args.indexOf('--since') + 1] : null;
  report(since, args.includes('--ttl')).catch(e => { console.error(e.message); process.exitCode = 1; });
}

module.exports = { bucketOf, writeCost, ttlAlternative, BUCKETS };
