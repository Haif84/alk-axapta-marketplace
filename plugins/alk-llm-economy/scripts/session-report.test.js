/*
 * Тесты сборки HTML-отчёта: скрипт берёт JSON чужого analyze-sessions.mjs,
 * вставляет его в шаблон скилла session-report и заполняет два блока выводов
 * вычисленными фактами — без обращения к модели.
 * Запуск: node --test scripts/*.test.js
 */
const { test } = require('node:test');
const assert = require('node:assert');
const { execFileSync } = require('node:child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const SCRIPT = path.join(__dirname, 'session-report.js');

const TEMPLATE = [
  '<html><head>',
  '<link rel="preconnect" href="https://fonts.googleapis.com">',
  '<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono" rel="stylesheet">',
  '</head><body>',
  '<div id="takeaways">',
  '<!-- AGENT: anomalies -->',
  '<div class="take"><div class="fig">—</div><div class="txt">No findings generated yet.</div></div>',
  '<!-- /AGENT -->',
  '</div>',
  '<div id="recs">',
  '<!-- AGENT: optimizations -->',
  '<div class="callout">No suggestions generated yet.</div>',
  '<!-- /AGENT -->',
  '</div>',
  '<script id="report-data" type="application/json">{}</script>',
  '</body></html>',
].join('\n');

// Разрез анализатора: только те поля, которые читает отчёт.
const proj = (total, out) => ({
  sessions: 1, api_calls: 10,
  input_tokens: { uncached: total, cache_create: 0, cache_read: 0, total, pct_cached: 0 },
  output_tokens: out, human_messages: 1,
  hours: { wall_clock: 2, active: 1 },
  cache_breaks_over_100k: 0,
  subagent: { calls: 0, total_tokens: 0, avg_tokens_per_call: 0 },
  skill_invocations: 0, span: null,
});

function data(over) {
  const base = {
    root: '/projects', generated_at: '2026-09-16T09:00:00.000Z',
    overall: {
      sessions: 2, api_calls: 20,
      input_tokens: { uncached: 40000, cache_create: 10000, cache_read: 950000, total: 1000000, pct_cached: 95 },
      output_tokens: 20000, human_messages: 4,
      hours: { wall_clock: 4, active: 2 },
      cache_breaks_over_100k: 0,
      subagent: { calls: 2, total_tokens: 100000, avg_tokens_per_call: 50000 },
      skill_invocations: 3, span: null,
    },
    cache_breaks: [],
    by_project: { alpha: proj(750000, 0), beta: proj(250000, 0) },
    by_subagent_type: {}, by_skill: {},
    top_prompts: [{
      ts: '2026-09-16T09:05:00.000Z', project: 'alpha', session: 's1',
      text: 'самый дорогой ход', api_calls: 12, subagent_calls: 1,
      total_tokens: 600000, input: { uncached: 1000, cache_create: 0, cache_read: 599000 },
      output: 0, context: null,
    }],
    by_day: [],
  };
  return Object.assign(base, over);
}

// Поддельный маркетплейс: анализатор печатает готовый JSON, шаблон минимальный.
function fixture(json, opts) {
  const cfg = fs.mkdtempSync(path.join(os.tmpdir(), 'srp-'));
  const skill = path.join(cfg, 'plugins', 'marketplaces', 'fake',
    'plugins', 'session-report', 'skills', 'session-report');
  fs.mkdirSync(skill, { recursive: true });
  if (json) fs.writeFileSync(path.join(skill, 'analyze-sessions.mjs'),
    `process.stdout.write(${JSON.stringify(JSON.stringify(json))})\n`);
  if (json) fs.writeFileSync(path.join(skill, 'template.html'), opts === 'no-template' ? '' : TEMPLATE);
  if (opts === 'no-template') fs.unlinkSync(path.join(skill, 'template.html'));
  return cfg;
}

function run(cfg, ...flags) {
  const out = path.join(cfg, 'report.html');
  execFileSync(process.execPath, [SCRIPT, '-o', out, ...flags], {
    encoding: 'utf8', env: Object.assign({}, process.env, { CLAUDE_CONFIG_DIR: cfg }),
  });
  return fs.readFileSync(out, 'utf8');
}

const embedded = html => {
  const m = html.match(/<script id="report-data"[^>]*>([\s\S]*?)<\/script>/);
  assert.ok(m, 'в отчёте нет блока report-data:\n' + html);
  return JSON.parse(m[1]);
};

const block = (html, name) => {
  const m = html.match(new RegExp(`<!-- AGENT: ${name} -->([\\s\\S]*?)<!-- /AGENT -->`));
  assert.ok(m, `в отчёте нет блока ${name}`);
  return m[1];
};

test('встраивает JSON анализатора в report-data', () => {
  const html = run(fixture(data()));
  const got = embedded(html);
  assert.equal(got.overall.api_calls, 20);
  assert.equal(got.top_prompts[0].text, 'самый дорогой ход');
});

test('выводы считаются из данных, а не остаются заглушкой', () => {
  const b = block(run(fixture(data())), 'anomalies');
  assert.doesNotMatch(b, /No findings generated yet/, b);
  assert.match(b, /alpha/, b);
});

test('доля самого крупного проекта считается в процентах', () => {
  const b = block(run(fixture(data())), 'anomalies');
  assert.match(b, /75%/, b);
});

test('самый дорогой ход владельца попадает в выводы', () => {
  const b = block(run(fixture(data())), 'anomalies');
  assert.match(b, /самый дорогой ход/, b);
});

test('низкая доля кэша даёт рекомендацию, высокая — нет', () => {
  const low = data();
  low.overall.input_tokens.pct_cached = 70;
  assert.match(block(run(fixture(low)), 'optimizations'), /кэш/i);
  assert.doesNotMatch(block(run(fixture(data())), 'optimizations'), /доля кэш/i);
});

test('разрывы кэша дают рекомендацию с самым крупным из них', () => {
  const d = data();
  d.overall.cache_breaks_over_100k = 3;
  d.cache_breaks = [{ uncached: 180000, project: 'alpha', session: 's1', ts: '2026-09-16T09:10:00.000Z', context: null }];
  assert.match(block(run(fixture(d)), 'optimizations'), /Разрывов кэша 3;.+180 000 некэшированного/);
});

test('в готовом отчёте нет внешних ссылок', () => {
  const html = run(fixture(data()));
  assert.doesNotMatch(html, /(src|href)\s*=\s*["']https?:/i, 'отчёт тянет ресурс из сети');
});

test('закрывающий тег внутри данных не рвёт отчёт', () => {
  const d = data();
  d.top_prompts[0].text = 'посмотри </script><script>alert(1)</script>';
  const got = embedded(run(fixture(d)));
  assert.equal(got.top_prompts[0].text, 'посмотри </script><script>alert(1)</script>');
});

test('без шаблона в маркетплейсе падает с внятной ошибкой', () => {
  const cfg = fixture(data(), 'no-template');
  assert.throws(() => run(cfg), err => {
    const text = String(err.stderr || '') + String(err.stdout || '');
    assert.match(text, /template\.html/, text);
    return true;
  });
});
