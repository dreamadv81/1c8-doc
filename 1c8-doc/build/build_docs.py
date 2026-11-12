#!/usr/bin/env python3
# 1c8-doc/build/build_docs.py
"""Сборка справочника навыка 1c8-doc из четырёх книг синтакс-помощника платформы.

python3 build/build_docs.py --src КАТАЛОГ_BIN [--out КАТАЛОГ_НАВЫКА] [--platform ВЕРСИЯ]
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bracket, container, hbk, layout, page, prose, render  # noqa: E402

BOOKS = ["shcntx_ru", "shlang_ru", "shclang_ru", "shquery_ru"]
OUT_DIRS = ["global", "collections", "objects", "applied", "forms", "forms-ordinary",
            "enums", "values", "queries", "admin", "lang"]
COMMANDS = ["python3 doc8.py find ИМЯ [--in РАЗДЕЛ]",
            "python3 doc8.py search СЛОВО… [--in РАЗДЕЛ] [-n N]",
            "python3 doc8.py list [РАЗДЕЛ]"]
_SENTENCE = re.compile(r"^(.{1,200}?\.)(\s|$)", re.S)


def _first_sentence(rec):
    """Первая фраза поля «Описание» (до первой точки включительно, до 200 знаков);
    у записи без «Описание» (например, у записей малых книг — там поле не заводится,
    текст лежит в prose) — пустая строка."""
    text = dict(rec.fields).get("Описание", "")
    m = _SENTENCE.match(text.replace("\n", " "))
    return m.group(1) if m else ""


def _record_for(item, books, keywords):
    book = books[item.book]
    if item.book == "shcntx_ru":
        node = book.nodes[item.node]
        try:
            rec = page.parse_page(book.pages[node.path], in_params=layout.member_dir(node.path) == "params")
        except page.PageError as exc:
            raise SystemExit("%s: страница %s: %s" % (item.book, node.path, exc))
        if node.path.startswith("tables/"):
            rec.code_lang = "sql"
        rec.source = "%s.hbk (%s)" % (item.book, "/".join(hbk.toc_path(book, item.node)))
        return rec
    lang = "sql" if item.book == "shquery_ru" else "bsl"
    if item.node:
        node = book.nodes[item.node]
        path, name = node.path, node.ru
    else:
        path, name = item.text, ""
    h1, body = prose.html_to_text(book.pages[path], lang)
    name = name or page.split_title(h1)[0]
    en = page.split_title(h1)[1] if h1 else ""
    if not en and item.book == "shquery_ru":
        en = keywords.get(name, "")
    source = "%s.hbk (%s)" % (item.book, "/".join(hbk.toc_path(book, item.node)) if item.node else path)
    return page.Record(name, en, prose=body, source=source)


def _missing_note(book):
    """«, узлов без страницы N (имя1, имя2, …)» — для малых книг это не отказ, а строка
    отчёта: узел оглавления сослался на страницу, которой в
    FileStorage нет, и `hbk.load_book` сам превратил его в папку без страницы."""
    if not book.missing:
        return ""
    return ", узлов без страницы %d (%s)" % (len(book.missing), ", ".join(ru for _, ru, _ in book.missing))


def build(src, out, platform):
    # заведён корень в layout.ROOT_MAP, забыли завести каталог в OUT_DIRS — без этой
    # заставы build() падает голым ValueError из OUT_DIRS.index(...) посреди записи
    # INDEX.md, а незаведённый каталог не чистится при пересборке (finding 5, финальный
    # обзор 2026-09-10).
    stray = sorted(set(layout.ROOT_MAP.values()) - set(OUT_DIRS))
    if stray:
        raise SystemExit("в layout.ROOT_MAP есть каталог(и), которых нет в OUT_DIRS: %s" % ", ".join(stray))
    src, out = Path(src).resolve(), Path(out).resolve()
    missing = [n + ".hbk" for n in BOOKS if not (src / (n + ".hbk")).exists()]
    if missing:
        raise SystemExit("не хватает книг в %s: %s" % (src, ", ".join(missing)))
    if out == src or src in out.parents or out in src.parents:
        raise SystemExit("каталог результата %s и каталог книг %s вложены друг в друга" % (out, src))

    books = {}
    for name in BOOKS:
        try:
            books[name] = hbk.load_book(src / (name + ".hbk"))
        except (hbk.BookError, container.ContainerError, bracket.BracketError) as exc:
            raise SystemExit("%s.hbk: %s" % (name, exc))

    cntx = books["shcntx_ru"]
    referenced = {n.path for n in cntx.nodes.values() if n.path}
    orphans = sorted(p for p in cntx.pages if p not in referenced)
    if orphans:
        raise SystemExit("shcntx_ru.hbk: страниц вне оглавления %d, первые: %s" % (
            len(orphans), ", ".join(orphans[:10])))
    if cntx.missing:
        first = cntx.missing[:10]
        raise SystemExit("shcntx_ru.hbk: узлов без страницы %d, первые: %s" % (
            len(cntx.missing), ", ".join("%d «%s» → %s" % m for m in first)))

    try:
        kinds = layout.classify(cntx)
        files = {}
        for spec in layout.plan_context(cntx):
            files[spec.path] = spec
        for name in BOOKS[1:]:
            layout.plan_prose(books[name], files)
    except layout.LayoutError as exc:
        raise SystemExit(str(exc))

    keywords = {}
    if "present.html" in books["shquery_ru"].pages:
        keywords = prose.bilingual_keywords(books["shquery_ru"].pages["present.html"])

    file_list = list(files.values())

    # первый проход: разбор страниц в записи — до состава, потому что файл раздела и файлы
    # его состава могут идти в любом порядке (§4.4, шаг 7); первая запись файла (Item
    # kind == "page") запоминается для строки состава владельца.
    recs = {}
    first_rec = {}
    for spec in file_list:
        pairs = []
        for item in spec.items:
            if item.kind in ("page", "section"):
                rec = _record_for(item, books, keywords)
                pairs.append((item, rec))
                if item.kind == "page" and spec.path not in first_rec:
                    first_rec[spec.path] = rec
            else:
                pairs.append((item, None))
        recs[spec.path] = pairs

    # второй проход: состав раздела (из уже разобранных записей) и рендер файла целиком.
    rendered = {}
    counts = {}
    for spec in file_list:
        parts, n = [], 0
        for item, rec in recs[spec.path]:
            if item.kind in ("page", "section"):
                if item.kind == "section":
                    # строка «Состав» называет ФАЙЛ, а не первую запись в нём: у файла,
                    # чья первая запись озаглавлена иначе, чем сам файл (например,
                    # «Расширение картинки.md» открывается записью «Расширение декорации
                    # формы для картинки»), английское имя и фраза из записи ведут не туда
                    # — тогда берётся только
                    # заголовок файла, без английского имени и без фразы.
                    comp = layout.composition(file_list, spec.path)
                    lines = []
                    for f in comp:
                        r = first_rec.get(f.path)
                        if r and r.name == f.title:
                            head = render.heading(r)
                            phrase = _first_sentence(r)
                        else:
                            head = f.title
                            phrase = ""
                        lines.append("- " + head + (" — " + phrase if phrase else ""))
                    if lines:
                        rec.fields.append(("Состав", "\n".join(lines)))
                parts.append(render.render_record(rec))
                n += 1
            elif item.kind == "heading":
                parts.append(render.render_heading(item.text))
            else:
                parts.append(render.render_pointer(books[item.book].nodes[item.node].ru, item.text))
                n += 1
        rendered[spec.path] = render.render_file(spec.title, parts)
        counts[spec.path] = n

    for d in OUT_DIRS:
        shutil.rmtree(out / d, ignore_errors=True)
    if (out / "INDEX.md").exists():
        (out / "INDEX.md").unlink()
    for spec in file_list:
        p = out / spec.path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(rendered[spec.path].encode("utf-8"))

    rows, order = {}, []
    for spec in file_list:
        d = spec.dir
        if d not in rows:
            rows[d] = {"section": d.split("/", 1)[0], "dir": d, "files": 0, "records": 0, "books": []}
            order.append(d)
        rows[d]["files"] += 1
        rows[d]["records"] += counts[spec.path]
        for item in spec.items:
            if item.book and item.book not in rows[d]["books"]:
                rows[d]["books"].append(item.book)
    # строки INDEX.md идут по карте разделов §4.1 (порядок OUT_DIRS), а внутри раздела —
    # по первому появлению каталога в дереве; sorted() устойчив, второй ключ не нужен.
    index_rows = []
    for d in sorted(order, key=lambda p: OUT_DIRS.index(rows[p]["section"])):
        r = dict(rows[d])
        r["books"] = "; ".join(b + ".hbk" for b in BOOKS if b in r["books"])
        index_rows.append(r)
    (out / "INDEX.md").write_bytes(render.render_index(
        index_rows, COMMANDS, [(b + ".hbk", books[b].sha256) for b in BOOKS], platform).encode("utf-8"))

    report = []
    for d in OUT_DIRS:
        fs = [s for s in file_list if s.path.split("/", 1)[0] == d]
        report.append("%s: файлов %d, записей %d" % (d, len(fs), sum(counts[s.path] for s in fs)))
    kc = {k: 0 for k in (layout.KIND_MEMBER, layout.KIND_OWNER, layout.KIND_LEAF, layout.KIND_SECTION)}
    for k in kinds.values():
        if k in kc:
            kc[k] += 1
    report.append("страниц shcntx: член %d, владелец %d, объект без членов %d, раздел %d" % (
        kc[layout.KIND_MEMBER], kc[layout.KIND_OWNER], kc[layout.KIND_LEAF], kc[layout.KIND_SECTION]))
    for name in BOOKS[1:]:
        book = books[name]
        items = [it for spec in file_list for it in spec.items if it.book == name]
        pages_n = sum(1 for it in items if it.kind in ("page", "section") and it.node != 0)
        pointers = sum(1 for it in items if it.kind == "pointer")
        outside = sum(1 for spec in file_list if spec.path.endswith("/" + layout.OUTSIDE_FILE + ".md")
                       for it in spec.items if it.book == name)
        report.append("%s: страниц %d, повторных вхождений %d, вне оглавления %d%s" % (
            name, pages_n, pointers, outside, _missing_note(book)))
    if not keywords:
        report.append("shquery_ru: таблицы двуязычных ключевых слов нет, английские имена ключевых слов не проставлены")
    report.append("итого файлов %d, записей %d" % (len(file_list), sum(counts.values())))
    return "\n".join(report) + "\n"


def _platform_from(src):
    """Версия платформы по каталогу установки: `…/8.3.27.1936/bin` → `8.3.27.1936`, иначе просто `8.3`."""
    name = Path(src).resolve().parent.name
    return name if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", name) else "8.3"


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description="Сборка справочника 1С 8.3 для навыка 1c8-doc")
    ap.add_argument("--src", required=True,
                    help="каталог bin установленной платформы: shcntx_ru.hbk, shlang_ru.hbk, shclang_ru.hbk, shquery_ru.hbk")
    ap.add_argument("--out", default=str(root), help="каталог навыка (по умолчанию — тот, где лежит сборщик)")
    ap.add_argument("--platform", default=None,
                    help="версия платформы для INDEX.md; по умолчанию — имя каталога над bin, если это номер версии")
    a = ap.parse_args(argv)
    sys.stdout.write(build(a.src, a.out, a.platform or _platform_from(a.src)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
