#!/usr/bin/env python3
# 1c8-doc/doc8.py
"""Поиск по справочнику 1С 8.3: find / search / list.

Индекса нет: markdown разбирается на лету, запись — от строки «## » до следующей «## » или «### ».
"""
import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SECTIONS = _TOP = ["global", "collections", "objects", "applied", "forms", "forms-ordinary",
                    "enums", "values", "queries", "admin", "lang"]
_HEAD_RE = re.compile(r"^## (.+?)(?: \(([A-Za-z0-9<][^()]*)\))?$")
# Метки полей записи плюс «Вариант:» — маркер
# альтернативного синтаксиса. Запись без единой такой метки в начале строки — прозаическая
# (глава тома, статья языка запросов): у неё «назначение» берут иначе (см. `_purpose`).
_LABELS = ("Синтаксис:", "Параметры:", "Возвращает:", "Использование:", "Описание:",
           "Элементы коллекции:", "Свойства:", "Методы:", "События:", "Конструкторы:",
           "Значения:", "Поля:", "Параметры формы:", "Доступность:", "Версия:",
           "Устарело:", "Примечание:", "Пример:", "См. также:", "Вариант:")
# Строки, которые не считаются «назначением» даже у прозаической записи: адрес источника,
# состав раздела (список членов, не текст) и перекрёстная ссылка языка запросов.
_NOT_PURPOSE = ("Источник:", "Состав:", "См.:")


class Entry:
    __slots__ = ("path", "line", "name", "name_en", "suffix", "purpose", "text")

    def __init__(self, path, line, name, name_en, suffix):
        self.path, self.line, self.name, self.name_en, self.suffix = path, line, name, name_en, suffix
        self.purpose, self.text = "", ""


def norm(s):
    return (s or "").lower().replace("ё", "е")


def _last(name):
    """Часть имени после последней точки: «ТаблицаЗначений.Добавить» → «Добавить»."""
    return name.rsplit(".", 1)[-1].strip()


def _after(lines, label):
    """Первая непустая строка после метки `label`: на той же строке или следующих.

    Метки нет — `None`; метка есть, но текста после неё нигде нет — `""`.
    """
    for i, l in enumerate(lines):
        if l.startswith(label):
            rest = l[len(label):].strip()
            if rest:
                return rest
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    return nxt.strip()
            return ""
    return None


def _purpose(lines):
    p = _after(lines, "Описание:")
    if p is None:
        p = _after(lines, "Синтаксис:")
        if p is None:
            p = _after(lines, "Вариант:")
    if p is not None:
        return p
    if any(l.startswith(lbl) for l in lines for lbl in _LABELS):
        return ""   # запись со структурой, но без Описание/Синтаксис/Вариант — назначения нет
    for l in lines:
        s = l.strip()
        if not s or s.startswith("```") or s.startswith("- ") or s.startswith(_NOT_PURPOSE):
            continue
        return s
    return ""


def load_entries(root):
    root = Path(root)
    entries = []
    files = []
    for top in _TOP:
        d = root / top
        if d.is_dir():
            files.extend(sorted(d.rglob("*.md"), key=lambda p: p.as_posix()))
    for p in files:
        rel = p.relative_to(root).as_posix()
        cur, body = None, []

        def close():
            if cur is not None:
                cur.text = "\n".join(body).strip("\n")
                cur.purpose = _purpose(body)
                entries.append(cur)

        for no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            m = _HEAD_RE.match(line)
            if m:
                close()
                cur, body = Entry(rel, no, m.group(1).strip(), (m.group(2) or "").strip(), ""), []
            elif line.startswith("### "):
                close()
                cur, body = None, []
            elif cur is not None:
                body.append(line)
        close()
    return entries


def resolve_section(root, name):
    if name is None:
        return lambda path: True
    n = norm(name).strip("/").replace("\\", "/")
    root = Path(root)
    dirs = set()
    stems = {}
    for top in _TOP:
        d = root / top
        if not d.is_dir():
            continue
        for p in d.rglob("*.md"):
            rel = p.relative_to(root).as_posix()
            stems.setdefault(norm(p.stem), []).append(rel)
            parts = rel.split("/")[:-1]
            for k in range(1, len(parts) + 1):
                dirs.add(norm("/".join(parts[:k])))
    if n in dirs:
        return lambda path, n=n: norm(path).startswith(n + "/")
    if n in stems:
        paths = set(stems[n])
        return lambda path, paths=paths: path in paths
    raise ValueError("неизвестный раздел «%s»: каталог (%s), путь каталога или имя файла без .md (см. list)"
                      % (name, ", ".join(SECTIONS)))


def _heading(e):
    if e.name_en and norm(e.name) != norm(e.name_en):
        return "%s (%s)" % (e.name, e.name_en)
    return e.name


def _render(e):
    return "— %s:%d\n## %s\n\n%s\n" % (e.path, e.line, _heading(e), e.text)


def cmd_find(entries, name, section):
    n = norm(name)
    pool = [e for e in entries if section(e.path)]
    exact = [e for e in pool if norm(e.name) == n or norm(e.name_en) == n]
    if not exact:
        exact = [e for e in pool if norm(_last(e.name)) == n or norm(_last(e.name_en)) == n]
    if not exact:
        exact = [e for e in pool if norm(e.name).startswith(n) or norm(e.name_en).startswith(n)]
    if not exact:
        exact = [e for e in pool if n in norm(e.name) or n in norm(e.name_en)]
    if not exact:
        return 1, ""
    if len(exact) <= 5:
        return 0, "\n".join(_render(e) for e in exact)
    return 0, "".join("%s:%d  %s\n" % (e.path, e.line, _heading(e)) for e in exact)


def cmd_search(entries, words, section, limit):
    ws = [norm(w) for w in words if w]
    hits = []
    for idx, e in enumerate(entries):
        if not section(e.path):
            continue
        head, text = norm(_heading(e)), norm(e.text)
        if not all(w in head or w in text for w in ws):
            continue
        syntax = "\n".join(l for l in text.splitlines() if l.startswith("синтаксис"))
        score = sum(3 if w in head else 2 if w in syntax else 1 for w in ws)
        hits.append((-score, idx, e))
    hits.sort(key=lambda h: (h[0], h[1]))
    if not hits:
        return 1, ""
    out = []
    for _, _, e in hits[:limit]:
        tail = " — " + e.purpose if e.purpose else ""
        out.append("%s:%d  %s%s\n" % (e.path, e.line, _heading(e), tail))
    return 0, "".join(out)


def _section_of(path):
    return path.split("/", 1)[0]


def _dir_of(path):
    parts = path.split("/")[:-1]
    return "/".join(parts) if parts else path


def cmd_list(entries, root, section_name):
    if section_name is None:
        counts = {}
        for e in entries:
            counts[e.path] = counts.get(e.path, 0) + 1
        dirs = {}
        for path, n in counts.items():
            d = _dir_of(path)
            files, records = dirs.get(d, (0, 0))
            dirs[d] = (files + 1, records + n)
        out, current = [], None
        for d in sorted(dirs, key=lambda p: (SECTIONS.index(_section_of(p)), p.lower())):
            sec = _section_of(d)
            if sec != current:
                out.append("%s\n" % sec)
                current = sec
            files, records = dirs[d]
            out.append("  %-60s %5d файлов %6d записей\n" % (d, files, records))
        return (0 if out else 1), "".join(out)
    section = resolve_section(root, section_name)
    rows = [e for e in entries if section(e.path)]
    if not rows:
        return 1, ""
    return 0, "".join("%s%s\n" % (_heading(e), " — " + e.purpose if e.purpose else "") for e in rows)


def main(argv=None, root=None):
    root = Path(root) if root else ROOT
    ap = argparse.ArgumentParser(prog="doc8.py", description="Справочник 1С 8.3")
    sub = ap.add_subparsers(dest="cmd")
    f = sub.add_parser("find", help="запись по имени (русскому или английскому)")
    f.add_argument("name")
    f.add_argument("--in", dest="section")
    s = sub.add_parser("search", help="записи, где встречаются все слова")
    s.add_argument("words", nargs="+")
    s.add_argument("--in", dest="section")
    s.add_argument("-n", type=int, default=20)
    l = sub.add_parser("list", help="оглавление или записи раздела")
    l.add_argument("section", nargs="?")
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        # argparse выходит и на «--help» (код 0), и на неверном вызове (код 2) — свой код
        # у него верный, поэтому возвращаем его, а не считаем всякий выход ошибкой
        return exc.code if isinstance(exc.code, int) else 0
    if not a.cmd:
        ap.print_usage(sys.stderr)
        return 2
    if a.cmd == "search" and a.n < 1:
        sys.stderr.write("-n должно быть не меньше 1\n")
        return 2
    try:
        entries = load_entries(root)
        if not entries:
            sys.stderr.write("справочник не собран: python3 %s --src <каталог bin платформы>\n"
                             % (root / "build" / "build_docs.py"))
            return 2
        if a.cmd == "list":
            code, out = cmd_list(entries, root, a.section)
        else:
            section = resolve_section(root, a.section)
            if a.cmd == "find":
                code, out = cmd_find(entries, a.name, section)
            else:
                code, out = cmd_search(entries, a.words, section, a.n)
    except ValueError as exc:
        sys.stderr.write(str(exc) + "\n")
        return 2
    if code == 1:
        sys.stderr.write("ничего не найдено\n")
    try:
        sys.stdout.write(out)
    except BrokenPipeError:
        return 0   # читатель ушёл (`| head`) — это не отказ поиска
    return code


def _quiet_broken_pipe():
    """Труба закрыта: уводим stdout в «никуда», иначе интерпретатор при выходе
    напечатает своё сообщение о BrokenPipeError поверх чужого вывода."""
    try:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    except (OSError, ValueError, AttributeError):
        pass


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        _code = main()
        sys.stdout.flush()   # остаток буфера тоже может упереться в закрытую трубу
    except BrokenPipeError:
        _quiet_broken_pipe()
        _code = 0
    sys.exit(_code)
