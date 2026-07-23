# -*- coding: utf-8 -*-
"""Build AX AOT Resource .xpo from a binary file (xlsx, etc.).

AOS Export wraps the file as:
  [55-byte SysResourceType header][file bytes][FF FF FF]

Header length fields (little-endian uint32):
  offset 44: len(payload) + 5   where payload = file + 3×FF
  offset 51: len(file)          — length AX uses when exporting the file

Anti-pattern (truncates last 3 bytes on extract): field@51 = len(file)-3 without
trailing FF bytes.
"""
from __future__ import annotations

import argparse
import struct
import uuid
from pathlib import Path

HEADER_HEX = (
    "07fd0707fdfc03"
    "5300790073005200650073006f00750072006300650054007900700065000000"
    "ff0707fd30"
    "00000000"
    "07fd30"
    "00000000"
)
SENTINEL = b"\xff" * 3


def build_blob(file_bytes: bytes) -> bytes:
    payload = file_bytes + SENTINEL
    hdr = bytearray(bytes.fromhex(HEADER_HEX))
    assert len(hdr) == 55
    struct.pack_into("<I", hdr, 44, len(payload) + 5)
    struct.pack_into("<I", hdr, 51, len(file_bytes))
    return bytes(hdr) + payload


def extract_file(blob: bytes) -> bytes:
    """Simulate AX export: take len(file) bytes after the 55-byte header."""
    if len(blob) < 55:
        raise ValueError("blob too short")
    file_len = struct.unpack_from("<I", blob, 51)[0]
    return blob[55 : 55 + file_len]


def hex_dump(data: bytes, width: int = 32) -> str:
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i : i + width]
        lines.append("      " + " ".join(f"{b:02X}" for b in chunk))
    return "\r\n".join(lines)


def write_resource_xpo(
    *,
    file_bytes: bytes,
    name: str,
    filename: str,
    out: Path,
    origin: str | None = None,
) -> Path:
    blob = build_blob(file_bytes)
    if not origin:
        origin = "{" + str(uuid.uuid4()).upper() + "}"
    if not origin.startswith("{"):
        origin = "{" + origin.strip("{}") + "}"
    body = (
        "Exportfile for AOT version 1.0 or later\r\n"
        "Formatversion: 1\r\n"
        "\r\n"
        "***Element: RES\r\n"
        "\r\n"
        f"; Microsoft Dynamics AX RESOURCE : {name} unloaded\r\n"
        "; --------------------------------------------------------------------------------\r\n"
        "  VERSION 1\r\n"
        "  \r\n"
        f"  RESOURCE #{name}\r\n"
        "    PROPERTIES\r\n"
        f"      Name                #{name}\r\n"
        f"      Filename            #{filename}\r\n"
        "      Label               #\r\n"
        "      HelpText            #\r\n"
        "      ConfigurationKey    #\r\n"
        f"      Origin              #{origin}\r\n"
        "    ENDPROPERTIES\r\n"
        "    \r\n"
        f"    BINARY {len(blob)}\r\n"
        f"{hex_dump(blob)}\r\n"
        "    ENDBINARY\r\n"
        "  ENDRESOURCE\r\n"
        "  \r\n"
        "\r\n"
        "***Element: END\r\n"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build AOT Resource .xpo from a binary file")
    p.add_argument("--file", required=True, type=Path, help="Source binary (e.g. .xlsx)")
    p.add_argument("--name", required=True, help="AOT Resource name")
    p.add_argument(
        "--filename",
        default="",
        help="Filename property (default: basename of --file)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output .xpo (default: XPO/Resources/<name>.xpo under cwd)",
    )
    p.add_argument("--origin", default="", help="Origin GUID; generated if omitted")
    args = p.parse_args(argv)

    src: Path = args.file
    if not src.is_file():
        raise SystemExit(f"file not found: {src}")
    data = src.read_bytes()
    filename = args.filename or src.name
    out = args.out or Path("XPO") / "Resources" / f"{args.name}.xpo"
    origin = args.origin or None

    write_resource_xpo(
        file_bytes=data,
        name=args.name,
        filename=filename,
        out=out,
        origin=origin,
    )
    blob = build_blob(data)
    extracted = extract_file(blob)
    if extracted != data:
        raise SystemExit("internal error: extract round-trip failed")
    print(
        f"wrote {out} ({out.stat().st_size} bytes), "
        f"blob={len(blob)}, file={len(data)}, sentinel=ffffff"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
