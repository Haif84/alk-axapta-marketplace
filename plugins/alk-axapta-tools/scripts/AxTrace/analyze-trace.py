"""Разбор трассировки клиента Microsoft Dynamics AX 2012.

Отвечает на главный вопрос профилирования: чем занят клиент и что делает это чаще всего.
На вход принимает .etl (сконвертирует сам через tracerpt) или готовый .xml.

Подкоманды:
    summary            общая сводка: объём, окно времени, топ методов и вызовов
    hot                топ методов X++ по числу вызовов — начинать отсюда
    stack <метод>      кто вызывает указанный метод (цепочки предков)
    tree               дерево вызовов за окно времени
    rpc                серверные вызовы: количество и переданные байты
    hung               незавершённые серверные вызовы — след зависания
    sql                статистика SQL-событий

Запуск:
    python analyze-trace.py summary C:\\AxTrace\\DataCollector01.etl
    python analyze-trace.py hot trace.xml --limit 30
    python analyze-trace.py stack "DLL.new" trace.xml
    python analyze-trace.py tree trace.xml --since 17:08:00 --until 17:08:05
    python analyze-trace.py hung trace.etl

Побочные эффекты: при подаче .etl рядом создаётся .xml примерно вшестеро большего
размера. Повторные запуски переиспользуют готовый .xml — удали его, если нужен
свежий разбор того же .etl.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "Modules"))

import axtrace_report as report  # noqa: E402
from axtrace_parse import resolve_input  # noqa: E402

if sys.platform == "win32":
    # reconfigure(), не пересоздание TextIOWrapper: при импорте нескольких таких
    # скриптов в одном процессе (например unittest discover тянет их как модули)
    # каждое присваивание оборачивало ТЕКУЩИЙ .buffer заново — старая обёртка теряла
    # ссылку, GC закрывал её вместе с общим нижним буфером, и следующий модуль писал
    # уже в закрытый поток (ValueError: I/O operation on closed file).
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")


def _limit(value: str) -> int:
    """--limit меньше единицы показывать нечего, а отчёту ломает раскладку."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"нужно целое число, получено: {value}")
    if number < 1:
        raise argparse.ArgumentTypeError(f"должно быть не меньше 1, получено: {number}")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="analyze-trace",
        description="Разбор трассировки клиента Dynamics AX 2012 (Microsoft-DynamicsAX-Tracing)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("trace", type=Path, help="файл .etl или .xml")

    p = sub.add_parser("summary", help="общая сводка")
    add_common(p)

    p = sub.add_parser("hot", help="топ методов X++ по числу вызовов")
    add_common(p)
    p.add_argument("--limit", type=_limit, default=25, help="сколько строк показать (25)")

    p = sub.add_parser("stack", help="кто вызывает указанный метод")
    p.add_argument("method", help="имя метода или его часть, регистр не важен")
    add_common(p)
    p.add_argument("--limit", type=_limit, default=10, help="сколько цепочек показать (10)")

    p = sub.add_parser("tree", help="дерево вызовов за окно времени")
    add_common(p)
    p.add_argument("--since", default="", help="начало окна, HH:MM:SS")
    p.add_argument("--until", default="", help="конец окна, HH:MM:SS")
    p.add_argument("--limit", type=_limit, default=200, help="предел строк (200)")

    p = sub.add_parser("rpc", help="серверные вызовы")
    add_common(p)
    p.add_argument("--limit", type=_limit, default=25, help="сколько строк показать (25)")

    p = sub.add_parser("hung", help="незавершённые серверные вызовы")
    add_common(p)

    p = sub.add_parser("sql", help="статистика SQL")
    add_common(p)
    p.add_argument("--limit", type=_limit, default=15, help="сколько соединений показать (15)")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        xml_path = resolve_input(args.trace)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 1

    etl = args.trace if args.trace.suffix.lower() == ".etl" else None

    if args.command == "summary":
        report.summary(xml_path, etl)
    elif args.command == "hot":
        report.hot(xml_path, args.limit)
    elif args.command == "stack":
        report.stack(xml_path, args.method, args.limit)
    elif args.command == "tree":
        report.tree(xml_path, args.since, args.until, args.limit)
    elif args.command == "rpc":
        report.rpc(xml_path, args.limit)
    elif args.command == "hung":
        report.hung(xml_path)
    elif args.command == "sql":
        report.sql(xml_path, args.limit)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
