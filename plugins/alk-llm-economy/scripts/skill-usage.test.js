/*
 * Тесты skill-usage.js — кто из скиллов вызывался и сколько стоит их листинг.
 * Транскрипты синтетические, боевой ~/.claude не трогается.
 */
const { test } = require('node:test');
const assert = require('node:assert');

const { skillUsesOf, listingSkills } = require('./skill-usage');

test('вызов скилла виден по инструменту Skill', () => {
  const o = { type: 'assistant', timestamp: '2026-09-14T10:00:00Z', message: { content: [
    { type: 'tool_use', name: 'Skill', input: { skill: 'superpowers:brainstorming' } },
  ] } };
  assert.deepStrictEqual(skillUsesOf(o), ['superpowers:brainstorming']);
});

test('другие инструменты не считаются вызовом скилла', () => {
  const o = { type: 'assistant', message: { content: [
    { type: 'tool_use', name: 'Bash', input: { command: 'Skill' } },
  ] } };
  assert.deepStrictEqual(skillUsesOf(o), []);
});

test('два вызова в одном ходе считаются отдельно', () => {
  const o = { type: 'assistant', message: { content: [
    { type: 'tool_use', name: 'Skill', input: { skill: 'code-review' } },
    { type: 'tool_use', name: 'Skill', input: { skill: 'simplify' } },
  ] } };
  assert.deepStrictEqual(skillUsesOf(o), ['code-review', 'simplify']);
});

test('строка без содержимого и мусор не роняют разбор', () => {
  assert.deepStrictEqual(skillUsesOf({ type: 'user', message: { content: 'дальше' } }), []);
  assert.deepStrictEqual(skillUsesOf(null), []);
});

const LISTING = [
  'The following skills are available for use with the Skill tool:',
  '',
  '- code-review: Review the current diff.',
  '- superpowers:brainstorming: Use this before any creative work.',
  '  Второй строкой продолжение описания.',
  '- init: Initialize a new CLAUDE.md file',
].join('\n');

test('листинг разбирается на скиллы с длиной описания', () => {
  const rows = listingSkills(LISTING);
  assert.deepStrictEqual(rows.map(r => r.name), ['code-review', 'superpowers:brainstorming', 'init']);
  assert.ok(rows[0].chars > 0);
});

test('продолжение описания идёт в свой скилл, шапка не считается', () => {
  const rows = listingSkills(LISTING);
  const brainstorming = rows.find(r => r.name === 'superpowers:brainstorming');
  const init = rows.find(r => r.name === 'init');
  assert.ok(brainstorming.chars > init.chars, 'многострочное описание длиннее однострочного');
  assert.strictEqual(rows.reduce((s, r) => s + r.chars, 0) < LISTING.length, true);
});

test('скилл плагина отличается от встроенного по двоеточию', () => {
  const rows = listingSkills(LISTING);
  assert.strictEqual(rows.find(r => r.name === 'superpowers:brainstorming').plugin, true);
  assert.strictEqual(rows.find(r => r.name === 'code-review').plugin, false);
});

/* --- Режим --cost: стоимость ходов приписывается ближайшему вызову Skill --- */

const { attributeTurns } = require('./skill-usage');

// Ход модели опознаётся в проверках по output_tokens — он же метка.
const turn = out => ({ type: 'assistant', requestId: `r${out}`,
  message: { model: 'claude-opus-5', usage: { input_tokens: 1, output_tokens: out } } });
const callTurn = (skill, out) => ({ type: 'assistant', requestId: `r${out}`,
  message: { model: 'claude-opus-5', usage: { input_tokens: 1, output_tokens: out },
    content: [{ type: 'tool_use', name: 'Skill', input: { skill } }] } });
const owner = () => ({ type: 'user', message: { content: 'дальше' } });
const outs = row => row.turns.map(t => t.usage.output_tokens);

test('ходы после вызова идут скиллу, сообщение владельца закрывает отрезок', () => {
  const rows = attributeTurns([callTurn('code-review', 10), turn(20), turn(30), owner(), turn(40)]);
  assert.deepStrictEqual(rows.map(r => r.skill), ['code-review']);
  assert.deepStrictEqual(outs(rows[0]), [20, 30]);
  assert.strictEqual(rows[0].calls, 1);
});

test('ход с самим вызовом скиллу не приписывается', () => {
  const rows = attributeTurns([callTurn('code-review', 10), turn(20)]);
  assert.ok(!outs(rows[0]).includes(10), 'решение позвать скилл принято до того, как его текст попал в контекст');
});

test('служебное сообщение отрезок не закрывает', () => {
  const meta = { type: 'user', isMeta: true, message: { content: 'хук' } };
  const side = { type: 'user', isSidechain: true, message: { content: 'сабагент' } };
  const rows = attributeTurns([callTurn('code-review', 10), meta, turn(20), side, turn(30)]);
  assert.deepStrictEqual(outs(rows[0]), [20, 30]);
});

test('второй вызов в том же цикле забирает последующие ходы себе', () => {
  const rows = attributeTurns([callTurn('brainstorming', 10), turn(20), callTurn('tdd', 30), turn(40)]);
  const by = Object.fromEntries(rows.map(r => [r.skill, outs(r)]));
  assert.deepStrictEqual(by.brainstorming, [20]);
  assert.deepStrictEqual(by.tdd, [40]);
});

test('вызовы одного скилла складываются, ходы до первого вызова ничьи', () => {
  const rows = attributeTurns([turn(5), callTurn('code-review', 10), turn(20), owner(), callTurn('code-review', 25), turn(50)]);
  assert.strictEqual(rows.length, 1);
  assert.strictEqual(rows[0].calls, 2);
  assert.deepStrictEqual(outs(rows[0]), [20, 50]);
});

test('цена хода считается по прайсу с наценкой за запись кэша', () => {
  const { turnCost } = require('./skill-usage');
  // opus 5: вход 5, чтение кэша 0.5, выход 25 $/MTok; запись 5m — ×1.25 от входа.
  const u = { input_tokens: 1e6, cache_read_input_tokens: 1e6, output_tokens: 1e6,
    cache_creation: { ephemeral_5m_input_tokens: 1e6, ephemeral_1h_input_tokens: 1e6 } };
  assert.strictEqual(turnCost('claude-opus-5', u), 5 + 0.5 + 25 + 5 * 1.25 + 5 * 2);
});

test('разбивки по TTL нет — вся запись кэша считается пятиминутной', () => {
  const { turnCost } = require('./skill-usage');
  assert.strictEqual(turnCost('claude-opus-5', { cache_creation_input_tokens: 1e6 }), 5 * 1.25);
});

test('незнакомая модель не роняет счёт', () => {
  const { turnCost } = require('./skill-usage');
  assert.strictEqual(turnCost('claude-unknown', { input_tokens: 1e6 }), 0);
});

test('строки одного хода с общим requestId считаются один раз, вызов в поздней строке виден', () => {
  // Ход приходит в транскрипт несколькими строками: текст отдельно, каждый
  // инструмент отдельно, requestId и usage у них общие.
  const part = blocks => ({ type: 'assistant', requestId: 'r1',
    message: { model: 'claude-opus-5', usage: { output_tokens: 20 }, content: blocks } });
  const text = part([{ type: 'text', text: 'зову скилл' }]);
  const call = part([{ type: 'tool_use', name: 'Skill', input: { skill: 'code-review' } }]);
  const by = objs => Object.fromEntries(attributeTurns(objs).map(r => [r.skill, outs(r)]));
  assert.deepStrictEqual(by([callTurn('brainstorming', 10), text, call, turn(30)]),
    { brainstorming: [20], 'code-review': [30] });
  // Порядок строк внутри хода на счёт не влияет.
  assert.deepStrictEqual(by([callTurn('brainstorming', 10), call, text, turn(30)]),
    { brainstorming: [], 'code-review': [30] });
});

test('результат инструмента и уведомление сабагента отрезок не закрывают', () => {
  // Скилл возвращается записью type=user с tool_result — это не владелец.
  const result = { type: 'user', message: { content: [{ type: 'tool_result', content: 'текст скилла' }] } };
  const notice = { type: 'user', message: { content: [{ type: 'text', text: '<task-notification>готов</task-notification>' }] } };
  const rows = attributeTurns([callTurn('code-review', 10), result, turn(20), notice, turn(30)]);
  assert.deepStrictEqual(outs(rows[0]), [20, 30]);
});

test('отрезок, начатый до --since, отдаёт скиллу свои ходы внутри периода', () => {
  // Фильтр по дню на чтении строк рвал разметку: вызов оставался за границей,
  // а его ходы становились ничьими и молча занижали долю скилла.
  const at = (day, o) => ({ ...o, timestamp: `${day}T10:00:00Z` });
  const rows = attributeTurns([
    at('2026-09-10', callTurn('code-review', 10)),
    at('2026-09-10', turn(20)),
    at('2026-09-12', turn(30)),
  ], '2026-09-11');
  assert.deepStrictEqual(outs(rows[0]), [30]);
  assert.strictEqual(rows[0].calls, 0, 'вызов сделан до периода');
});

test('вызов внутри периода считается, ходы до периода — нет', () => {
  const at = (day, o) => ({ ...o, timestamp: `${day}T10:00:00Z` });
  const rows = attributeTurns([
    at('2026-09-10', callTurn('code-review', 10)),
    at('2026-09-10', turn(20)),
    at('2026-09-12', callTurn('code-review', 25)),
    at('2026-09-12', turn(40)),
  ], '2026-09-11');
  assert.strictEqual(rows[0].calls, 1);
  assert.deepStrictEqual(outs(rows[0]), [40]);
});
