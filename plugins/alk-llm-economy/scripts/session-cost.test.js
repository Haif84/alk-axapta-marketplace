/*
 * Тесты session-cost.js. Запуск: node --test "scripts/*.test.js"
 * Скрипт запускается подпроцессом на временных транскриптах-фикстурах —
 * проверяется поведение CLI, а не внутренние функции.
 */
const { test } = require('node:test');
const assert = require('node:assert');
const { execFileSync } = require('node:child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const SCRIPT = path.join(__dirname, 'session-cost.js');

function usageLine(requestId, model, usage) {
  return JSON.stringify({ requestId, message: { model, usage } });
}

const U = { input_tokens: 1000, cache_creation_input_tokens: 0, cache_read_input_tokens: 0, output_tokens: 1000 };

// Готовит папку проекта с одной сессией; sub — записи сабагентов.
function fixture(main, sub) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'sc-'));
  fs.writeFileSync(path.join(dir, 'sess.jsonl'), main.join('\n') + '\n');
  if (sub) {
    const sd = path.join(dir, 'sess', 'subagents');
    fs.mkdirSync(sd, { recursive: true });
    fs.writeFileSync(path.join(sd, 'agent-1.jsonl'), sub.join('\n') + '\n');
  }
  return dir;
}

const run = dir => execFileSync(process.execPath, [SCRIPT, dir], { encoding: 'utf8' });

test('учитывает транскрипты сабагентов из подпапки сессии', () => {
  const dir = fixture(
    [usageLine('req-main', 'claude-opus-5', U)],
    [usageLine('req-sub', 'claude-sonnet-5', U)]
  );
  const out = run(dir);
  assert.match(out, /claude-sonnet-5/, 'модель сабагента не попала в отчёт');
  // opus 1k in + 1k out = $0.03; sonnet 1k in + 1k out = $0.012 → $0.04
  assert.match(out, /итого \$0\.04/, 'стоимость сабагента не вошла в итог:\n' + out);
});

test('знает цену модели с датой в идентификаторе', () => {
  const dir = fixture([usageLine('req-h', 'claude-haiku-4-5-20251001', U)]);
  const out = run(dir);
  assert.doesNotMatch(out, /\$\?/, 'цена не определилась:\n' + out);
});

test('не считает один запрос дважды при слиянии файлов', () => {
  const dir = fixture(
    [usageLine('req-dup', 'claude-opus-5', U)],
    [usageLine('req-dup', 'claude-opus-5', U)]
  );
  assert.match(run(dir), /итого \$0\.03/);
});

test('запись в часовой кэш стоит 2x входа, а не 1.25x', () => {
  const dir = fixture([usageLine('req-1h', 'claude-opus-5', {
    input_tokens: 0, cache_read_input_tokens: 0, output_tokens: 0,
    cache_creation_input_tokens: 100000,
    cache_creation: { ephemeral_5m_input_tokens: 0, ephemeral_1h_input_tokens: 100000 },
  })]);
  // 100k × $5/MTok × 2 = $1.00 (по ставке 5 минут вышло бы $0.63)
  assert.match(run(dir), /итого \$1\.00/);
});

test('печатает средний контекст на запрос', () => {
  const dir = fixture([
    usageLine('req-a', 'claude-opus-5', { input_tokens: 1000, cache_read_input_tokens: 99000, output_tokens: 500 }),
    usageLine('req-b', 'claude-opus-5', { input_tokens: 1000, cache_creation_input_tokens: 49000, cache_read_input_tokens: 100000, output_tokens: 500 }),
  ]);
  // (1000+99000 + 1000+49000+100000) / 2 = 125 000
  assert.match(run(dir), /avg\s+125\.0k/, 'нет среднего контекста на запрос');
});

test('знает цену моделей предыдущего поколения', () => {
  for (const m of ['claude-sonnet-4-6', 'claude-opus-4-7', 'claude-opus-4-6']) {
    const out = run(fixture([usageLine('req-' + m, m, U)]));
    assert.doesNotMatch(out, /\$\?/, m + ' — цена не определилась:\n' + out);
  }
});

// Разрез по типу агента: тип берётся из agent-<id>.meta.json рядом с транскриптом.
function fixtureAgents(main, agents) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'sc-'));
  fs.writeFileSync(path.join(dir, 'sess.jsonl'), main.join('\n') + '\n');
  const sd = path.join(dir, 'sess', 'subagents');
  fs.mkdirSync(sd, { recursive: true });
  agents.forEach(({ type, lines }, i) => {
    fs.writeFileSync(path.join(sd, `agent-${i}.jsonl`), lines.join('\n') + '\n');
    fs.writeFileSync(path.join(sd, `agent-${i}.meta.json`), JSON.stringify({ agentType: type }));
  });
  return dir;
}

test('разрез по типу называет модель без прайса, а не молчит про $0.00', () => {
  const dir = fixtureAgents([usageLine('req-main', 'claude-opus-5', U)],
    [{ type: 'Explore', lines: [usageLine('req-x', 'claude-mystery-9', U)] }]);
  const out = run(dir);
  assert.match(out, /Explore.*без прайса: claude-mystery-9/,
    'неизвестная модель в разрезе по типу не названа:\n' + out);
});

test('типы в разрезе идут по убыванию цены, а не по появлению', () => {
  const dir = fixtureAgents([usageLine('req-main', 'claude-opus-5', U)], [
    { type: 'Explore', lines: [usageLine('req-e', 'claude-haiku-4-5', U)] },
    { type: 'general-purpose', lines: [usageLine('req-g', 'claude-opus-5', U)] },
  ]);
  const order = run(dir).split('\n').filter(l => l.includes('вызовов'))
    .map(l => l.trim().split(/\s+/)[0]);
  // Две пары: разрез сессии и такой же разрез в блоке ВСЕГО.
  assert.deepStrictEqual(order, ['general-purpose', 'Explore', 'general-purpose', 'Explore'],
    'разрез не отсортирован по цене');
});

test('тип с пробелом не разрывает колонку разреза', () => {
  const dir = fixtureAgents([usageLine('req-main', 'claude-opus-5', U)],
    [{ type: 'мой агент', lines: [usageLine('req-s', 'claude-opus-5', U)] }]);
  const out = run(dir);
  assert.match(out, /мой_агент\s+вызовов 1/, 'пробел в типе не заменён:\n' + out);
});
