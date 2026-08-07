"""Тесты разбора трассировки AX: события, поля, восстановление стека по AxNestLevel."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "Modules"))

from axtrace_parse import (  # noqa: E402
    RPC_BEGIN,
    RPC_END,
    XPP_BEGIN,
    build_stack,
    iter_events,
    resolve_input,
)

# Образец повторяет формат tracerpt: namespace по умолчанию, System/EventData/RenderingInfo.
SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<Events>
<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System>
    <Provider Name="Microsoft-DynamicsAX-Tracing" Guid="{8e410b1f-eb34-4417-be16-478a22c98916}" />
    <EventID>56</EventID>
    <TimeCreated SystemTime="2026-08-06T15:29:07.372911700+02:59" />
    <Execution ProcessID="42724" ThreadID="15784" ProcessorID="2" />
  </System>
  <EventData>
    <Data Name="AxUserName">akaz</Data>
    <Data Name="AxSessionId">3</Data>
    <Data Name="AxXppClassName">SysSetupFormRun</Data>
    <Data Name="AxXppMethodName">timeoutHandler</Data>
    <Data Name="AxFormPath">CIT_DevToolPanel</Data>
    <Data Name="AxNestLevel">1</Data>
  </EventData>
  <RenderingInfo Culture="ru-RU"><Opcode>Start </Opcode></RenderingInfo>
</Event>
<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System>
    <Provider Name="Microsoft-DynamicsAX-Tracing" Guid="{8e410b1f-eb34-4417-be16-478a22c98916}" />
    <EventID>56</EventID>
    <TimeCreated SystemTime="2026-08-06T15:29:07.373026600+02:59" />
    <Execution ProcessID="42724" ThreadID="15784" ProcessorID="2" />
  </System>
  <EventData>
    <Data Name="AxXppClassName">WinAPI</Data>
    <Data Name="AxXppMethodName">FindWindowEx</Data>
    <Data Name="AxFormPath">NULL</Data>
    <Data Name="AxNestLevel">2</Data>
  </EventData>
  <RenderingInfo Culture="ru-RU"><Opcode>Start </Opcode></RenderingInfo>
</Event>
<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System>
    <Provider Name="Microsoft-DynamicsAX-Tracing" Guid="{8e410b1f-eb34-4417-be16-478a22c98916}" />
    <EventID>56</EventID>
    <TimeCreated SystemTime="2026-08-06T15:29:07.373040700+02:59" />
    <Execution ProcessID="42724" ThreadID="15784" ProcessorID="2" />
  </System>
  <EventData>
    <Data Name="AxXppClassName">DLL</Data>
    <Data Name="AxXppMethodName">new</Data>
    <Data Name="AxFormPath">NULL</Data>
    <Data Name="AxNestLevel">3</Data>
  </EventData>
  <RenderingInfo Culture="ru-RU"><Opcode>Start </Opcode></RenderingInfo>
</Event>
<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System>
    <Provider Name="Microsoft-DynamicsAX-Tracing" Guid="{8e410b1f-eb34-4417-be16-478a22c98916}" />
    <EventID>54</EventID>
    <TimeCreated SystemTime="2026-08-06T15:29:08.100000000+02:59" />
    <Execution ProcessID="42724" ThreadID="15784" ProcessorID="2" />
  </System>
  <EventData>
    <Data Name="AxRPCName">ServerNext</Data>
    <Data Name="AxRC">0</Data>
    <Data Name="AxSessionId">3</Data>
    <Data Name="AxServerBytesSent">301</Data>
  </EventData>
  <RenderingInfo Culture="ru-RU"><Opcode>Start </Opcode></RenderingInfo>
</Event>
<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System>
    <Provider Name="Microsoft-DynamicsAX-Tracing" Guid="{8e410b1f-eb34-4417-be16-478a22c98916}" />
    <EventID>55</EventID>
    <TimeCreated SystemTime="2026-08-06T15:29:08.200000000+02:59" />
    <Execution ProcessID="42724" ThreadID="15784" ProcessorID="2" />
  </System>
  <EventData>
    <Data Name="AxRPCName">ServerBuildList</Data>
    <Data Name="AxRC">13100</Data>
    <Data Name="AxServerBytesSent">171266</Data>
  </EventData>
  <RenderingInfo Culture="ru-RU"><Opcode>Stop </Opcode></RenderingInfo>
</Event>
</Events>
"""


class SampleTraceCase(unittest.TestCase):
    """Общая база: пишет образец во временный XML."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.xml = Path(self._tmp.name) / "sample.xml"
        self.xml.write_text(SAMPLE, encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TestIterEvents(SampleTraceCase):
    def test_reads_all_events(self) -> None:
        self.assertEqual(len(list(iter_events(self.xml))), 5)

    def test_filters_by_event_id(self) -> None:
        xpp = list(iter_events(self.xml, (XPP_BEGIN,)))
        self.assertEqual(len(xpp), 3)
        self.assertTrue(all(e.event_id == XPP_BEGIN for e in xpp))

    def test_strips_namespace_and_reads_fields(self) -> None:
        first = next(iter_events(self.xml, (XPP_BEGIN,)))
        self.assertEqual(first.xpp_class, "SysSetupFormRun")
        self.assertEqual(first.xpp_method, "timeoutHandler")
        self.assertEqual(first.form_path, "CIT_DevToolPanel")
        self.assertEqual(first.nest_level, 1)
        self.assertEqual(first.pid, "42724")
        self.assertEqual(first.session, "3")
        self.assertEqual(first.user, "akaz")

    def test_time_is_local_without_timezone(self) -> None:
        first = next(iter_events(self.xml, (XPP_BEGIN,)))
        self.assertEqual(first.time, "15:29:07.372911")

    def test_form_path_null_becomes_empty(self) -> None:
        events = list(iter_events(self.xml, (XPP_BEGIN,)))
        self.assertEqual(events[1].form_path, "")

    def test_qualified_name_includes_form_only_when_present(self) -> None:
        events = list(iter_events(self.xml, (XPP_BEGIN,)))
        self.assertEqual(events[0].qualified_name(), "SysSetupFormRun.timeoutHandler <CIT_DevToolPanel>")
        self.assertEqual(events[1].qualified_name(), "WinAPI.FindWindowEx")

    def test_rpc_fields(self) -> None:
        rpc = list(iter_events(self.xml, (RPC_BEGIN, RPC_END)))
        self.assertEqual(rpc[0].rpc_name, "ServerNext")
        self.assertEqual(rpc[0].data["AxServerBytesSent"], "301")
        # AxRC у ServerBuildList — размер списка, не код ошибки
        self.assertEqual(rpc[1].data["AxRC"], "13100")


class TestBuildStack(SampleTraceCase):
    def test_ancestors_follow_nest_level(self) -> None:
        chains = {
            ev.qualified_name(): ancestors
            for ev, ancestors in build_stack(iter_events(self.xml, (XPP_BEGIN,)))
        }
        self.assertEqual(chains["SysSetupFormRun.timeoutHandler <CIT_DevToolPanel>"], [])
        self.assertEqual(
            chains["WinAPI.FindWindowEx"],
            ["SysSetupFormRun.timeoutHandler <CIT_DevToolPanel>"],
        )
        self.assertEqual(
            chains["DLL.new"],
            ["SysSetupFormRun.timeoutHandler <CIT_DevToolPanel>", "WinAPI.FindWindowEx"],
        )

    def test_deeper_levels_are_dropped_on_return(self) -> None:
        """После возврата на верхний уровень старая глубина не должна протекать в стек."""
        xml = self.xml.parent / "twolevels.xml"
        body = SAMPLE.replace("</Events>", "")
        body += """
<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System><EventID>56</EventID>
    <TimeCreated SystemTime="2026-08-06T15:29:09.000000000+02:59" />
    <Execution ProcessID="42724" ThreadID="15784" />
  </System>
  <EventData>
    <Data Name="AxXppClassName">Info</Data>
    <Data Name="AxXppMethodName">onEventGoingIdle</Data>
    <Data Name="AxFormPath">NULL</Data>
    <Data Name="AxNestLevel">1</Data>
  </EventData>
</Event>
</Events>
"""
        xml.write_text(body, encoding="utf-8")
        chains = list(build_stack(iter_events(xml, (XPP_BEGIN,))))
        last_event, last_ancestors = chains[-1]
        self.assertEqual(last_event.qualified_name(), "Info.onEventGoingIdle")
        self.assertEqual(last_ancestors, [])


class TestResolveInput(SampleTraceCase):
    def test_xml_passes_through(self) -> None:
        self.assertEqual(resolve_input(self.xml), self.xml)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            resolve_input(self.xml.parent / "нет-такого.xml")

    def test_wrong_extension_raises(self) -> None:
        other = self.xml.parent / "trace.txt"
        other.write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError):
            resolve_input(other)


if __name__ == "__main__":
    unittest.main()
