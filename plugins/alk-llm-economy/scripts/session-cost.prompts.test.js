/*
 * Тесты разреза по ходам владельца (--prompts): одно сообщение владельца —
 * одна строка с ценой всего, что за ним последовало, включая сабагентов.
 * Запуск: node --test scripts/*.test.js
 */
const { test } = require('node:test');
const assert = require('node:assert');
const { execFileSync } = require('node:child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const SCRIPT = path.join(__dirname, 'session-cost.js');

// Минута сессии: ходы раскладываются по времени, поэтому у каждой строки
// транскрипта свой timestamp.
const at = min => `2026-09-16T09:${String(min).padStart(2, '0')}:00.000Z`;
const hhmm = min => {
  const d = new Date(at(min));
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

const call = (id, min, usage) => JSON.stringify({
  requestId: id, timestamp: at(min),
  message: { model: 'claude-opus-5', usage },
});

const user = (min, content, extra) => JSON.stringify(Object.assign({
  type: 'user', timestamp: at(min), uuid: `u${min}`, message: { role: 'user', content },
}, extra));

function fixture(main, sub) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'scp-'));
  fs.writeFileSync(path.join(dir, 'sess.jsonl'), main.join('\n') + '\n');
  if (sub) {
    const sd = path.join(dir, 'sess', 'subagents');
    fs.mkdirSync(sd, { recursive: true });
    fs.writeFileSync(path.join(sd, 'agent-1.jsonl'), sub.join('\n') + '\n');
    fs.writeFileSync(path.join(sd, 'agent-1.meta.json'),
      JSON.stringify({ agentType: 'Explore', toolUseId: 'toolu_1' }));
  }
  return dir;
}

const run = (dir, ...flags) =>
  execFileSync(process.execPath, [SCRIPT, dir, ...flags], { encoding: 'utf8' });

// вход 1M × $5 = $5.00, выход 100k × $25 = $2.50 → ход стоит $7.50
const U = { input_tokens: 1e6, output_tokens: 1e5 };

test('печатает строку на каждое сообщение владельца с ценой хода', () => {
  const out = run(fixture([
    user(1, 'первый вопрос'), call('r1', 2, U),
    user(3, 'второй вопрос'), call('r2', 4, U),
  ]), '--prompts');
  assert.match(out, new RegExp(`${hhmm(1)}.+\\$\\s*7\\.50.+первый вопрос`), out);
  assert.match(out, new RegExp(`${hhmm(3)}.+\\$\\s*7\\.50.+второй вопрос`), out);
});

test('без флага разрез по ходам не печатается', () => {
  const out = run(fixture([user(1, 'вопрос'), call('r1', 2, U)]));
  assert.doesNotMatch(out, /ходы владельца/, out);
});

test('токены сабагента относятся к ходу, в котором он запущен', () => {
  const out = run(fixture([
    user(1, 'первый'), call('r1', 2, U),
    user(5, 'второй'), call('r2', 6, U),
  ], [call('a1', 7, U)]), '--prompts');
  // Сабагент отработал внутри второго хода: там 2 запроса и удвоенная цена.
  assert.match(out, new RegExp(`${hhmm(1)}\\s+req 1\\s+саб 0.+\\$\\s*7\\.50`), out);
  assert.match(out, new RegExp(`${hhmm(5)}\\s+req 2\\s+саб 1.+\\$\\s*15\\.00`), out);
});

test('уведомление задачи не открывает новый ход владельца', () => {
  const out = run(fixture([
    user(1, 'работай'), call('r1', 2, U),
    user(3, '<task-notification>агент закончил</task-notification>'), call('r2', 4, U),
  ]), '--prompts');
  assert.match(out, new RegExp(`${hhmm(1)}\\s+req 2`), out);
  assert.doesNotMatch(out, /task-notification/, out);
});

test('tool_result, meta и прерывание не считаются ходом владельца', () => {
  const out = run(fixture([
    user(1, 'вопрос'), call('r1', 2, U),
    user(3, [{ type: 'tool_result', content: 'ok' }]),
    user(4, 'подсказка хука', { isMeta: true }),
    user(5, '[Request interrupted by user]'),
    call('r2', 6, U),
  ]), '--prompts');
  assert.match(out, new RegExp(`${hhmm(1)}\\s+req 2`), out);
  assert.doesNotMatch(out, /tool_result|хука|interrupted/, out);
});

test('ходы до первого сообщения владельца не теряются', () => {
  const out = run(fixture([
    call('r0', 1, U),
    user(2, 'вопрос'), call('r1', 3, U),
  ]), '--prompts');
  assert.match(out, /—\s+req 1\s+саб 0.+\$\s*7\.50/, out);
});

test('крупные суммы токенов печатает в миллионах', () => {
  const out = run(fixture([
    user(1, 'вопрос'), call('r1', 2, { input_tokens: 4.2e7, output_tokens: 1000 }),
  ]), '--prompts');
  assert.match(out, /вход\s+42\.0M/, out);
});

test('вставленный скриншот перед текстом не съедает ход', () => {
  const out = run(fixture([
    user(1, [{ type: 'image', source: { type: 'base64', media_type: 'image/png', data: 'iVBOR' } },
      { type: 'text', text: 'вот скриншот' }]),
    call('r1', 2, U),
  ]), '--prompts');
  assert.match(out, new RegExp(`${hhmm(1)}\\s+req 1.+вот скриншот`), out);
});
