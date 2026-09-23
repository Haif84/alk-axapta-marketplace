#!/usr/bin/env node
/*
 * superpowers-hook-off.js — снимает впрыск `using-superpowers` на старте сессии.
 *
 * Плагин вешает SessionStart-хук, который кладёт в контекст весь SKILL.md
 * (3 321 знак, ~1 230 токенов в кэшируемом префиксе каждой сессии). Обязательные
 * скиллы по фазам записаны в `global/CLAUDE.md`, поэтому впрыск снят
 * (решение `docs/decisions/2026-09-14-superpowers-hook.md`).
 *
 * Правка живёт в кэше плагина и слетает при его обновлении, поэтому скрипт
 * идемпотентен, а `--check` (код возврата 1) годится для хука на старте.
 *
 *   node scripts/superpowers-hook-off.js            # снять впрыск
 *   node scripts/superpowers-hook-off.js --check    # вернулся ли он
 */

const fs = require('fs');
const path = require('path');

const cacheRoot = home => path.join(home || process.env.USERPROFILE || process.env.HOME,
  '.claude', 'plugins', 'cache');

// Из конфигурации хуков убирается только SessionStart: других хуков плагин
// не ставит, но появятся — не наше дело их трогать.
function stripSessionStart(config) {
  const hooks = (config && config.hooks) || {};
  if (!hooks.SessionStart) return { changed: false, config };
  const rest = { ...hooks };
  delete rest.SessionStart;
  return { changed: true, config: { ...config, hooks: rest } };
}

// Кэш плагинов: <root>/<маркетплейс>/superpowers/<версия>/hooks/hooks.json.
// Версия и маркетплейс меняются, поэтому путь ищется, а не прописывается.
function findHookFiles(root = cacheRoot()) {
  const out = [];
  let markets;
  try { markets = fs.readdirSync(root); } catch { return out; }
  for (const m of markets) {
    let versions;
    try { versions = fs.readdirSync(path.join(root, m, 'superpowers')); } catch { continue; }
    for (const v of versions) {
      const file = path.join(root, m, 'superpowers', v, 'hooks', 'hooks.json');
      if (fs.existsSync(file)) out.push(file);
    }
  }
  return out;
}

// Бэкап делается один раз: после обновления плагина рядом уже лежит исходник,
// и перезапись превратила бы его в копию уже поправленного файла.
function patchFile(file) {
  const backup = file + '.bak';
  const config = JSON.parse(fs.readFileSync(file, 'utf8'));
  const { changed, config: next } = stripSessionStart(config);
  if (!changed) return { file, changed: false, backup };
  if (!fs.existsSync(backup)) fs.copyFileSync(file, backup);
  fs.writeFileSync(file, JSON.stringify(next, null, 2) + '\n');
  return { file, changed: true, backup };
}

module.exports = { stripSessionStart, findHookFiles, patchFile, cacheRoot };

function main() {
  const args = process.argv.slice(2);
  const i = args.indexOf('--root');
  const files = findHookFiles(i >= 0 ? args[i + 1] : cacheRoot());
  const back = files.filter(f => stripSessionStart(JSON.parse(fs.readFileSync(f, 'utf8'))).changed);
  if (args.includes('--check')) {
    if (!back.length) return;
    console.log(`Впрыск superpowers вернулся: ${back.join(', ')} — снять `
      + 'командой `node ~/.claude/scripts/superpowers-hook-off.js`');
    process.exit(1);
  }
  if (!files.length) { console.log('Кэш плагина superpowers не найден'); return; }
  for (const f of files) {
    const r = patchFile(f);
    console.log(`${r.changed ? 'снят впрыск' : 'уже снят  '}  ${r.file}`);
  }
}

if (require.main === module) main();
