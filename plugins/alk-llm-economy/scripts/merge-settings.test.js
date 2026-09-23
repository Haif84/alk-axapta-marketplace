/*
 * Тесты merge-settings.js — слияние фрагмента настроек в ~/.claude/settings.json.
 * Работа идёт по временным файлам, боевой settings.json не трогается.
 */
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const script = path.join(__dirname, 'merge-settings.js');
const { merge, substituteHome } = require(script);

function tmpDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'merge-settings-'));
}

test('substituteHome: <HOME> заменяется на домашнюю папку с экранированием для JSON', () => {
  const text = '{"a":"<HOME>\\\\.claude\\\\hooks\\\\x.ps1"}';
  const out = substituteHome(text, 'C:\\Users\\me');
  assert.deepStrictEqual(JSON.parse(out), { a: 'C:\\Users\\me\\.claude\\hooks\\x.ps1' });
});

test('merge: deny объединяется, allow сохраняется, хуки заменяются по событию', () => {
  const target = {
    model: 'claude-sonnet-5',
    permissions: { allow: ['Bash(git *)'], deny: ['Artifact', 'Foo'] },
    hooks: {
      SessionStart: [{ hooks: [{ type: 'command', command: 'old' }] }],
      Notification: [{ hooks: [{ type: 'command', command: 'keep' }] }],
    },
    env: { MY_VAR: '1' },
    enabledPlugins: { 'x@y': true },
  };
  const fragment = {
    model: 'claude-opus-5',
    permissions: { deny: ['Artifact', 'Workflow'] },
    hooks: { SessionStart: [{ hooks: [{ type: 'command', command: 'new' }] }] },
    env: { CLAUDE_CODE_SUBAGENT_MODEL: 'sonnet' },
    autoCompactWindow: 133000,
  };
  const { result, changed } = merge(target, fragment);
  assert.strictEqual(result.model, 'claude-opus-5');
  assert.deepStrictEqual(result.permissions.allow, ['Bash(git *)']);
  assert.deepStrictEqual(result.permissions.deny, ['Artifact', 'Foo', 'Workflow']);
  assert.strictEqual(result.hooks.SessionStart[0].hooks[0].command, 'new');
  assert.strictEqual(result.hooks.Notification[0].hooks[0].command, 'keep');
  assert.deepStrictEqual(result.env, { MY_VAR: '1', CLAUDE_CODE_SUBAGENT_MODEL: 'sonnet' });
  assert.deepStrictEqual(result.enabledPlugins, { 'x@y': true });
  assert.strictEqual(result.autoCompactWindow, 133000);
  assert.deepStrictEqual(changed.sort(), ['autoCompactWindow', 'env', 'hooks', 'model', 'permissions']);
});

test('merge: одинаковый фрагмент второй раз ничего не меняет', () => {
  const fragment = { a: 1, env: { X: '1' }, permissions: { deny: ['A'] } };
  const once = merge({}, fragment).result;
  const twice = merge(once, fragment);
  assert.deepStrictEqual(twice.changed, []);
  assert.deepStrictEqual(twice.result, once);
});

test('CLI: пишет target с резервной копией; --dry-run только печатает', () => {
  const dir = tmpDir();
  const target = path.join(dir, 'settings.json');
  const fragment = path.join(dir, 'fragment.json');
  fs.writeFileSync(target, JSON.stringify({ permissions: { allow: ['X'] } }));
  fs.writeFileSync(fragment, '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"<HOME>\\\\h.ps1"}]}]}}');

  const dry = execFileSync('node', [script, fragment, '--target', target, '--dry-run'], { encoding: 'utf8' });
  assert.match(dry, /Stop/);
  assert.deepStrictEqual(JSON.parse(fs.readFileSync(target, 'utf8')), { permissions: { allow: ['X'] } });
  assert.strictEqual(fs.readdirSync(dir).filter((f) => f.startsWith('settings.json.bak')).length, 0);

  const out = execFileSync('node', [script, fragment, '--target', target], { encoding: 'utf8' });
  assert.match(out, /hooks/);
  const written = JSON.parse(fs.readFileSync(target, 'utf8'));
  assert.deepStrictEqual(written.permissions.allow, ['X']);
  assert.strictEqual(written.hooks.Stop[0].hooks[0].command, path.join(os.homedir(), 'h.ps1'));
  assert.strictEqual(fs.readdirSync(dir).filter((f) => f.startsWith('settings.json.bak')).length, 1);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('CLI: отсутствующий target считается пустым объектом', () => {
  const dir = tmpDir();
  const target = path.join(dir, 'settings.json');
  const fragment = path.join(dir, 'fragment.json');
  fs.writeFileSync(fragment, '{"model":"claude-opus-5"}');
  execFileSync('node', [script, fragment, '--target', target], { encoding: 'utf8' });
  assert.deepStrictEqual(JSON.parse(fs.readFileSync(target, 'utf8')), { model: 'claude-opus-5' });
  fs.rmSync(dir, { recursive: true, force: true });
});
