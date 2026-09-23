#!/usr/bin/env node
/*
 * handoff-from-transcript.js — выжимка из транскрипта закрытой сессии.
 *
 * Если сессия закрылась без `/remember`, структурированного handoff не
 * остаётся. Скрипт собирает из `.jsonl` текстовую часть диалога (реплики
 * владельца, текст ассистента, вызовы инструментов одной строкой) — её
 * скармливают сабагенту на Haiku, чтобы тот написал handoff. Сырой транскрипт
 * в окно не лезет (мегабайты), выжимка — единицы тысяч токенов.
 *
 * Использование:
 *   node handoff-from-transcript.js                # список последних сессий
 *   node handoff-from-transcript.js 1              # выжимка сессии #1 из списка
 *   node handoff-from-transcript.js <uuid|файл>    # выжимка конкретной сессии
 *   node handoff-from-transcript.js --dir <папка>  # транскрипты другого проекта
 *
 * Выжимка пишется в %TEMP%\claude\handoff-<uuid8>.md, в stdout — только путь.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const { projectDir, listSessions } = require('./transcripts');

const LIST_SIZE = 5;

const args = process.argv.slice(2);
const dirIdx = args.indexOf('--dir');
const dirArg = dirIdx >= 0 ? args[dirIdx + 1] : null;
// Значение --dir — не цель: пропускаем именно его позицию, а не позицию 0.
const target = args.find((a, i) => !a.startsWith('--') && !(dirIdx >= 0 && i === dirIdx + 1));

function die(msg) { console.error(msg); process.exit(1); }

function records(file) {
  return fs.readFileSync(file, 'utf8').split('\n').filter(Boolean)
    .map(l => { try { return JSON.parse(l); } catch { return null; } })
    .filter(Boolean)
    // Сабагенты — своя ветка диалога, в handoff их шум не нужен.
    .filter(o => !o.isSidechain);
}

const blocks = o => Array.isArray(o.message && o.message.content) ? o.message.content : [];

// Реплика владельца: текст, который он набрал сам. Вставки скиллов и хуков
// приходят тем же типом с isMeta, результаты инструментов — с toolUseResult.
function userText(o) {
  if (o.type !== 'user' || o.isMeta || o.toolUseResult) return null;
  const t = blocks(o).filter(b => b.type === 'text').map(b => b.text).join('\n').trim();
  return t || null;
}

// В транскрипте время в UTC, а читает выжимку владелец — переводим в местное.
const local = o => o.timestamp ? new Date(o.timestamp) : null;
const time = o => { const d = local(o); return d ? d.toTimeString().slice(0, 5) : '?'; };
const day = o => { const d = local(o); return d ? d.toLocaleDateString('sv') : '?'; };
const when = t => (t ? day({ timestamp: t }) + ' ' + time({ timestamp: t }) : '?');

// Вызов инструмента — одной строкой: чем он был, а не с каким аргументом.
function toolLine(b) {
  const i = b.input || {};
  const what = i.description || i.file_path || i.path || i.pattern || i.prompt || i.skill
    || (typeof i.command === 'string' ? i.command : '');
  return `- ${b.name}${what ? ': ' + String(what).split('\n')[0].slice(0, 120) : ''}`;
}

function digest(file) {
  const recs = records(file);
  const uuid = path.basename(file, '.jsonl');
  const stamps = recs.map(o => o.timestamp).filter(Boolean).sort();
  const out = [`# Транскрипт сессии ${uuid}`, '',
    `Окно: ${when(stamps[0])} — ${when(stamps[stamps.length - 1])}`, ''];

  // Ходы ассистента между репликами владельца идут одним блоком: отдельный
  // заголовок на каждый вызов инструмента — шум, которого в выжимке быть не должно.
  let turn = null;
  const flush = () => { if (turn) out.push(`## ${turn.at} ассистент`, '', turn.lines.join('\n'), ''); turn = null; };

  for (const o of recs) {
    const ut = userText(o);
    if (ut) { flush(); out.push(`## ${time(o)} владелец`, '', ut, ''); continue; }
    if (o.type !== 'assistant') continue;
    const lines = [];
    for (const b of blocks(o)) {
      // thinking в транскрипт пишется без содержимого (только подпись) — мимо.
      if (b.type === 'text' && b.text.trim()) lines.push(b.text.trim());
      if (b.type === 'tool_use') lines.push(toolLine(b));
    }
    if (!lines.length) continue;
    if (!turn) turn = { at: time(o), lines };
    else turn.lines.push(...lines);
  }
  flush();

  const log = gitLog(stamps[0], stamps[stamps.length - 1]);
  if (log) out.push('## Коммиты за окно сессии', '', '```', log, '```', '');
  return out.join('\n');
}

// Что менялось на диске, выжимка не знает — вывод инструментов в неё не входит.
// Коммиты за окно сессии закрывают этот пробел, если проект под git.
function gitLog(from, to) {
  if (!from) return '';
  try {
    return execFileSync('git', ['log', '--oneline', '--since', from, '--until', to || from],
      { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
  } catch { return ''; }
}

// Пометка handoff: был ли в сессии /remember и уцелел ли он в remember.md.
// Плагин remember держит один remember.md на проект, и второй /remember из
// другой сессии молча затирает первый.
function rememberMark(file) {
  const recs = records(file);
  const stamp = recs.filter(o => (userText(o) || '').includes('/remember'))
    .map(o => o.timestamp).pop();
  if (!stamp) return '✗ без /remember';
  const md = path.join(process.cwd(), '.remember', 'remember.md');
  if (!fs.existsSync(md)) return '⟳ /remember был, remember.md нет';
  // remember.md принадлежит этой сессии, если записан между вызовом /remember
  // и концом сессии: скилл пишет файл не мгновенно, а работа после него
  // продолжается. Запись позже конца сессии — чужая, handoff затёрт.
  const last = recs.map(o => o.timestamp).filter(Boolean).sort().pop();
  const mtime = +fs.statSync(md).mtime;
  const mine = mtime >= +new Date(stamp) - 60e3 && mtime <= +new Date(last) + 15 * 60e3;
  return mine ? `✓ /remember ${time({ timestamp: stamp })}`
    : '⟳ /remember затёрт другой сессией';
}

function list(dir) {
  const sessions = listSessions(dir).slice(-LIST_SIZE).reverse();
  if (!sessions.length) die('В папке нет транскриптов: ' + dir);
  sessions.forEach((s, i) => {
    const recs = records(s.file);
    const prompts = recs.filter(o => userText(o)).length;
    const first = recs.find(o => o.timestamp);
    const date = first ? day(first) + ' ' + time(first) : '?';
    console.log(`#${i + 1}  ${path.basename(s.file, '.jsonl')}  ${date}—${time(recs.filter(o => o.timestamp).pop() || {})}`
      + `  ${String(prompts).padStart(3)} реплик  ${(s.size / 1048576).toFixed(1)} МБ  ${rememberMark(s.file)}`);
  });
}

function resolve(dir, arg) {
  if (arg.endsWith('.jsonl')) {
    if (!fs.existsSync(arg)) die('Файл не найден: ' + arg);
    return arg;
  }
  const sessions = listSessions(dir).slice(-LIST_SIZE).reverse();
  if (/^\d+$/.test(arg)) {
    const s = sessions[Number(arg) - 1];
    if (!s) die(`Сессия #${arg} не найдена: в списке ${sessions.length}`);
    return s.file;
  }
  const byUuid = path.join(dir, arg + '.jsonl');
  if (!fs.existsSync(byUuid)) die('Сессия не найдена: ' + arg);
  return byUuid;
}

let dir;
try { dir = dirArg || projectDir(); } catch (e) { die(e.message); }
if (!fs.existsSync(dir)) die('Папка транскриптов не найдена: ' + dir);

if (!target) {
  list(dir);
} else {
  const file = resolve(dir, target);
  const outDir = path.join(os.tmpdir(), 'claude');
  fs.mkdirSync(outDir, { recursive: true });
  const out = path.join(outDir, 'handoff-' + path.basename(file, '.jsonl').slice(0, 8) + '.md');
  fs.writeFileSync(out, digest(file), 'utf8');
  console.log(out);
}
