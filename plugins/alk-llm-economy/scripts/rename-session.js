/*
 * rename-session.js — своё имя сессии в списке Claude Code.
 *
 * Заголовок строки в списке собирается по приоритету custom-title → ai-title →
 * первое сообщение. ai-title генерируется один раз по первому содержательному
 * промпту, поэтому сессии, начатые словом «дальше», остаются безымянными.
 * Своё имя — это одна строка {"type":"custom-title",...} в конце транскрипта;
 * ровно так пишет команда расширения «Rename Session Tab», сайдкар
 * custom-title.json эта сборка только читает. Побеждает последняя запись,
 * поэтому переименование повторяемо.
 *
 * node scripts/rename-session.js --session <id> --title "Суть работ"
 * node scripts/rename-session.js --list
 */
const fs = require('fs');
const path = require('path');
const { projectDirs, listSessions } = require('./transcripts');

// Транскрипт, который писался только что, принадлежит идущей сессии: чужую
// такую не трогаем, иначе дозапись встрянет в работающий процесс.
const FRESH_MIN = 30;

const sessionIdOf = file => path.basename(file, '.jsonl');

function isFresh(file, { now = Date.now(), freshMinutes = FRESH_MIN } = {}) {
  return now - fs.statSync(file).mtimeMs < freshMinutes * 60000;
}

// self — id своей сессии: её транскрипт живой всегда, и это единственный
// случай, когда писать в свежий файл можно.
function appendCustomTitle(file, title, opts = {}) {
  const sessionId = sessionIdOf(file);
  if (isFresh(file, opts) && opts.self !== sessionId) {
    throw new Error(`живая сессия, запись запрещена: ${file}`);
  }
  const line = JSON.stringify({ type: 'custom-title', sessionId, customTitle: title });
  fs.appendFileSync(file, line + '\n');
  return line;
}

function firstPrompt(text) {
  for (const line of text.split('\n')) {
    let o; try { o = JSON.parse(line); } catch { continue; }
    const c = o && o.type === 'user' && o.message && o.message.content;
    const t = Array.isArray(c) ? c.find(p => p.type === 'text') : null;
    if (t) return t.text;
  }
  return '';
}

// Сессии, у которых в списке нет осмысленного имени: ни своего, ни
// сгенерированного. Живые пропускаются — их переименует своя сессия.
function untitled(dirs, opts = {}) {
  return listSessions(dirs)
    .filter(s => !isFresh(s.file, opts))
    .map(s => ({ ...s, text: fs.readFileSync(s.file, 'utf8') }))
    .filter(s => !s.text.includes('"type":"custom-title"') && !s.text.includes('"type":"ai-title"'))
    .map(s => ({
      file: s.file,
      sessionId: sessionIdOf(s.file),
      mtime: s.mtime,
      firstPrompt: firstPrompt(s.text).slice(0, 100).replace(/\s+/g, ' '),
    }));
}

function arg(name) {
  const i = process.argv.indexOf('--' + name);
  return i === -1 ? undefined : process.argv[i + 1];
}

function main() {
  const dirs = projectDirs(arg('project') || process.cwd());
  if (process.argv.includes('--list')) {
    for (const s of untitled(dirs)) {
      console.log(`${s.sessionId}  ${s.mtime.toISOString().slice(0, 16).replace('T', ' ')}  ${s.firstPrompt}`);
    }
    return;
  }
  const id = arg('session');
  const title = arg('title');
  if (!id || !title) {
    console.error('Нужны --session <id> и --title "Суть работ" либо --list');
    process.exit(2);
  }
  const file = listSessions(dirs).map(s => s.file).find(f => sessionIdOf(f) === id);
  if (!file) { console.error('Сессия не найдена: ' + id); process.exit(2); }
  if (process.argv.includes('--dry-run')) {
    console.log(`${file}\n+ ${JSON.stringify({ type: 'custom-title', sessionId: id, customTitle: title })}`);
    return;
  }
  appendCustomTitle(file, title, { self: arg('self') });
  console.log(`${id} → ${title}`);
}

if (require.main === module) {
  try { main(); } catch (e) { console.error(e.message); process.exit(1); }
}

module.exports = { appendCustomTitle, untitled };
