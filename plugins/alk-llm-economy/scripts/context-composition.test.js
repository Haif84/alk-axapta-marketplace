/*
 * Тесты context-composition.js — состав контекста по транскриптам.
 * Транскрипты синтетические, боевой ~/.claude не трогается.
 */
const { test } = require('node:test');
const assert = require('node:assert');

const { partsOf } = require('./context-composition');

// Сумма символов по частям одной строки транскрипта.
const parts = obj => {
  const m = {};
  for (const { part, chars } of partsOf(obj)) m[part] = (m[part] || 0) + chars;
  return m;
};

test('результат инструмента — часть tool_result', () => {
  const o = { type: 'user', message: { content: [{ type: 'tool_result', content: 'вывод' }] } };
  assert.deepStrictEqual(Object.keys(parts(o)), ['tool_result']);
  assert.ok(parts(o).tool_result > 0);
});

test('вызов инструмента — часть tool_use, имя инструмента отдельно', () => {
  const o = { type: 'assistant', message: { content: [{ type: 'tool_use', name: 'Edit', input: { a: 1 } }] } };
  const [p] = partsOf(o);
  assert.strictEqual(p.part, 'tool_use');
  assert.strictEqual(p.tool, 'Edit');
});

test('реплика владельца строкой, а не массивом', () => {
  const o = { type: 'user', message: { content: 'дальше' } };
  assert.deepStrictEqual(Object.keys(parts(o)), ['user']);
});

test('ход ассистента делится на думанье и текст', () => {
  const o = { type: 'assistant', message: { content: [
    { type: 'thinking', thinking: 'длинное размышление про запас' },
    { type: 'text', text: 'коротко' },
  ] } };
  const m = parts(o);
  assert.ok(m.thinking > m.assistant, 'думанье и текст считаются по своим элементам');
});

test('вложение — своя часть с типом', () => {
  const o = { type: 'attachment', attachment: { type: 'instructions', files: [] } };
  assert.deepStrictEqual(Object.keys(parts(o)), ['attach:instructions']);
});

test('служебные записи CLI в контекст не уходят', () => {
  for (const type of ['file-history-snapshot', 'file-history-delta', 'queue-operation',
    'bridge-session', 'atis-latch', 'last-prompt', 'system']) {
    assert.deepStrictEqual(Object.keys(parts({ type })), ['cli'], type);
  }
});

// --- вид команды Bash и хвост крупных вызовов ---

const { bashKind, scan } = require('./context-composition');

test('вид команды Bash — читающая команда важнее первого слова', () => {
  assert.strictEqual(bashKind('cat scripts/session-cost.js'), 'cat');
  assert.strictEqual(bashKind("sed -n '10,300p' docs/costs.md"), 'sed -n');
  assert.strictEqual(bashKind('cd /c/Proj/ClaudeOps && cat docs/tech-debt.md'), 'cat');
  assert.strictEqual(bashKind('node --test scripts/x.test.js'), 'node');
  assert.strictEqual(bashKind('git log --oneline -5'), 'git');
});

// Строки одной синтетической сессии: вызов Bash с крупным выводом и мелкий Read.
const lines = [
  { type: 'assistant', message: { content: [
    { type: 'tool_use', id: 't1', name: 'Bash', input: { command: 'cat big.js' } }] } },
  { type: 'user', message: { content: [
    { type: 'tool_result', tool_use_id: 't1', content: 'x'.repeat(9000) }] } },
  { type: 'assistant', message: { content: [
    { type: 'tool_use', id: 't2', name: 'Read', input: { file_path: 'a.js' } }] } },
  { type: 'user', message: { content: [
    { type: 'tool_result', tool_use_id: 't2', content: 'y'.repeat(100) }] } },
];

test('объём результата относится к инструменту, который его вызвал', () => {
  const s = scan(lines, { tailMin: 8000 });
  assert.strictEqual(s.tools.Bash.calls, 1);
  assert.ok(s.tools.Bash.chars > 9000, 'результат Bash — весь вывод');
  assert.strictEqual(s.tools.Read.calls, 1);
  assert.ok(s.tools.Read.chars < 500);
});

test('в хвост попадают только вызовы длиннее порога', () => {
  const s = scan(lines, { tailMin: 8000 });
  assert.strictEqual(s.tail.calls, 1);
  assert.ok(s.tail.chars > 9000);
  assert.strictEqual(s.tail.byKind['cat'].calls, 1, 'у Bash в хвосте виден вид команды');
});

test('порог хвоста двигается параметром', () => {
  assert.strictEqual(scan(lines, { tailMin: 50 }).tail.calls, 2);
  assert.strictEqual(scan(lines, { tailMin: 100000 }).tail.calls, 0);
});

// --- контекст хода и корзины бюджета ---

const { sessionStats, budget } = require('./context-composition');

// Ход ассистента с заданным чтением кэша; requestId склеивает строки одного запроса.
const turn = (cr, requestId, extra = {}) => ({
  type: 'assistant', requestId,
  message: { model: 'claude-opus-5', usage: { input_tokens: 100, cache_read_input_tokens: cr,
    cache_creation_input_tokens: 0, output_tokens: 10 }, ...extra },
});

test('контекст хода — вход плюс чтение и запись кэша', () => {
  const s = sessionStats([turn(50000, 'r1')]);
  assert.strictEqual(s.turns, 1);
  assert.strictEqual(s.first, 50100);
  assert.strictEqual(s.cacheRead, 50000);
});

test('строки одного запроса считаются одним ходом', () => {
  assert.strictEqual(sessionStats([turn(50000, 'r1'), turn(50000, 'r1')]).turns, 1);
});

test('служебная строка <synthetic> ходом не считается', () => {
  const syn = { type: 'assistant', requestId: 'r9',
    message: { model: '<synthetic>', usage: { input_tokens: 0, cache_read_input_tokens: 0 } } };
  assert.strictEqual(sessionStats([turn(1000, 'r1'), syn]).turns, 1);
});

test('сессии раскладываются по корзинам среднего контекста', () => {
  const b = budget([
    { turns: 10, avg: 60000, cacheRead: 600000, first: 50000 },
    { turns: 20, avg: 120000, cacheRead: 2400000, first: 60000 },
    { turns: 30, avg: 160000, cacheRead: 4800000, first: 55000 },
  ], { minTurns: 5 });
  assert.deepStrictEqual(b.buckets.map(x => x.sessions), [1, 1, 1]);
  assert.deepStrictEqual(b.buckets.map(x => x.turns), [10, 20, 30]);
  assert.ok(b.buckets[2].crShare > 0.6, 'самые длинные сессии дают большую часть чтений');
});

test('короткие сессии в бюджет не входят', () => {
  const b = budget([{ turns: 3, avg: 200000, cacheRead: 600000, first: 50000 }], { minTurns: 5 });
  assert.strictEqual(b.buckets.reduce((n, x) => n + x.sessions, 0), 0);
});

test('базовый контекст — медиана первого хода сессий', () => {
  const mk = first => ({ turns: 10, avg: 100000, cacheRead: 10, first });
  assert.strictEqual(budget([mk(40000), mk(57000), mk(80000)], { minTurns: 5 }).base, 57000);
});

// --- сбор файлов и запуск целиком ---

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const { globalDirs, readLines } = require('./context-composition');

// Домашняя папка с двумя проектами и одной сессией в каждом.
function twoProjects() {
  const h = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-'));
  for (const slug of ['c--Proj-A', 'c--Proj-B']) {
    const dir = path.join(h, '.claude', 'projects', slug);
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 's.jsonl'),
      [JSON.stringify({ type: 'user', cwd: 'c:/Proj/' + slug.slice(-1), message: { content: 'привет' } }),
        ...Array.from({ length: 6 }, (_, i) => JSON.stringify({
          type: 'assistant', requestId: 'r' + i,
          message: { model: 'claude-opus-5', content: [{ type: 'text', text: 'ответ' }],
            usage: { input_tokens: 10, cache_read_input_tokens: 160000, output_tokens: 5 } } })),
      ].join('\n'));
  }
  return h;
}

test('--global берёт папки всех проектов, а не только текущего', () => {
  const h = twoProjects();
  assert.strictEqual(globalDirs(h).length, 2);
});

test('битая строка транскрипта не роняет разбор', () => {
  const f = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'cc-')), 's.jsonl');
  fs.writeFileSync(f, '{"type":"user","message":{"content":"да"}}\n{битая\n\n');
  assert.strictEqual(readLines(f).length, 1);
});

test('скрипт целиком печатает состав, инструменты и бюджет', () => {
  const h = twoProjects();
  const out = execFileSync(process.execPath,
    [path.join(__dirname, 'context-composition.js'), '--global'],
    { env: { ...process.env, USERPROFILE: h, HOME: h }, encoding: 'utf8' });
  assert.match(out, /состав/i);
  assert.match(out, /от 150k/);
  assert.match(out, /%/);
});

// --- снимок системного промпта ---

test('снимок системного промпта в доли состава не входит', () => {
  const snap = { type: 'attachment', attachment: { type: 'prompt_snapshot', systemPrompt: ['z'.repeat(5000)] } };
  const s = scan([snap, ...lines], { tailMin: 8000 });
  assert.ok(!('attach:prompt_snapshot' in s.parts),
    'снимок платится раз на ход, а в транскрипт пишется многократно');
  assert.strictEqual(s.snapshots.length, 1);
  assert.ok(s.snapshots[0] > 5000);
});

// --- длина вложения: считается впрыснутый текст, а не весь объект ---

test('хук: текст берётся из additionalContext, а не из всего объекта', () => {
  const text = 'впрыснутый текст\nвторая строка';
  const o = { type: 'attachment', attachment: {
    type: 'hook_success', hookName: 'SessionStart:startup', hookEvent: 'SessionStart',
    toolUseID: 'a931030d-3074-4ea1-839f-b659a2a35969', command: 'node hook.js',
    durationMs: 12, exitCode: 0, stderr: '', content: '',
    stdout: JSON.stringify({ hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: text } }),
  } };
  assert.strictEqual(parts(o)['attach:hook_success'], text.length);
});

test('хук: непустой content важнее stdout', () => {
  const o = { type: 'attachment', attachment: {
    type: 'hook_additional_context', hookName: 'UserPromptSubmit', content: 'напоминание',
    stdout: 'служебный вывод подлиннее напоминания', toolUseID: 'x',
  } };
  assert.strictEqual(parts(o)['attach:hook_additional_context'], 'напоминание'.length);
});

test('хук без JSON в stdout считается по stdout', () => {
  const o = { type: 'attachment', attachment: {
    type: 'hook_success', hookName: 'SessionStart', content: '', stdout: 'простой текст',
    command: 'echo простой текст', exitCode: 0, durationMs: 3, stderr: '',
  } };
  assert.strictEqual(parts(o)['attach:hook_success'], 'простой текст'.length);
});

test('напоминание считается по своему тексту', () => {
  const o = { type: 'attachment', attachment: {
    type: 'total_tokens_reminder', text: '<total_tokens>15000000 tokens left</total_tokens>' } };
  assert.strictEqual(parts(o)['attach:total_tokens_reminder'],
    '<total_tokens>15000000 tokens left</total_tokens>'.length);
});
