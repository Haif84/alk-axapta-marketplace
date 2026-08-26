# alk-axapta-marketplace — правила для сессий-авторов

## Версионирование: чек-лист «5 мест» (ОБЯЗАТЕЛЬНО в каждом PR)

Любой PR, меняющий содержимое плагина (код, скиллы, скрипты, hooks — в том
числе правки только `SKILL.md`), бампает **патч-версию плагина И маркетплейса
во всех 5 местах**:

| # | Файл | Поле |
|---|------|------|
| 1 | `.claude-plugin/marketplace.json` | `version` (top-level, версия маркетплейса) |
| 2 | `.claude-plugin/marketplace.json` | `plugins[name=alk-axapta-tools].version` |
| 3 | `.cursor-plugin/marketplace.json` | `metadata.version` (версия маркетплейса) |
| 4 | `plugins/alk-axapta-tools/.claude-plugin/plugin.json` | `version` |
| 5 | `plugins/alk-axapta-tools/.cursor-plugin/plugin.json` | `version` |

Версия плагина (2, 4, 5) и версия маркетплейса (1, 3) — **разные числа**,
двигаются парой: например плагин `1.6.25` + маркетплейс `1.9.20`.

Самопроверка перед push:

```powershell
python -c "
import json
for p in ['.claude-plugin/marketplace.json','.cursor-plugin/marketplace.json','plugins/alk-axapta-tools/.claude-plugin/plugin.json','plugins/alk-axapta-tools/.cursor-plugin/plugin.json']:
    d = json.load(open(p, encoding='utf-8'))
    v = d.get('version') or d.get('metadata',{}).get('version')
    entry = next((x.get('version') for x in d.get('plugins',[]) if x.get('name')=='alk-axapta-tools'), None)
    print(p, '->', v, ('entry='+entry) if entry else '')
"
```

Все 4 строки должны показать новые версии (первая — обе: top-level и entry).

## Коллизии версий между параллельными PR

Версию выбирай от **актуального master на момент мержа**, не на момент
создания ветки. Если параллельный PR успел занять твою версию — ре-бамп на
следующую в своём PR (фикс-коммит). Заголовок PR при этом можно не
переименовывать, но тело коммита должно называть фактическую версию.

## Фикс-коммит после крит-ревью

Фикс-коммит поверх PR (находки ревью) — тоже изменение плагина: если PR уже
был на версии N, а мастер тем временем ушёл вперёд, фикс-коммит включает
ре-бамп. Правило: **в момент squash-мержа версии в PR строго больше версий
master во всех 5 местах**.

## Исключения (бамп не нужен)

Файлы вне состава плагина и маркетплейса: корневые `CLAUDE.md`, `plans/`,
`install/` (пока не под git). Корневой `README.md` — тоже вне плагина, но
если правка сопровождает изменение плагина, бамп уже идёт от него.
