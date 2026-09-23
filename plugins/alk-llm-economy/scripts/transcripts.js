/*
 * transcripts.js — где лежат транскрипты Claude Code и какие сессии в них есть.
 * Общий модуль для session-cost.js и handoff-from-transcript.js.
 */
const fs = require('fs');
const path = require('path');

function defaultHome() { return process.env.USERPROFILE || process.env.HOME; }

// Слаг папки в ~/.claude/projects: путь рабочей папки, где всё, кроме латиницы
// и цифр, заменено дефисом — как делает Claude Code (01_Tools -> 01-Tools).
const slugOf = cwd => cwd.replace(/[^A-Za-z0-9]/g, '-').replace(/^-/, '');

// Рабочая папка сессии — из первой строки транскрипта. Слаг неоднозначен:
// c--Proj-Foo-other — это и подпапка Foo\other, и соседний проект Foo-other.
function dirCwd(dir) {
  for (const f of fs.readdirSync(dir).filter(f => f.endsWith('.jsonl'))) {
    for (const line of fs.readFileSync(path.join(dir, f), 'utf8').split('\n')) {
      let o; try { o = JSON.parse(line); } catch { continue; }
      if (o && o.cwd) return o.cwd;
    }
  }
  return null;
}

// Все каталоги проекта: свой и созданные работой из подпапок. Слаг строится от
// cwd, поэтому сессии одного проекта расходятся по каталогам, а замер из корня
// видел только свою часть и молча занижал сумму.
function projectDirs(cwd = process.cwd(), home = defaultHome()) {
  const slug = slugOf(cwd);
  const root = path.join(home, '.claude', 'projects');
  // Имя ищется по каталогу, а не через existsSync: буква диска попадает в слаг
  // в разном регистре, а на Windows existsSync этого не различает и вернул бы
  // путь с чужим регистром.
  const names = fs.existsSync(root) ? fs.readdirSync(root) : [];
  const eq = (a, b) => a.toLowerCase() === b.toLowerCase();
  const main = names.find(d => d === slug) || names.find(d => eq(d, slug));
  if (!main) throw new Error('Папка проекта не найдена: ' + path.join(root, slug));
  const nested = names
    .filter(d => d !== main && d.toLowerCase().startsWith(slug.toLowerCase() + '-'))
    .filter(d => {
      // Сверка по слагу здесь не годится — он неоднозначен ровно так же;
      // подпапку от соседнего проекта отличает только настоящий путь.
      const c = dirCwd(path.join(root, d));
      const norm = p => p.toLowerCase().replace(/\\/g, '/').replace(/\/+$/, '');
      return c && norm(c).startsWith(norm(cwd) + '/');
    });
  return [path.join(root, main), ...nested.map(d => path.join(root, d))];
}

const projectDir = (cwd, home) => projectDirs(cwd, home)[0];

// Сессии проекта от старой к новой: {file, mtime, size}.
function listSessions(dir) {
  const dirs = Array.isArray(dir) ? dir : [dir];
  return dirs.flatMap(d => fs.readdirSync(d).filter(f => f.endsWith('.jsonl'))
    .map(f => {
      const file = path.join(d, f);
      const st = fs.statSync(file);
      return { file, mtime: st.mtime, size: st.size };
    }))
    .sort((a, b) => a.mtime - b.mtime);
}

module.exports = { projectDir, projectDirs, listSessions };
