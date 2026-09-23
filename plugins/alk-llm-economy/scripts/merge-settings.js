#!/usr/bin/env node
/*
 * merge-settings.js — вливает фрагмент настроек в ~/.claude/settings.json.
 *
 * settings.json не хранится в репозитории (машинный allowlist), поэтому
 * экономящие ключи переносятся фрагментом (docs/export/settings.fragment.json):
 *   node merge-settings.js <fragment.json> [--target <settings.json>] [--dry-run]
 *
 * Правила слияния: `permissions.deny` объединяется, остальное в `permissions`
 * (allow и т.п.) не трогается; `hooks` заменяются по событию, чужие события
 * остаются; объекты (`env`, `modelSettings`, `skillOverrides`, ...) сливаются
 * по ключам; скаляры перезаписываются. `<HOME>` во фрагменте — домашняя папка.
 * Перед записью делается копия settings.json.bak-<метка>.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');

function substituteHome(text, home) {
  return text.split('<HOME>').join(home.replace(/\\/g, '\\\\'));
}

function isObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

function same(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function merge(target, fragment) {
  const result = JSON.parse(JSON.stringify(target));
  const changed = [];
  for (const [key, value] of Object.entries(fragment)) {
    const before = result[key];
    if (key === 'permissions') {
      result.permissions = { ...(result.permissions || {}) };
      if (value.deny) {
        const deny = [...(result.permissions.deny || [])];
        for (const d of value.deny) if (!deny.includes(d)) deny.push(d);
        result.permissions.deny = deny;
      }
    } else if (key === 'hooks') {
      result.hooks = { ...(result.hooks || {}), ...value };
    } else if (isObject(value) && isObject(before)) {
      result[key] = { ...before, ...value };
    } else {
      result[key] = value;
    }
    if (!same(before, result[key])) changed.push(key);
  }
  return { result, changed };
}

function main(argv) {
  const args = argv.slice(2);
  const fragmentPath = args.find((a) => !a.startsWith('--'));
  if (!fragmentPath) {
    console.error('usage: merge-settings.js <fragment.json> [--target <settings.json>] [--dry-run]');
    process.exit(2);
  }
  const t = args.indexOf('--target');
  const targetPath = t >= 0 ? args[t + 1] : path.join(os.homedir(), '.claude', 'settings.json');
  const dryRun = args.includes('--dry-run');

  const fragment = JSON.parse(substituteHome(fs.readFileSync(fragmentPath, 'utf8'), os.homedir()));
  const target = fs.existsSync(targetPath) ? JSON.parse(fs.readFileSync(targetPath, 'utf8')) : {};
  const { result, changed } = merge(target, fragment);

  if (dryRun) {
    console.log(JSON.stringify(result, null, 2));
    console.log(`changed keys: ${changed.join(', ') || 'none'}`);
    return;
  }
  if (changed.length === 0) {
    console.log('nothing to change');
    return;
  }
  if (fs.existsSync(targetPath)) {
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    fs.copyFileSync(targetPath, `${targetPath}.bak-${stamp}`);
  } else {
    fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  }
  fs.writeFileSync(targetPath, JSON.stringify(result, null, 2) + '\n');
  console.log(`written ${targetPath}; changed keys: ${changed.join(', ')}`);
}

module.exports = { merge, substituteHome };
if (require.main === module) main(process.argv);
