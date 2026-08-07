"""Отчёты по трассировке AX 2012: горячие места, стеки, RPC, зависшие вызовы.

Каждая функция принимает путь к XML (уже сконвертированному из .etl) и печатает
готовый отчёт. Разбор потоковый, файл читается по одному разу на отчёт.

Главный отчёт для поиска узких мест — hot(): он показывает, какие методы X++
вызываются чаще всего. Дальше по цепочке: stack() отвечает на вопрос «кто их вызывает».
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from axtrace_parse import (  # noqa: E402
    RPC_BEGIN,
    RPC_END,
    SQL_IDS,
    XPP_BEGIN,
    Event,
    build_stack,
    iter_events,
)


def _bar(value: int, top: int, width: int = 24) -> str:
    """Простая полоска для наглядности пропорций."""
    if top <= 0:
        return ""
    filled = max(1, round(width * value / top)) if value else 0
    return "#" * filled


def _print_table(rows: list[tuple[str, int]], title: str, limit: int, unit: str = "вызовов") -> None:
    print(f"\n=== {title} ===")
    if not rows:
        print("  (пусто)")
        return
    top = rows[0][1]
    name_width = min(70, max(len(r[0]) for r in rows[:limit]))
    for name, count in rows[:limit]:
        print(f"  {count:>9,}  {name:<{name_width}}  {_bar(count, top)}")
    total = sum(c for _, c in rows)
    print(f"  {'':>9}  всего {unit}: {total:,} по {len(rows):,} позициям")


def hot(xml_path: Path, limit: int = 25) -> None:
    """Топ методов X++ по числу вызовов — с чего начинать поиск узких мест."""
    counter: Counter[str] = Counter()
    for ev in iter_events(xml_path, (XPP_BEGIN,)):
        if ev.xpp_class:
            counter[ev.qualified_name()] += 1

    _print_table(counter.most_common(), "Горячие методы X++", limit)
    print(
        "\n  Читать так: одинаковое число вызовов у двух методов почти всегда значит,\n"
        "  что они в одном цикле. Ищи не самый частый метод, а самый частый КОРЕНЬ —\n"
        "  для этого прогони: analyze-trace.py stack <метод>"
    )


def stack(xml_path: Path, target: str, limit: int = 10) -> None:
    """Цепочки предков указанного метода: кто и сколько раз его вызывает."""
    chains: Counter[str] = Counter()
    total = 0

    for ev, ancestors in build_stack(iter_events(xml_path, (XPP_BEGIN,))):
        if not ev.xpp_class:
            continue
        name = ev.qualified_name()
        if target.lower() not in name.lower():
            continue
        total += 1
        chains[" > ".join(ancestors) if ancestors else "(корень)"] += 1

    print(f"\n=== Кто вызывает «{target}» ===")
    if not total:
        print("  Совпадений не найдено. Проверь написание — сравнение по подстроке, регистр не важен.")
        return

    print(f"  Всего вызовов: {total:,}\n")
    for chain, count in chains.most_common(limit):
        share = 100.0 * count / total
        print(f"  {count:>9,}  ({share:5.1f}%)")
        for i, step in enumerate(chain.split(" > ")):
            print(f"             {'  ' * i}{'└─ ' if i else ''}{step}")
        print()

    if len(chains) > limit:
        print(f"  ... и ещё {len(chains) - limit} цепочек")


def tree(xml_path: Path, since: str = "", until: str = "", limit: int = 200) -> None:
    """Дерево вызовов с отступами по AxNestLevel за окно времени."""
    print(f"\n=== Дерево вызовов {since or 'с начала'} — {until or 'до конца'} ===")
    shown = 0
    for ev in iter_events(xml_path, (XPP_BEGIN,)):
        if not ev.xpp_class:
            continue
        if since and ev.time < since:
            continue
        if until and ev.time > until:
            break
        indent = "  " * max(0, ev.nest_level - 1)
        print(f"  {ev.time}  L{ev.nest_level:<2} {indent}{ev.qualified_name()}")
        shown += 1
        if shown >= limit:
            print(f"  ... показано {limit} событий, сузь окно ключами --since / --until")
            break
    if not shown:
        print("  (в указанном окне событий X++ нет)")


def rpc(xml_path: Path, limit: int = 25) -> None:
    """Сводка серверных вызовов: сколько раз и сколько байт передано."""
    calls: Counter[str] = Counter()
    sent: defaultdict[str, int] = defaultdict(int)

    for ev in iter_events(xml_path, (RPC_BEGIN, RPC_END)):
        name = ev.rpc_name
        if not name:
            continue
        # у ServerUtilLoad имя содержит параметры в угловых скобках — схлопываем
        short = name.split("&lt;", 1)[0].split("<", 1)[0].strip()
        if ev.event_id == RPC_BEGIN:
            calls[short] += 1
        else:
            try:
                sent[short] += int(ev.data.get("AxServerBytesSent", "0") or 0)
            except ValueError:
                pass

    print("\n=== Серверные вызовы (RPC уровня AX) ===")
    if not calls:
        print("  (пусто)")
        return
    top = calls.most_common(1)[0][1]
    for name, count in calls.most_common(limit):
        mb = sent[name] / 1024 / 1024
        size = f"{mb:8.2f} МБ" if mb >= 0.01 else f"{sent[name]:>8,} Б "
        print(f"  {count:>8,}  {size}  {name:<45} {_bar(count, top, 16)}")

    print(
        "\n  ВНИМАНИЕ: AxRC у ServerBuildList — это число элементов в списке,\n"
        "  а НЕ код ошибки. Значения 13100 или 25125 означают размер выборки."
    )


def hung(xml_path: Path) -> None:
    """Вызовы RPC, начавшиеся и не завершившиеся — след зависания."""
    open_calls: dict[tuple[str, str], Event] = {}
    closed = 0

    for ev in iter_events(xml_path, (RPC_BEGIN, RPC_END)):
        if not ev.rpc_name:
            continue
        key = (ev.pid, ev.tid)
        if ev.event_id == RPC_BEGIN:
            open_calls[key] = ev
        else:
            closed += 1
            open_calls.pop(key, None)

    print("\n=== Незавершённые серверные вызовы ===")
    print(f"  завершено вызовов: {closed:,}")
    if not open_calls:
        print("  Незавершённых нет — зависаний в этом окне не было.")
        return

    print(f"  ЗАВИСЛО: {len(open_calls)}\n")
    for (pid, tid), ev in sorted(open_calls.items(), key=lambda kv: kv[1].time):
        print(
            f"  {ev.time}  pid={pid} tid={tid} сессия={ev.session} "
            f"пользователь={ev.user}\n      {ev.rpc_name}"
        )

    print(
        "\n  Дальше: посмотри, какой метод X++ выпустил этот вызов —\n"
        "  analyze-trace.py tree --since <время минус секунда> --until <время>"
    )


def sql(xml_path: Path, limit: int = 15) -> None:
    """Статистика SQL-событий."""
    by_spid: Counter[str] = Counter()
    total = 0
    for ev in iter_events(xml_path, SQL_IDS):
        total += 1
        spid = ev.data.get("AxConDBSpid", "?")
        by_spid[spid] += 1

    print("\n=== SQL ===")
    print(f"  всего событий: {total:,}")
    if by_spid:
        print("  по соединениям (SPID):")
        for spid, count in by_spid.most_common(limit):
            print(f"    SPID {spid:<6} {count:>9,}")


def summary(xml_path: Path, etl_path: Path | None = None) -> None:
    """Всё сразу: объём, окно времени, топ методов и RPC."""
    counts: Counter[int] = Counter()
    first = last = ""
    xpp: Counter[str] = Counter()
    rpc_calls: Counter[str] = Counter()

    for ev in iter_events(xml_path):
        counts[ev.event_id] += 1
        if ev.time:
            if not first:
                first = ev.time
            last = ev.time
        if ev.event_id == XPP_BEGIN and ev.xpp_class:
            xpp[ev.qualified_name()] += 1
        elif ev.event_id == RPC_BEGIN and ev.rpc_name:
            rpc_calls[ev.rpc_name.split("&lt;", 1)[0].split("<", 1)[0].strip()] += 1

    total = sum(counts.values())
    print("\n=== Сводка трассировки ===")
    print(f"  файл:            {xml_path.name}")
    if etl_path and etl_path.exists():
        print(f"  исходный .etl:   {etl_path.stat().st_size / 1024 / 1024:,.1f} МБ")
    print(f"  событий всего:   {total:,}")
    print(f"  окно времени:    {first} — {last}")
    print(f"  вызовов X++:     {counts.get(XPP_BEGIN, 0):,}")
    print(f"  вызовов RPC:     {counts.get(RPC_BEGIN, 0):,}")
    print(f"  событий SQL:     {sum(counts.get(i, 0) for i in SQL_IDS):,}")

    _print_table(xpp.most_common(), "Топ методов X++", 10)
    _print_table(rpc_calls.most_common(), "Топ серверных вызовов", 10)
