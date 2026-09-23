/*
 * Тесты подробной статистики session-cost.js: разбивка цены по статьям,
 * доля чтения кэша, ходы сабагентов, максимум контекста, web-инструменты,
 * длительность сессии. Запуск: node --test scripts/*.test.js
 */
const { test } = require('node:test');
const assert = require('node:assert');
const { execFileSync } = require('node:child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const SCRIPT = path.join(__dirname, 'session-cost.js');

function line(requestId, model, usage, extra) {
  return JSON.stringify(Object.assign({ requestId, message: { model, usage } }, extra));
}

function fixture(main, sub, agentType) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'scs-'));
  fs.writeFileSync(path.join(dir, 'sess.jsonl'), main.join('\n') + '\n');
  if (sub) {
    const sd = path.join(dir, 'sess', 'subagents');
    fs.mkdirSync(sd, { recursive: true });
    fs.writeFileSync(path.join(sd, 'agent-1.jsonl'), sub.join('\n') + '\n');
    if (agentType) fs.writeFileSync(path.join(sd, 'agent-1.meta.json'),
      JSON.stringify({ agentType, toolUseId: 'toolu_1' }));
  }
  return dir;
}

const run = dir => execFileSync(process.execPath, [SCRIPT, dir], { encoding: 'utf8' });

test('печатает цену по статьям, а не только итог', () => {
  // opus-5: вход 1M × $5, чтение 1M × $0.5, выход 100k × $25 = $5.00 / $0.50 / $2.50
  const out = run(fixture([line('r', 'claude-opus-5', {
    input_tokens: 1e6, cache_read_input_tokens: 1e6, output_tokens: 1e5,
  })]));
  assert.match(out, /вход\s+1 000 000\s+\$\s*5\.00/, out);
  assert.match(out, /чтение\s+1 000 000\s+\$\s*0\.50/, out);
  assert.match(out, /выход\s+100 000\s+\$\s*2\.50/, out);
});

test('печатает долю чтения кэша во входных токенах', () => {
  // вход 10k + чтение 90k → 90.0 %
  const out = run(fixture([line('r', 'claude-opus-5', {
    input_tokens: 10000, cache_read_input_tokens: 90000, output_tokens: 0,
  })]));
  assert.match(out, /кэш-чтение 90\.0%/, out);
});

test('разделяет ходы водителя и сабагентов', () => {
  const U = { input_tokens: 1000, cache_read_input_tokens: 0, output_tokens: 100 };
  const out = run(fixture(
    [line('r1', 'claude-opus-5', U), line('r2', 'claude-opus-5', U)],
    [line('r3', 'claude-opus-5', U)]
  ));
  assert.match(out, /водитель 2 \/ сабагенты 1/, out);
});

test('печатает максимальный контекст хода, а не только средний', () => {
  const out = run(fixture([
    line('r1', 'claude-opus-5', { input_tokens: 1000, cache_read_input_tokens: 49000, output_tokens: 0 }),
    line('r2', 'claude-opus-5', { input_tokens: 1000, cache_read_input_tokens: 149000, output_tokens: 0 }),
  ]));
  assert.match(out, /max\s+150\.0k/, out);
});

test('считает запросы web_search и web_fetch', () => {
  const out = run(fixture([line('r', 'claude-opus-5', {
    input_tokens: 100, output_tokens: 10,
    server_tool_use: { web_search_requests: 3, web_fetch_requests: 2 },
  })]));
  assert.match(out, /web: search 3\s+fetch 2/, out);
});

test('печатает длительность сессии по времени запросов', () => {
  const U = { input_tokens: 100, output_tokens: 10 };
  const out = run(fixture([
    line('r1', 'claude-opus-5', U, { timestamp: '2026-09-14T06:00:00.000Z' }),
    line('r2', 'claude-opus-5', U, { timestamp: '2026-09-14T07:30:00.000Z' }),
  ]));
  assert.match(out, /1ч 30м/, out);
});

test('печатает ветку и effort сессии', () => {
  const out = run(fixture([line('r', 'claude-opus-5', { input_tokens: 100, output_tokens: 10 },
    { gitBranch: 'feature-x', effort: 'high' })]));
  assert.match(out, /feature-x/, out);
  assert.match(out, /effort high/, out);
});

test('доля думанья в выходе', () => {
  const out = run(fixture([line('r', 'claude-opus-5', {
    input_tokens: 100, output_tokens: 1000,
    output_tokens_details: { thinking_tokens: 400 },
  })]));
  assert.match(out, /думанье 400 \(40\.0%\)/, out);
});

test('не считает служебные строки CLI за ход модели', () => {
  // <synthetic> — сообщение самого CLI (ошибка авторизации, «No response
  // requested»), запроса к модели за ним не было: счётчики нулевые.
  const out = run(fixture([
    line('r1', 'claude-opus-5', { input_tokens: 1000, output_tokens: 100 }),
    line('r2', '<synthetic>', { input_tokens: 0, output_tokens: 0 },
      { isApiErrorMessage: true }),
  ]));
  assert.doesNotMatch(out, /synthetic/, out);
  assert.match(out, /claude-opus-5\s+req\s+1\s/, out);
});

test('печатает разрез сабагентов по типу агента из meta.json', () => {
  const U = { input_tokens: 1000, cache_read_input_tokens: 0, output_tokens: 100 };
  const out = run(fixture(
    [line('r1', 'claude-opus-5', U)],
    [line('r2', 'claude-haiku-4-5', U), line('r3', 'claude-haiku-4-5', U)],
    'Explore'
  ));
  // один файл сабагента = один вызов, два запроса, вход 2 000, на вызов 2.0k
  assert.match(out, /сабагенты по типам:/, out);
  assert.match(out, /Explore\s+вызовов 1\s+req 2\s+вход\s+2 000\s+на вызов\s+2\.0k/, out);
});

test('цена типа агента считается по ставке его модели', () => {
  // haiku-4-5: вход 1M × $1 = $1.00; opus-5 водителя в строку типа не попадает
  const out = run(fixture(
    [line('r1', 'claude-opus-5', { input_tokens: 1e6, cache_read_input_tokens: 0, output_tokens: 0 })],
    [line('r2', 'claude-haiku-4-5', { input_tokens: 1e6, cache_read_input_tokens: 0, output_tokens: 0 })],
    'Explore'
  ));
  assert.match(out, /Explore\s+вызовов 1\s+req 1\s+вход\s+1 000 000\s+на вызов\s+1000\.0k\s+\$1\.00\s+\(\$1\.00\/вызов\)/, out);
});

test('сабагент без meta.json попадает в тип «?», а не роняет скрипт', () => {
  const U = { input_tokens: 1000, cache_read_input_tokens: 0, output_tokens: 100 };
  const out = run(fixture([line('r1', 'claude-opus-5', U)], [line('r2', 'claude-sonnet-5', U)]));
  assert.match(out, /\?\s+вызовов 1\s+req 1/, out);
});

// Разрез по вызовам нужен, когда агенты одного типа шли на разных моделях:
// в строке типа они сливаются, и модель с effort в ней не видны.
function fixtureCalls(main, agents) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'scs-'));
  fs.writeFileSync(path.join(dir, 'sess.jsonl'), main.join('\n') + '\n');
  const sd = path.join(dir, 'sess', 'subagents');
  fs.mkdirSync(sd, { recursive: true });
  agents.forEach(({ lines, meta }, i) => {
    fs.writeFileSync(path.join(sd, `agent-${i}.jsonl`), lines.join('\n') + '\n');
    if (meta) fs.writeFileSync(path.join(sd, `agent-${i}.meta.json`), JSON.stringify(meta));
  });
  return dir;
}

const runAgents = dir => execFileSync(process.execPath, [SCRIPT, '--agents', dir], { encoding: 'utf8' });

test('--agents печатает строку на вызов: описание, тип, модель, effort', () => {
  const U = { input_tokens: 1000, cache_read_input_tokens: 0, output_tokens: 100 };
  const out = runAgents(fixtureCalls([line('r1', 'claude-opus-5', U)], [
    { lines: [line('r2', 'claude-fable-5-1', U, { perTurnEffort: 'high' })],
      meta: { agentType: 'general-purpose', description: 'Ревью спеки' } },
    { lines: [line('r3', 'claude-haiku-4-5', U, { perTurnEffort: 'low' })],
      meta: { agentType: 'Explore', description: 'Разведка' } },
  ]));
  assert.match(out, /Ревью спеки\s+general-purpose\s+claude-fable-5-1\s+high/, out);
  assert.match(out, /Разведка\s+Explore\s+claude-haiku-4-5\s+low/, out);
});

test('вызов без meta и без effort печатается, а не роняет разрез', () => {
  const U = { input_tokens: 1000, cache_read_input_tokens: 0, output_tokens: 100 };
  const out = runAgents(fixtureCalls([line('r1', 'claude-opus-5', U)],
    [{ lines: [line('r2', 'claude-sonnet-5', U)] }]));
  assert.match(out, /\?\s+claude-sonnet-5\s+—/, out);
});

test('без флага разрез по вызовам не печатается', () => {
  const U = { input_tokens: 1000, cache_read_input_tokens: 0, output_tokens: 100 };
  const out = run(fixtureCalls([line('r1', 'claude-opus-5', U)], [
    { lines: [line('r2', 'claude-fable-5-1', U, { perTurnEffort: 'high' })],
      meta: { agentType: 'general-purpose', description: 'Ревью спеки' } },
  ]));
  assert.doesNotMatch(out, /Ревью спеки/, out);
});
