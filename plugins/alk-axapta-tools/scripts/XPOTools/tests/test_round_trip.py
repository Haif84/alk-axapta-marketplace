"""Smoke-тесты XPOTools на синтетических xpo.

Покрывает:
  T1: build → split → byte-equal с исходниками.
  T2: validate на синтетических исходниках и на бандле — exit 0.
  T3: fix_mojibake на синтетическом моджибейке восстанавливает кириллицу.

Запуск (без pytest):
    python tests/test_round_trip.py
"""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Modules"))

from fix_mojibake import try_fix  # noqa: E402

PYTHON = sys.executable
BUILD = str(ROOT / "build-shared-project.py")


CLASS_XPO = (
    "Exportfile for AOT version 1.0 or later\n"
    "Formatversion: 1\n"
    "\n"
    "***Element: CLS\n"
    "\n"
    "; Microsoft Dynamics AX Class: ALK_TestClass unloaded\n"
    "; --------------------------------------------------------------------------------\n"
    "  CLSVERSION 1\n"
    "\n"
    "  CLASS #ALK_TestClass\n"
    "    PROPERTIES\n"
    "      Name                #ALK_TestClass\n"
    "      Origin              #{11111111-1111-1111-1111-111111111111}\n"
    "    ENDPROPERTIES\n"
    "\n"
    "    METHODS\n"
    "      SOURCE #classDeclaration\n"
    "        #//ALK_DEVAX12, DAX_TEST, smoke test, 09.05.2026, akaz\n"
    "        #class ALK_TestClass\n"
    "        #{\n"
    "        #}\n"
    "      ENDSOURCE\n"
    "      SOURCE #new\n"
    "        #void new()\n"
    "        #{\n"
    "        #}\n"
    "      ENDSOURCE\n"
    "    ENDMETHODS\n"
    "\n"
    "***Element: END\n"
)


def write_xpo(path: pathlib.Path, content: str) -> None:
    if not content.endswith("\n"):
        content += "\n"
    body = content.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
    with open(path, "wb") as f:
        f.write(b"\xef\xbb\xbf")
        f.write(body)


def run(cmd, **kw):
    res = subprocess.run(cmd, capture_output=True, text=True, **kw)
    return res


def t1_build_split_round_trip(workdir: pathlib.Path) -> None:
    print("[T1] build → split round-trip (AOT layout — канонический с 2026-07-03)")
    xpo_dir = workdir / "XPO"
    class_dir = xpo_dir / "Classes"
    class_dir.mkdir(parents=True)
    # AOT-layout: без file_prefix, в подпапке по типу (dir_path_for("CLS") == ("Classes",)).
    src = class_dir / "ALK_TestClass.xpo"
    write_xpo(src, CLASS_XPO)

    res = run([
        PYTHON, BUILD,
        "--root", str(xpo_dir),
        "--project-name", "ALK_DEVAX12_DAX_TEST",
        "--guid", "{12345678-1234-1234-1234-1234567890AB}",
        "--dt-stamp", "20260509_0000",
        "--yes",
    ])
    assert res.returncode == 0, f"build failed:\n{res.stdout}\n{res.stderr}"
    bundles = list((xpo_dir / "_release").glob("SharedProject_*.xpo"))
    assert len(bundles) == 1, f"expected 1 bundle, got {bundles}"
    bundle = bundles[0]

    out_dir = workdir / "split-out"
    res = run([
        PYTHON, "-m", "Modules.split_shared_project",
        str(bundle),
        "--out", str(out_dir),
        "--layout", "aot",
    ], cwd=ROOT)
    assert res.returncode == 0, f"split failed:\n{res.stdout}\n{res.stderr}"

    rebuilt = out_dir / "Classes" / "ALK_TestClass.xpo"
    assert rebuilt.exists(), f"split did not produce {rebuilt}"
    assert src.read_bytes() == rebuilt.read_bytes(), "round-trip byte-equal failed"
    print("    OK")


def t2_validate_clean(workdir: pathlib.Path) -> None:
    print("[T2] validate clean sources + bundle")
    xpo_dir = workdir / "XPO"
    bundle = next((xpo_dir / "_release").glob("SharedProject_*.xpo"))

    res = run([PYTHON, "-m", "Modules.validate_xpo", str(xpo_dir), "--strict"], cwd=ROOT)
    assert res.returncode == 0, f"validate sources failed:\n{res.stdout}\n{res.stderr}"

    res = run([PYTHON, "-m", "Modules.validate_xpo", str(bundle), "--strict"], cwd=ROOT)
    assert res.returncode == 0, f"validate bundle failed:\n{res.stdout}\n{res.stderr}"
    print("    OK")


def t3_fix_mojibake() -> None:
    print("[T3] fix_mojibake on synthetic mojibake")
    original = "документация работы с XPO"
    mojibake = original.encode("cp1251").decode("cp1252")
    fixed, pipeline = try_fix(mojibake)
    assert fixed == original, f"fix_mojibake failed: {fixed!r}, pipeline={pipeline}"
    print(f"    OK (pipeline={pipeline})")


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory(prefix="xpotools-test-") as tmp:
        workdir = pathlib.Path(tmp)
        for name, fn in (
            ("T1", lambda: t1_build_split_round_trip(workdir)),
            ("T2", lambda: t2_validate_clean(workdir)),
            ("T3", lambda: t3_fix_mojibake()),
        ):
            try:
                fn()
            except AssertionError as e:
                print(f"    FAIL: {e}")
                failures += 1
            except Exception as e:
                print(f"    ERROR: {e}")
                failures += 1
    print()
    if failures:
        print(f"{failures} test(s) failed")
        return 1
    print("All tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
