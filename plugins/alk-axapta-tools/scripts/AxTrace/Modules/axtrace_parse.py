"""Разбор трассировок Microsoft Dynamics AX 2012 (провайдер Microsoft-DynamicsAX-Tracing).

Модуль превращает XML, полученный из .etl утилитой tracerpt, в поток событий.
Разбор потоковый (iterparse): XML после конвертации раздувается примерно в шесть раз
(363 МБ .etl дают 2.3 ГБ .xml), целиком в память такое грузить нельзя.

Состав событий трассировки AX:
    54 / 55  — серверный вызов (RPC) уровня AX, начало/конец.
               Поля: AxRPCName, AxRC, AxServerBytesSent, AxServerBytesRecd.
    56 / 57  — метод X++, вход/выход.
               Поля: AxXppClassName, AxXppMethodName, AxFormPath, AxNestLevel.
    59, 65,  — SQL: операторы, выборка строк, параметры привязки.
    66, 67     Поля: AxConDBSpid, AxBindVar*.

ВАЖНО про AxRC: у ServerBuildList это НЕ код ошибки, а число элементов в списке.
Значения вида 13100 или 25125 означают размер выборки, а не сбой.

Стек X++ восстанавливается по AxNestLevel: события 56 идут в порядке выполнения,
уровень вложенности даёт отступ. Предки метода на уровне L — ближайшие
предшествующие события уровней 1..L-1.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Iterator, NamedTuple
from xml.etree import ElementTree

# --- Идентификаторы событий -------------------------------------------------

RPC_BEGIN = 54
RPC_END = 55
XPP_BEGIN = 56
XPP_END = 57
SQL_IDS = frozenset({59, 65, 66, 67})

PROVIDER_GUID = "{8e410b1f-eb34-4417-be16-478a22c98916}"

_NS_RE = re.compile(r"^\{[^}]*\}")


class Event(NamedTuple):
    """Одно событие трассировки."""

    event_id: int
    time: str          # HH:MM:SS.ffffff, локальное время как его записал tracerpt
    pid: str
    tid: str
    opcode: str        # Start / Stop / Info — из RenderingInfo
    data: dict[str, str]

    # --- удобные обёртки над data, чтобы не сыпать литералами по коду ---

    @property
    def xpp_class(self) -> str:
        return self.data.get("AxXppClassName", "")

    @property
    def xpp_method(self) -> str:
        return self.data.get("AxXppMethodName", "")

    @property
    def form_path(self) -> str:
        form = self.data.get("AxFormPath", "")
        return "" if form in ("", "NULL") else form

    @property
    def nest_level(self) -> int:
        try:
            return int(self.data.get("AxNestLevel", "0"))
        except ValueError:
            return 0

    @property
    def rpc_name(self) -> str:
        return self.data.get("AxRPCName", "")

    @property
    def session(self) -> str:
        return self.data.get("AxSessionId", "")

    @property
    def user(self) -> str:
        return self.data.get("AxUserName", "")

    def qualified_name(self) -> str:
        """Имя метода X++ вида Class.method <Форма> — как показываем в отчётах."""
        name = f"{self.xpp_class}.{self.xpp_method}"
        return f"{name} <{self.form_path}>" if self.form_path else name


def _local(tag: str) -> str:
    """Убирает namespace из имени тега: '{...}EventID' -> 'EventID'."""
    return _NS_RE.sub("", tag)


def _time_of(system_el) -> str:
    for child in system_el:
        if _local(child.tag) == "TimeCreated":
            raw = child.get("SystemTime", "")
            # 2026-08-06T15:29:07.372911700+02:59 -> 15:29:07.372911
            if "T" in raw:
                raw = raw.split("T", 1)[1]
            for cut in ("+", "Z"):
                if cut in raw:
                    raw = raw.split(cut, 1)[0]
            return raw[:15]
    return ""


def iter_events(xml_path: Path, wanted_ids: Iterable[int] | None = None) -> Iterator[Event]:
    """Потоково читает XML от tracerpt и отдаёт события.

    wanted_ids сужает выборку по EventID — это заметно ускоряет разбор,
    потому что большая часть событий обычно не нужна.
    """
    wanted = frozenset(wanted_ids) if wanted_ids is not None else None

    context = ElementTree.iterparse(str(xml_path), events=("end",))
    for _, elem in context:
        if _local(elem.tag) != "Event":
            continue

        event_id = 0
        time = pid = tid = opcode = ""
        data: dict[str, str] = {}

        for section in elem:
            name = _local(section.tag)
            if name == "System":
                for child in section:
                    ctag = _local(child.tag)
                    if ctag == "EventID":
                        try:
                            event_id = int((child.text or "0").strip())
                        except ValueError:
                            event_id = 0
                    elif ctag == "Execution":
                        pid = child.get("ProcessID", "")
                        tid = child.get("ThreadID", "")
                time = _time_of(section)
            elif name in ("EventData", "UserData"):
                # Data лежат и напрямую, и внутри ComplexData
                for node in section.iter():
                    if _local(node.tag) == "Data":
                        key = node.get("Name")
                        if key:
                            data[key] = (node.text or "").strip()
            elif name == "RenderingInfo":
                for child in section:
                    if _local(child.tag) == "Opcode":
                        opcode = (child.text or "").strip()

        if wanted is None or event_id in wanted:
            yield Event(event_id, time, pid, tid, opcode, data)

        elem.clear()


def convert_etl(etl_path: Path, xml_path: Path | None = None) -> Path:
    """Конвертирует .etl в XML через tracerpt. Возвращает путь к XML.

    Осторожно: XML примерно в шесть раз больше исходного .etl.
    """
    if shutil.which("tracerpt") is None:
        raise RuntimeError(
            "tracerpt не найден в PATH. Он входит в состав Windows; "
            "проверь, что скрипт запущен в Windows-окружении."
        )

    xml_path = xml_path or etl_path.with_suffix(".xml")
    result = subprocess.run(
        ["tracerpt", str(etl_path), "-o", str(xml_path), "-of", "XML", "-y"],
        capture_output=True,
        text=True,
        encoding="cp866",
        errors="replace",
    )
    if not xml_path.exists():
        raise RuntimeError(
            f"tracerpt не создал {xml_path}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return xml_path


def resolve_input(path: Path, keep_xml: bool = True) -> Path:
    """Принимает .etl или .xml и возвращает путь к XML, конвертируя при необходимости."""
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    if path.suffix.lower() == ".xml":
        return path

    if path.suffix.lower() != ".etl":
        raise ValueError(f"Ожидается .etl или .xml, получено: {path.suffix}")

    xml_path = path.with_suffix(".xml")
    if xml_path.exists() and keep_xml:
        size_mb = xml_path.stat().st_size / 1024 / 1024
        print(f"Использую готовый XML: {xml_path.name} ({size_mb:,.0f} МБ)", file=sys.stderr)
        return xml_path

    etl_mb = path.stat().st_size / 1024 / 1024
    print(
        f"Конвертирую {path.name} ({etl_mb:,.0f} МБ) в XML — "
        f"ожидаемый размер около {etl_mb * 6:,.0f} МБ, это займёт время...",
        file=sys.stderr,
    )
    return convert_etl(path, xml_path)


def build_stack(events: Iterable[Event]) -> Iterator[tuple[Event, list[str]]]:
    """Восстанавливает стек вызовов по AxNestLevel.

    Отдаёт пары (событие, цепочка предков). Цепочка — имена методов уровней 1..L-1,
    то есть кто вызвал этот метод, от корня к непосредственному вызывающему.
    """
    current: dict[int, str] = {}
    for ev in events:
        level = ev.nest_level
        if level <= 0:
            continue
        current[level] = ev.qualified_name()
        # уровни глубже текущего больше не актуальны
        for deeper in [lvl for lvl in current if lvl > level]:
            del current[deeper]
        ancestors = [current[lvl] for lvl in range(1, level) if lvl in current]
        yield ev, ancestors
