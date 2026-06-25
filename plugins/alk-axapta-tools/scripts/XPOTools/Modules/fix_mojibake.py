"""fix_mojibake — починка двойной перекодировки в xpo-файлах.

Сценарий: исходник был в CP1251 (Windows-1251) с русскими комментариями,
кто-то прочёл как Latin-1/CP1252 и пересохранил в UTF-8 — получили моджибейк
вида `Ð´Ð¾ÐºÑƒÐ¼ÐµÐ½Ñ‚` вместо `документ`.

Алгоритм: пробуем несколько кандидатов восстановления, выбираем тот, где:
  - результат декодируется без ошибок,
  - максимум кириллических символов,
  - минимум U+FFFD.

Запуск:
    python -m Modules.fix_mojibake <file_or_dir> [--dry-run]
    fix-mojibake <file_or_dir>           (через bin/-обёртку)
"""

import argparse
import io
import pathlib
import sys
from typing import List, Tuple

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def _cyrillic_count(s: str) -> int:
    return sum(1 for c in s if "Ѐ" <= c <= "ӿ")


def _has_replacement(s: str) -> bool:
    return "�" in s


CANDIDATES = (
    # (src_encoding, dst_encoding) — берём текст, кодируем как src, декодируем как dst.
    ("latin-1", "utf-8"),
    ("cp1252", "utf-8"),
    ("cp1252", "cp1251"),
    ("latin-1", "cp1251"),
)


def try_fix(text: str) -> Tuple[str, str]:
    """Возвращает (best_text, used_pipeline). Если починка не нужна — best_text == text."""
    base_cyr = _cyrillic_count(text)
    best = text
    best_score = base_cyr
    best_label = "no-op"
    for src_enc, dst_enc in CANDIDATES:
        try:
            candidate = text.encode(src_enc, errors="strict").decode(dst_enc, errors="strict")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if _has_replacement(candidate):
            continue
        cyr = _cyrillic_count(candidate)
        # Условие выигрыша: значительно больше кириллицы, чем в исходнике.
        if cyr > best_score and cyr - base_cyr >= 5:
            best = candidate
            best_score = cyr
            best_label = f"{src_enc}->{dst_enc}"
    return best, best_label


def write_xpo(path: pathlib.Path, content: str) -> None:
    if not content.endswith("\n"):
        content += "\n"
    body = content.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
    with open(path, "wb") as f:
        f.write(b"\xef\xbb\xbf")
        f.write(body)


def read_text(path: pathlib.Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8", errors="replace")


def gather_files(target: pathlib.Path) -> List[pathlib.Path]:
    if target.is_file():
        return [target]
    if target.is_dir():
        return sorted(p for p in target.glob("*.xpo") if p.parent.name != "_release")
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Починка моджибейка в xpo-файлах")
    parser.add_argument("target", help="Файл или директория")
    parser.add_argument("--dry-run", action="store_true", help="Не записывать, показать что починилось бы")
    args = parser.parse_args()

    target = pathlib.Path(args.target).resolve()
    files = gather_files(target)
    if not files:
        print(f"ERROR: нет .xpo файлов в {target}", file=sys.stderr)
        return 2

    fixed = 0
    for p in files:
        text = read_text(p)
        new_text, label = try_fix(text)
        if new_text == text:
            continue
        fixed += 1
        action = "[DRY]" if args.dry_run else "[FIX]"
        print(f"{action} {p.name}: pipeline={label}, "
              f"cyrillic {_cyrillic_count(text)}->{_cyrillic_count(new_text)}")
        if not args.dry_run:
            write_xpo(p, new_text)

    print()
    print(f"Files: {len(files)}; fixed: {fixed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
