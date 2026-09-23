/*
 * Тесты handoff-from-transcript.js. Скрипт запускается подпроцессом на
 * фикстурах-транскриптах: проверяется поведение CLI, а не внутренние функции.
 */
const { test } = require('node:test');
const assert = require('node:assert');
const { execFileSync } = require('node:child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const SCRIPT = path.join(__dirname, 'handoff-from-transcript.js');

let t = 0;
const ts = () => new Date(Date.UTC(2026, 8, 13, 10, 0, t++ * 60)).toISOString();

const prompt = text => JSON.stringify({
  type: 'user', timestamp: ts(), message: { role: 'user', content: [{ type: 'text', text }] },
});
const meta = text => JSON.stringify({
  type: 'user', isMeta: true, timestamp: ts(), message: { role: 'user', content: [{ type: 'text', text }] },
});
const toolResult = text => JSON.stringify({
  type: 'user', timestamp: ts(), toolUseResult: { stdout: text },
  message: { role: 'user', content: [{ type: 'tool_result', content: text }] },
});
const say = (...blocks) => JSON.stringify({
  type: 'assistant', timestamp: ts(), message: { role: 'assistant', content: blocks },
});
const sidechain = text => JSON.stringify({
  type: 'assistant', isSidechain: true, timestamp: ts(),
  message: { role: 'assistant', content: [{ type: 'text', text }] },
});
const text = t => ({ type: 'text', text: t });
const thinking = t => ({ type: 'thinking', thinking: t, signature: 'sig' });
const tool = (name, input) => ({ type: 'tool_use', id: 'tu', name, input });

// Папка проекта с транскриптами; cwd — рабочая папка проекта, как у живого.
// Раскладка повторяет боевую (<home>/.claude/projects/<slug рабочей папки>),
// чтобы скрипт находил транскрипты и сам, без --dir.
function fixture(sessions) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hf-'));
  const home = path.join(root, 'home');
  const cwd = path.join(root, 'project');
  fs.mkdirSync(cwd, { recursive: true });
  const slug = cwd.replace(/[^A-Za-z0-9]/g, '-').replace(/^-/, '');
  const dir = path.join(home, '.claude', 'projects', slug);
  fs.mkdirSync(dir, { recursive: true });
  let age = sessions.length;
  for (const [name, lines] of Object.entries(sessions)) {
    const file = path.join(dir, name + '.jsonl');
    fs.writeFileSync(file, lines.join('\n') + '\n');
    const m = new Date(Date.now() - age-- * 3600e3);
    fs.utimesSync(file, m, m);
  }
  return { dir, cwd, home };
}

const run = (f, ...args) => execFileSync(process.execPath, [SCRIPT, '--dir', f.dir, ...args],
  { encoding: 'utf8', cwd: f.cwd });

// Без --dir: папку проекта скрипт ищет сам от рабочей папки и домашней.
const runBare = (f, ...args) => execFileSync(process.execPath, [SCRIPT, ...args],
  { encoding: 'utf8', cwd: f.cwd, env: { ...process.env, USERPROFILE: f.home, HOME: f.home } });

test('без аргументов перечисляет сессии, свежая первой', () => {
  const f = fixture({
    'aaaaaaaa-1111-2222-3333-444444444444': [prompt('первая')],
    'bbbbbbbb-1111-2222-3333-444444444444': [prompt('вторая'), prompt('ещё')],
  });
  const out = run(f);
  const lines = out.trim().split('\n');
  assert.match(lines[0], /^#1\s+bbbbbbbb/, 'свежая сессия не первая:\n' + out);
  assert.match(lines[1], /^#2\s+aaaaaaaa/);
  assert.match(lines[0], /2 реплик/, 'нет числа реплик владельца:\n' + out);
});

test('помечает сессию без /remember', () => {
  const f = fixture({ 'aaaaaaaa-1111-2222-3333-444444444444': [prompt('работа')] });
  assert.match(run(f), /✗/);
});

// Время реплики с /remember — от него пляшет время записи remember.md.
function rememberStamp(f, name) {
  const line = fs.readFileSync(path.join(f.dir, name + '.jsonl'), 'utf8')
    .split('\n').find(l => l.includes('/remember'));
  return new Date(JSON.parse(line).timestamp);
}

function writeRemember(f, when) {
  const rem = path.join(f.cwd, '.remember');
  fs.mkdirSync(rem, { recursive: true });
  const md = path.join(rem, 'remember.md');
  fs.writeFileSync(md, '# Handoff\n');
  fs.utimesSync(md, when, when);
}

test('помечает сессию, чей /remember лежит в remember.md', () => {
  const f = fixture({
    'aaaaaaaa-1111-2222-3333-444444444444': [prompt('работа'), prompt('<command-name>/remember:remember</command-name>')],
  });
  const stamp = rememberStamp(f, 'aaaaaaaa-1111-2222-3333-444444444444');
  writeRemember(f, new Date(+stamp + 60e3));
  assert.match(run(f), /✓/);
});

test('помечает ✓, когда после /remember сессия ещё продолжалась', () => {
  const f = fixture({
    'aaaaaaaa-1111-2222-3333-444444444444': [
      prompt('<command-name>/remember:remember</command-name>'),
      prompt('ещё правка'), say(text('сделал')), prompt('и ещё одна'),
    ],
  });
  const stamp = rememberStamp(f, 'aaaaaaaa-1111-2222-3333-444444444444');
  writeRemember(f, new Date(+stamp + 60e3));
  const out = run(f);
  assert.match(out, /✓/, 'handoff на месте, но сессия помечена как потерянная:\n' + out);
});

test('помечает /remember, затёртый более поздней сессией', () => {
  const f = fixture({ 'aaaaaaaa-1111-2222-3333-444444444444': [prompt('<command-name>/remember:remember</command-name>')] });
  const stamp = rememberStamp(f, 'aaaaaaaa-1111-2222-3333-444444444444');
  writeRemember(f, new Date(+stamp + 3600e3));
  assert.match(run(f), /⟳/);
});

test('сообщает, когда папка --dir не существует', () => {
  const f = fixture({ 'aaaaaaaa-1111-2222-3333-444444444444': [prompt('работа')] });
  assert.throws(
    () => execFileSync(process.execPath, [SCRIPT, '--dir', path.join(f.dir, 'нет-такой')],
      { encoding: 'utf8', cwd: f.cwd, stdio: 'pipe' }),
    e => !/ENOENT|at Object/.test(String(e.stderr)) && /не найдена/.test(String(e.stderr)),
    'вместо понятного сообщения — стек ENOENT');
});

test('в stdout выжимки — только путь к файлу', () => {
  const f = fixture({ 'aaaaaaaa-1111-2222-3333-444444444444': [prompt('работа'), say(text('ответ'))] });
  const out = run(f, '1');
  assert.strictEqual(out.trim().split('\n').length, 1, 'лишние строки в stdout:\n' + out);
  assert.ok(fs.existsSync(out.trim()), 'файл выжимки не создан: ' + out);
  assert.match(out.trim(), /handoff-aaaaaaaa\.md$/);
});

test('выжимка берёт реплики владельца и текст ассистента', () => {
  const f = fixture({ 'aaaaaaaa-1111-2222-3333-444444444444': [prompt('сделай X'), say(text('делаю X'))] });
  const md = fs.readFileSync(run(f, '1').trim(), 'utf8');
  assert.match(md, /сделай X/);
  assert.match(md, /делаю X/);
});

test('выжимка выбрасывает вставки скиллов, вывод инструментов, размышления и сабагентов', () => {
  const f = fixture({
    'aaaaaaaa-1111-2222-3333-444444444444': [
      prompt('сделай X'),
      meta('Base directory for this skill: мусор скилла'),
      say(thinking('внутренние рассуждения')),
      toolResult('длинный вывод команды'),
      sidechain('отчёт сабагента'),
    ],
  });
  const md = fs.readFileSync(run(f, '1').trim(), 'utf8');
  assert.doesNotMatch(md, /мусор скилла/);
  assert.doesNotMatch(md, /внутренние рассуждения/);
  assert.doesNotMatch(md, /длинный вывод команды/);
  assert.doesNotMatch(md, /отчёт сабагента/);
});

test('вызов инструмента попадает одной строкой с сутью', () => {
  const f = fixture({
    'aaaaaaaa-1111-2222-3333-444444444444': [
      say(tool('Bash', { command: 'node --test scripts/', description: 'Прогнать тесты' })),
      say(tool('Edit', { file_path: 'C:\\Proj\\ClaudeOps\\scripts\\prices.js', old_string: 'a', new_string: 'b' })),
    ],
  });
  const md = fs.readFileSync(run(f, '1').trim(), 'utf8');
  assert.match(md, /Bash: Прогнать тесты/);
  assert.match(md, /Edit: .*prices\.js/);
  assert.doesNotMatch(md, /old_string/, 'в выжимку попал аргумент инструмента целиком');
});

test('принимает uuid сессии и путь к файлу', () => {
  const f = fixture({ 'aaaaaaaa-1111-2222-3333-444444444444': [prompt('работа')] });
  const byUuid = run(f, 'aaaaaaaa-1111-2222-3333-444444444444').trim();
  const byPath = run(f, path.join(f.dir, 'aaaaaaaa-1111-2222-3333-444444444444.jsonl')).trim();
  assert.strictEqual(byUuid, byPath);
  assert.ok(fs.existsSync(byUuid));
});

test('сообщает, когда сессия не найдена', () => {
  const f = fixture({ 'aaaaaaaa-1111-2222-3333-444444444444': [prompt('работа')] });
  assert.throws(() => run(f, '9'), /не найдена|не найден/i);
});

test('время печатается местное, а не UTC', () => {
  const iso = new Date(Date.UTC(2026, 8, 13, 10, 0, 0)).toISOString();
  const line = JSON.stringify({ type: 'user', timestamp: iso,
    message: { role: 'user', content: [{ type: 'text', text: 'работа' }] } });
  const f = fixture({ 'aaaaaaaa-1111-2222-3333-444444444444': [line] });
  const local = new Date(iso).toTimeString().slice(0, 5);
  assert.match(run(f), new RegExp(local), 'в списке не местное время');
  assert.match(fs.readFileSync(run(f, '1').trim(), 'utf8'), new RegExp(local), 'в выжимке не местное время');
});

test('без --dir находит транскрипты текущего проекта и понимает номер сессии', () => {
  const f = fixture({ 'aaaaaaaa-1111-2222-3333-444444444444': [prompt('работа')] });
  assert.match(runBare(f), /^#1\s+aaaaaaaa/, 'список не собрался без --dir');
  const out = runBare(f, '1').trim();
  assert.strictEqual(out.split('\n').length, 1, 'номер сессии потерян, вывелся список:\n' + out);
  assert.match(out, /handoff-aaaaaaaa\.md$/);
});

test('подряд идущие ходы ассистента идут одним блоком', () => {
  const f = fixture({
    'aaaaaaaa-1111-2222-3333-444444444444': [
      prompt('сделай X'),
      say(tool('Bash', { description: 'первая команда' })),
      say(tool('Bash', { description: 'вторая команда' })),
      say(text('готово')),
    ],
  });
  const md = fs.readFileSync(run(f, '1').trim(), 'utf8');
  assert.strictEqual(md.match(/^## .* ассистент$/gm).length, 1,
    'каждый ход ассистента получил свой заголовок:\n' + md);
  assert.match(md, /первая команда[\s\S]*вторая команда[\s\S]*готово/);
});
