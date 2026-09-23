#!/usr/bin/env node
/*
 * prune-allowlist.js — чистка раздувшегося permissions.allow в settings.json.
 *
 * Проблема: каждое "always allow" на уникальную команду добавляет в allow
 * точную строку, которая больше никогда не совпадёт (полные вызовы MSBuild с
 * конкретными путями, node из temp-папок, printf/echo с конкретным текстом
 * и т.п.). Список пухнет, а повторные запросы всё равно возникают.
 *
 * Что делает: удаляет ТОЛЬКО одноразовые записи — точные (без хвостового `*`)
 * и длиннее MAXLEN символов. Обобщённые prefix-паттерны (оканчиваются на `*`,
 * напр. `git status*`, `dotnet build *`, `…MSBuild.exe" *`) НЕ трогает,
 * даже если они длинные. Ничего не добавляет и не меняет вне permissions.allow.
 *
 * ВАЖНО: запускать при ЗАКРЫТОМ Claude Code. Живая сессия держит allow-список
 * в памяти и перезаписывает settings.json из неё при каждом новом "always allow",
 * затирая внешние правки. Порядок: закрыть Claude Code -> node ... --apply ->
 * открыть заново.
 *
 * Использование:
 *   node prune-allowlist.js                       # сухой прогон пользовательских настроек
 *   node prune-allowlist.js --apply               # применить чистку (создаёт .bak рядом)
 *   node prune-allowlist.js --ensure-readonly     # + добавить базовые read-only PowerShell-паттерны, если их нет
 *   node prune-allowlist.js <path> --apply        # для другого settings.json
 *
 * По умолчанию цель: ~/.claude/settings.json (C:\Users\<user>\.claude).
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');

const MAXLEN = 120; // точные записи длиннее этого считаем одноразовыми

const args = process.argv.slice(2);
const apply = args.includes('--apply');
const ensureReadonly = args.includes('--ensure-readonly');
const pathArg = args.find(a => !a.startsWith('--'));
const F = pathArg || path.join(os.homedir(), '.claude', 'settings.json');

// Базовые read-only PowerShell cmdlet'ы, которые Claude Code НЕ авто-разрешает
// (в отличие от Bash ls/cat/grep). Добавляются при --ensure-readonly, если их нет.
const READONLY_PS = [
  'PowerShell(Get-ChildItem*)',
  'PowerShell(Get-Service*)',
  'PowerShell(Get-Content*)',
  'PowerShell(Test-Path*)',
  'PowerShell(Select-String*)',
];

let c;
try {
  c = JSON.parse(fs.readFileSync(F, 'utf8'));
} catch (e) {
  console.error('Не удалось прочитать/разобрать ' + F + ': ' + e.message);
  process.exit(1);
}
if (!c.permissions || !Array.isArray(c.permissions.allow)) {
  console.error('В файле нет permissions.allow — нечего чистить.');
  process.exit(1);
}

const allow = c.permissions.allow;

// Обобщённый prefix-паттерн? -> оканчивается на `*` перед закрывающей `)`
function isWildcard(e) {
  return e.replace(/\)\s*$/, '').endsWith('*');
}

const keep = [];
const drop = [];
for (const e of allow) {
  if (!isWildcard(e) && e.length > MAXLEN) drop.push(e);
  else keep.push(e);
}

// Определяем, какие base read-only паттерны нужно добавить (идемпотентно)
const present = new Set(keep);
const toAdd = ensureReadonly ? READONLY_PS.filter(p => !present.has(p)) : [];

console.log('Файл: ' + F);
console.log('Записей allow: ' + allow.length + ' | оставить: ' + keep.length + ' | удалить: ' + drop.length + ' | добавить: ' + toAdd.length);
console.log('\n=== УДАЛЯЕМ (' + drop.length + ') ===');
drop.forEach(e => console.log('  - ' + (e.length > 130 ? e.slice(0, 130) + '…' : e)));
if (ensureReadonly) {
  console.log('\n=== ДОБАВЛЯЕМ (' + toAdd.length + ') ===');
  toAdd.forEach(e => console.log('  + ' + e));
}

if (!apply) {
  console.log('\n(сухой прогон — файл не изменён; добавьте --apply для записи)');
  process.exit(0);
}

if (drop.length === 0 && toAdd.length === 0) {
  console.log('\nНечего менять — список уже в порядке.');
  process.exit(0);
}

fs.copyFileSync(F, F + '.bak');
c.permissions.allow = keep.concat(toAdd);
fs.writeFileSync(F, JSON.stringify(c, null, 2), 'utf8');
JSON.parse(fs.readFileSync(F, 'utf8')); // валидация
console.log('\nПРИМЕНЕНО. Бэкап: ' + F + '.bak | новых записей allow: ' + c.permissions.allow.length);
