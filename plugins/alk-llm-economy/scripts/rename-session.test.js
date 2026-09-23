/*
 * Тесты rename-session.js — дозапись custom-title и выбор безымянных сессий.
 * Транскрипты создаются во временной папке, боевой ~/.claude не трогается.
 */
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { appendCustomTitle, untitled } = require('./rename-session');

const ID = '11111111-2222-3333-4444-555555555555';

// Транскрипт из готовых строк; mtime сдвигается в прошлое на ageMin минут.
function transcript(lines, ageMin = 120, id = ID) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rs-'));
  const file = path.join(dir, id + '.jsonl');
  fs.writeFileSync(file, lines.map(o => JSON.stringify(o)).join('\n') + '\n');
  const t = new Date(Date.now() - ageMin * 60000);
  fs.utimesSync(file, t, t);
  return { dir, file };
}

const user = text => ({ type: 'user', message: { role: 'user', content: [{ type: 'text', text }] } });

test('дописывает строку custom-title в конец транскрипта', () => {
  const { file } = transcript([user('дальше')]);
  appendCustomTitle(file, 'Долг 11: пилот водителя');
  const lines = fs.readFileSync(file, 'utf8').trim().split('\n');
  assert.strictEqual(lines.length, 2);
  assert.deepStrictEqual(JSON.parse(lines[0]), user('дальше'));
  assert.deepStrictEqual(JSON.parse(lines[1]), {
    type: 'custom-title', sessionId: ID, customTitle: 'Долг 11: пилот водителя',
  });
});

test('отказывается писать в транскрипт живой сессии', () => {
  const { file } = transcript([user('дальше')], 5);
  assert.throws(() => appendCustomTitle(file, 'Название'), /живая сессия/);
  assert.strictEqual(fs.readFileSync(file, 'utf8').includes('custom-title'), false);
});

test('пишет в живой транскрипт, если это своя сессия', () => {
  const { file } = transcript([user('дальше')], 5);
  appendCustomTitle(file, 'Название', { self: ID });
  assert.ok(fs.readFileSync(file, 'utf8').includes('"customTitle":"Название"'));
});

test('своей считается только сессия с тем же id', () => {
  const { file } = transcript([user('дальше')], 5);
  assert.throws(() => appendCustomTitle(file, 'Название', { self: 'другой-id' }), /живая сессия/);
});

test('untitled отдаёт сессии без своего и сгенерированного заголовка', () => {
  const { dir, file } = transcript([user('дальше')]);
  const got = untitled([dir]);
  assert.strictEqual(got.length, 1);
  assert.strictEqual(got[0].file, file);
  assert.strictEqual(got[0].sessionId, ID);
  assert.strictEqual(got[0].firstPrompt, 'дальше');
});

test('untitled пропускает сессии с ai-title и с custom-title', () => {
  const a = transcript([user('дальше'), { type: 'ai-title', aiTitle: 'Обзор кода' }]);
  const b = transcript([user('дальше'), { type: 'custom-title', customTitle: 'Свой' }]);
  assert.deepStrictEqual(untitled([a.dir]), []);
  assert.deepStrictEqual(untitled([b.dir]), []);
});

test('untitled не показывает живые сессии', () => {
  const { dir } = transcript([user('дальше')], 5);
  assert.deepStrictEqual(untitled([dir]), []);
});

test('CLI отказывает по живой сессии одной строкой, без стека', () => {
  const h = fs.mkdtempSync(path.join(os.tmpdir(), 'rs-home-'));
  const dir = path.join(h, '.claude', 'projects', 'c--Proj-Foo');
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, ID + '.jsonl');
  fs.writeFileSync(file, JSON.stringify({ ...user('дальше'), cwd: 'c:/Proj/Foo' }) + '\n');

  const r = require('child_process').spawnSync(process.execPath, [
    path.join(__dirname, 'rename-session.js'),
    '--project', 'c:/Proj/Foo', '--session', ID, '--title', 'Название',
  ], { env: { ...process.env, USERPROFILE: h, HOME: h }, encoding: 'utf8' });

  assert.strictEqual(r.status, 1);
  assert.match(r.stderr.trim().split('\n')[0], /живая сессия/);
  assert.strictEqual(r.stderr.includes('at '), false);
});
