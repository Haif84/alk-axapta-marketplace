"""Тесты отчётов: сопоставление начал и концов RPC, границы кольцевого буфера, --limit.

Запуск (без pytest):
    python tests/test_axtrace_report.py
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Modules"))

import axtrace_report as report  # noqa: E402


def _rpc_event(event_id: int, name: str, tid: str, time: str) -> str:
    return f"""<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System><EventID>{event_id}</EventID>
    <TimeCreated SystemTime="2026-08-06T{time}00+02:59" />
    <Execution ProcessID="100" ThreadID="{tid}" />
  </System>
  <EventData>
    <Data Name="AxRPCName">{name}</Data>
    <Data Name="AxSessionId">3</Data>
    <Data Name="AxServerBytesSent">100</Data>
  </EventData>
</Event>"""


class ReportCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.xml = Path(self._tmp.name) / "rpc.xml"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, events: list[str]) -> None:
        body = "\n".join(events)
        self.xml.write_text(
            f'<?xml version="1.0" encoding="UTF-8"?>\n<Events>\n{body}\n</Events>\n',
            encoding="utf-8",
        )

    def run_report(self, func, *args) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            func(self.xml, *args)
        return buffer.getvalue()


class TestHung(ReportCase):
    def test_end_of_another_call_does_not_close_the_hanging_one(self) -> None:
        """Сопоставление только по (процесс, поток) гасило чужое начало.

        Здесь ServerNext повис, а следом в том же потоке завершился ServerBuildList.
        Пока ключом была пара (pid, tid), его конец закрывал ServerNext и настоящее
        зависание исчезало из отчёта.
        """
        self.write([
            _rpc_event(54, "ServerNext", "500", "15:00:00.100000"),
            _rpc_event(55, "ServerBuildList", "500", "15:00:00.200000"),
        ])
        out = self.run_report(report.hung)
        self.assertIn("ЗАВИСЛО: 1", out)
        self.assertIn("ServerNext", out)

    def test_matching_pair_is_closed(self) -> None:
        self.write([
            _rpc_event(54, "ServerNext", "500", "15:00:00.100000"),
            _rpc_event(55, "ServerNext", "500", "15:00:00.200000"),
        ])
        out = self.run_report(report.hung)
        self.assertIn("Незавершённых нет", out)

    def test_same_call_on_other_thread_is_not_matched(self) -> None:
        """Одноимённый вызов в другом потоке — не завершение этого."""
        self.write([
            _rpc_event(54, "ServerNext", "500", "15:00:00.100000"),
            _rpc_event(55, "ServerNext", "600", "15:00:00.200000"),
        ])
        out = self.run_report(report.hung)
        self.assertIn("ЗАВИСЛО: 1", out)

    def test_orphan_end_is_counted_not_reported_as_hang(self) -> None:
        """Кольцевой буфер вытесняет начало: конец без начала — норма, а не клин."""
        self.write([_rpc_event(55, "ServerBuildList", "500", "15:00:00.100000")])
        out = self.run_report(report.hung)
        self.assertIn("концов без начала: 1", out)
        self.assertIn("Незавершённых нет", out)

    def test_nested_calls_close_innermost_first(self) -> None:
        self.write([
            _rpc_event(54, "Outer", "500", "15:00:00.100000"),
            _rpc_event(54, "Inner", "500", "15:00:00.200000"),
            _rpc_event(55, "Inner", "500", "15:00:00.300000"),
            _rpc_event(55, "Outer", "500", "15:00:00.400000"),
        ])
        out = self.run_report(report.hung)
        self.assertIn("завершено вызовов: 2", out)
        self.assertIn("Незавершённых нет", out)


class TestPrintTable(unittest.TestCase):
    def test_zero_limit_does_not_crash(self) -> None:
        """--limit 0 ронял любой отчёт: max() по пустой выборке ширины имени."""
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            report._print_table([("A.m", 5), ("B.m", 3)], "Проба", 0)
        out = buffer.getvalue()
        self.assertIn("всего вызовов: 8", out)

    def test_limit_cuts_rows_but_total_counts_all(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            report._print_table([("A.m", 5), ("B.m", 3)], "Проба", 1)
        out = buffer.getvalue()
        self.assertIn("A.m", out)
        self.assertNotIn("B.m", out)
        self.assertIn("всего вызовов: 8", out)


class TestLimitOption(unittest.TestCase):
    """--limit меньше единицы отвергается разбором аргументов, а не отчётом."""

    def test_zero_is_rejected(self) -> None:
        sys.path.insert(0, str(ROOT))
        import importlib.util

        spec = importlib.util.spec_from_file_location("analyze_trace", ROOT / "analyze-trace.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        # argparse печатает usage в stderr — гасим, чтобы не сорить в отчёте тестов
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            module.build_parser().parse_args(["hot", "t.xml", "--limit", "0"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
