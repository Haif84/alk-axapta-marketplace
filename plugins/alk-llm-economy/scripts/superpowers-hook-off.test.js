/*
 * Тесты superpowers-hook-off.js — снятие впрыска using-superpowers на старте.
 * Работа идёт по временной копии кэша плагина, боевой ~/.claude не трогается.
 */
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { stripSessionStart, findHookFiles, patchFile } = require('./superpowers-hook-off');

const HOOKS = {
  hooks: {
    SessionStart: [{
      matcher: 'startup|clear|compact',
      hooks: [{ type: 'command', command: '"${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.cmd" session-start' }],
    }],
  },
};

// Кэш плагина во временной папке: <root>/<маркетплейс>/superpowers/<версия>/hooks/hooks.json
function fakeCache(config = HOOKS, version = '6.3.0') {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'sp-hook-'));
  const dir = path.join(root, 'claude-plugins-official', 'superpowers', version, 'hooks');
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, 'hooks.json');
  fs.writeFileSync(file, JSON.stringify(config, null, 2));
  return { root, file };
}

test('SessionStart снимается, остальные события остаются', () => {
  const src = { hooks: { SessionStart: HOOKS.hooks.SessionStart, PreToolUse: [{ matcher: 'Read' }] } };
  const { changed, config } = stripSessionStart(src);
  assert.strictEqual(changed, true);
  assert.deepStrictEqual(Object.keys(config.hooks), ['PreToolUse']);
});

test('повторный вызов ничего не меняет', () => {
  const { config } = stripSessionStart(HOOKS);
  assert.strictEqual(stripSessionStart(config).changed, false);
});

test('кэш плагина находится при любой версии и маркетплейсе', () => {
  const { root, file } = fakeCache(HOOKS, '7.0.1');
  assert.deepStrictEqual(findHookFiles(root), [file]);
});

test('правка делает бэкап и второй раз не трогает файл', () => {
  const { file } = fakeCache();
  const first = patchFile(file);
  assert.strictEqual(first.changed, true);
  assert.ok(fs.existsSync(first.backup), 'рядом лежит бэкап исходного hooks.json');
  assert.ok(!JSON.parse(fs.readFileSync(file, 'utf8')).hooks.SessionStart);
  const mtime = fs.statSync(file).mtimeMs;
  assert.strictEqual(patchFile(file).changed, false);
  assert.strictEqual(fs.statSync(file).mtimeMs, mtime, 'файл не переписан впустую');
});

test('бэкап не затирается вторым прогоном после обновления плагина', () => {
  const { file } = fakeCache();
  const { backup } = patchFile(file);
  fs.writeFileSync(file, JSON.stringify(HOOKS));            // плагин обновился
  fs.writeFileSync(backup, JSON.stringify({ метка: 'первый бэкап' }));
  patchFile(file);
  assert.ok(JSON.parse(fs.readFileSync(backup, 'utf8')).метка, 'первый бэкап на месте');
});

test('--check находит вернувшийся впрыск и молчит, когда его нет', () => {
  const { execFileSync } = require('child_process');
  const { root, file } = fakeCache();
  const run = () => {
    try {
      return { out: execFileSync(process.execPath, [path.join(__dirname, 'superpowers-hook-off.js'),
        '--check', '--root', root], { encoding: 'utf8' }), code: 0 };
    } catch (e) { return { out: e.stdout || '', code: e.status }; }
  };
  const back = run();
  assert.strictEqual(back.code, 1);
  assert.match(back.out, /superpowers/i);
  patchFile(file);
  assert.strictEqual(run().code, 0);
});
