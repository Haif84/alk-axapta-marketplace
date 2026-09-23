/*
 * Тесты transcripts.js — поиск папки проекта и перечисление сессий.
 * Домашняя папка подставляется параметром, боевой ~/.claude не трогается.
 */
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { projectDir, listSessions } = require('./transcripts');

// Готовит домашнюю папку с одной папкой проекта и возвращает {h, dir}.
function home(slug) {
  const h = fs.mkdtempSync(path.join(os.tmpdir(), 'tr-'));
  const dir = path.join(h, '.claude', 'projects', slug);
  fs.mkdirSync(dir, { recursive: true });
  return { h, dir };
}

test('находит папку проекта по пути рабочей папки', () => {
  const { h, dir } = home('c--Proj-Foo');
  assert.strictEqual(projectDir('c:\\Proj\\Foo', h), dir);
});

test('находит папку проекта, когда регистр буквы диска не совпал', () => {
  const { h, dir } = home('C--Proj-Foo');
  assert.strictEqual(projectDir('c:\\Proj\\Foo', h), dir);
});

test('подчёркивание и точка в пути дают дефис, как у Claude Code', () => {
  const { h, dir } = home('e--ZeroCoder-01-Tools-my-app');
  assert.strictEqual(projectDir('e:\\ZeroCoder\\01_Tools\\my.app', h), dir);
});

test('сообщает об отсутствии папки проекта', () => {
  const { h } = home('c--Proj-Foo');
  assert.throws(() => projectDir('c:\\Proj\\Bar', h), /не найдена/);
});

test('перечисляет сессии от старой к новой с размером', () => {
  const { h, dir } = home('c--Proj-Foo');
  fs.writeFileSync(path.join(dir, 'old.jsonl'), 'x\n');
  fs.writeFileSync(path.join(dir, 'new.jsonl'), 'xxx\n');
  fs.writeFileSync(path.join(dir, 'note.txt'), 'not a session\n');
  const past = new Date(Date.now() - 3600e3);
  fs.utimesSync(path.join(dir, 'old.jsonl'), past, past);

  const s = listSessions(dir);
  assert.deepStrictEqual(s.map(x => path.basename(x.file)), ['old.jsonl', 'new.jsonl']);
  assert.strictEqual(s[1].size, 4);
  assert.ok(s[0].mtime < s[1].mtime);
});

// Сессии одного проекта расходятся по каталогам: слаг строится от cwd, и работа
// из подпапки создаёт отдельный каталог. Замер из корня видел только свою часть.
const { projectDirs } = require('./transcripts');

// Кладёт в папку проекта сессию с указанной рабочей папкой в первой строке.
function session(dir, cwd) {
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'sess.jsonl'), JSON.stringify({ cwd }) + '\n');
}

test('собирает каталоги подпапок проекта', () => {
  const { h, dir } = home('c--Proj-Foo');
  session(dir, 'c:\\Proj\\Foo');
  const sub = path.join(h, '.claude', 'projects', 'c--Proj-Foo-Sub');
  session(sub, 'c:\\Proj\\Foo\\Sub');
  assert.deepStrictEqual(projectDirs('c:\\Proj\\Foo', h).sort(), [dir, sub].sort());
});

test('не путает подпапку проекта с соседним проектом на том же префиксе', () => {
  const { h, dir } = home('c--Proj-Foo');
  session(dir, 'c:\\Proj\\Foo');
  session(path.join(h, '.claude', 'projects', 'c--Proj-Foo-other'), 'c:\\Proj\\Foo-other');
  assert.deepStrictEqual(projectDirs('c:\\Proj\\Foo', h), [dir]);
});
