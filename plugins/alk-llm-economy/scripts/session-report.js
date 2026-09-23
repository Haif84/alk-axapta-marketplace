#!/usr/bin/env node
/*
 * session-report.js — HTML-отчёт по транскриптам, собранный скриптом, а не
 * моделью: запускает чужой analyze-sessions.mjs из скилла session-report,
 * кладёт его JSON в <script id="report-data"> копии template.html и заполняет
 * два блока выводов вычисленными фактами. Ноль токенов, файл self-contained.
 *
 * Шаблон и анализатор берутся из зеркала маркетплейса по месту, в репозиторий
 * не копируются: версия плагина обновится — обновится и отчёт.
 *
 * Usage:
 *   node session-report.js -o report.html
 *   node session-report.js --since 7d -o report.html
 *   node session-report.js --dir <корень с проектами> -o r.html
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const args = process.argv.slice(2);
const flag = name => { const i = args.indexOf(name); return i < 0 ? null : args[i + 1]; };
const outFile = flag('-o') || flag('--out') || 'session-report.html';

const die = msg => { console.error(msg); process.exit(1); };

// Скилл живёт в зеркале маркетплейса; имя маркетплейса и версия плагина
// меняются, поэтому ищем перебором по всем установленным маркетплейсам.
function findSkill() {
  const cfg = process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), '.claude');
  const root = path.join(cfg, 'plugins', 'marketplaces');
  let names = [];
  try { names = fs.readdirSync(root); } catch { names = []; }
  for (const name of names) {
    const dir = path.join(root, name, 'plugins', 'session-report', 'skills', 'session-report');
    if (fs.existsSync(path.join(dir, 'template.html'))
      && fs.existsSync(path.join(dir, 'analyze-sessions.mjs'))) return dir;
  }
  die(`не найден скилл session-report: нет ${root}/*/plugins/session-report/`
    + `skills/session-report/{analyze-sessions.mjs,template.html}.\n`
    + 'Плагин session-report ставится из маркетплейса claude-plugins-official.');
}

function analyze(skill) {
  const argv = [path.join(skill, 'analyze-sessions.mjs'), '--json'];
  const since = flag('--since'), dir = flag('--dir');
  if (since) argv.push('--since', since);
  if (dir) argv.push('--dir', dir);
  const raw = execFileSync(process.execPath, argv, { encoding: 'utf8', maxBuffer: 256 << 20 });
  try { return JSON.parse(raw); } catch { return die('analyze-sessions.mjs вернул не JSON'); }
}

const tok = x => (x >= 1e6 ? (x / 1e6).toFixed(1) + 'M' : Math.round(x / 1000) + 'k');
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const num = x => String(x).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
const cut = (s, n) => (s.length > n ? s.slice(0, n) + '…' : s);
const total = s => s.input_tokens.total + s.output_tokens;

// Наблюдения: то, что видно из цифр без домыслов. Класс — оценка порогом.
function anomalies(d) {
  const o = d.overall, takes = [];
  const take = (cls, fig, txt) =>
    takes.push(`<div class="take ${cls}"><div class="fig">${esc(fig)}</div>`
      + `<div class="txt">${txt}</div></div>`);

  const projects = Object.entries(d.by_project || {}).sort((a, b) => total(b[1]) - total(a[1]));
  const all = projects.reduce((s, [, v]) => s + total(v), 0);
  if (projects.length && all) {
    const [name, v] = projects[0];
    take('info', Math.round((100 * total(v)) / all) + '%',
      `токенов ушло на проект <b>${esc(name)}</b> — ${tok(total(v))} из ${tok(all)} `
      + `по ${projects.length} проектам`);
  }

  const pct = o.input_tokens.pct_cached;
  take(pct >= 90 ? 'good' : pct >= 80 ? 'info' : 'bad', pct + '%',
    `входа прочитано из кэша; некэшированного входа ${tok(o.input_tokens.uncached)}, `
    + `записи в кэш ${tok(o.input_tokens.cache_create)}`);

  const top = (d.top_prompts || [])[0];
  if (top) take('info', tok(top.total_tokens),
    `самый дорогой ход владельца: «${esc(cut(top.text || '', 80))}» — `
    + `${top.api_calls} запросов, из них сабагентских ${top.subagent_calls}`);

  const breaks = o.cache_breaks_over_100k;
  take(breaks ? 'bad' : 'good', String(breaks),
    'разрывов кэша больше 100k токенов: столько раз контекст собирался заново');

  const wall = o.hours.wall_clock;
  if (wall) take('info', Math.round((100 * o.hours.active) / wall) + '%',
    `времени сессий было активным: ${o.hours.active} ч работы из ${wall} ч по часам, `
    + `${o.human_messages} сообщений владельца`);

  return takes.slice(0, 5).join('\n');
}

// Рекомендации срабатывают по порогам, а не по вкусу: не сработал ни один —
// так и написано, пустой совет не выдумывается.
function optimizations(d) {
  const o = d.overall, recs = [];
  const rec = text => recs.push(`<div class="callout">${text}</div>`);

  const pct = o.input_tokens.pct_cached;
  if (pct < 90) rec(`Доля кэша ${pct}% при норме 90%+. Кэш рвут правка CLAUDE.md `
    + 'посреди сессии, пауза больше часа и смена модели или effort: держать их '
    + 'на границах сессии.');

  const breaks = o.cache_breaks_over_100k;
  if (breaks) {
    const b = (d.cache_breaks || [])[0];
    rec(`Разрывов кэша ${breaks}` + (b
      ? `; самый крупный — ${num(b.uncached)} `
        + `некэшированного входа в проекте ${esc(b.project || '?')}`
      : '') + '. Каждый разрыв заново оплачивает весь контекст.');
  }

  if (o.subagent.calls && o.subagent.avg_tokens_per_call > 200000)
    rec(`Сабагент тянет в среднем ${tok(o.subagent.avg_tokens_per_call)} токенов за вызов `
      + `(${o.subagent.calls} вызовов). Давать ему узкую задачу и явные файлы, а не поиск по репозиторию.`);

  if (o.human_messages && o.api_calls / o.human_messages > 40)
    rec(`На одно сообщение владельца приходится ${Math.round(o.api_calls / o.human_messages)} `
      + 'запросов к модели. Длинные автономные ходы дороже: резать задачу на куски с проверкой.');

  if (!recs.length) rec('Пороги не превышены: кэш держится, разрывов нет, '
    + 'сабагенты и длина ходов в норме.');
  return recs.join('\n');
}

const putBlock = (html, name, body) => html.replace(
  new RegExp(`(<!-- AGENT: ${name} -->)[\\s\\S]*?(<!-- /AGENT -->)`),
  (_, a, b) => `${a}\n${body}\n${b}`);

function build(template, d) {
  // Шаблон тянет JetBrains Mono из Google Fonts. Отчёт должен открываться
  // без сети и никуда не ходить, а в CSS уже есть запасная цепочка
  // моноширинных, поэтому внешние <link> вырезаются.
  template = template.replace(/[ \t]*<link\b[^>]*\bhttps?:[^>]*>\r?\n?/gi, '');
  // < внутри JSON экранируется: иначе «</script>» в тексте промпта закрывает
  // блок данных, а «<!--» превращает его в комментарий.
  const json = JSON.stringify(d).replace(/</g, '\\u003c');
  let html = template.replace(
    /(<script id="report-data"[^>]*>)[\s\S]*?(<\/script>)/,
    (_, a, b) => a + json + b);
  html = putBlock(html, 'anomalies', anomalies(d));
  html = putBlock(html, 'optimizations', optimizations(d));
  return html;
}

const skill = findSkill();
const data = analyze(skill);
fs.writeFileSync(outFile, build(fs.readFileSync(path.join(skill, 'template.html'), 'utf8'), data));
const o = data.overall;
console.log(`${path.resolve(outFile)}\n  сессий ${o.sessions}, запросов ${o.api_calls}, `
  + `вход ${tok(o.input_tokens.total)} (кэш ${o.input_tokens.pct_cached}%), выход ${tok(o.output_tokens)}`);
