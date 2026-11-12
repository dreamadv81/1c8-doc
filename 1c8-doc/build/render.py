# build/render.py
"""Запись → markdown; файл; INDEX.md."""

_HEAD_FIELDS = ("Параметр", "Синтаксис")


def _norm(s):
    return (s or "").lower().replace("ё", "е")


def heading(rec):
    if rec.name_en and _norm(rec.name) != _norm(rec.name_en):
        return "%s (%s)" % (rec.name, rec.name_en)
    return rec.name


def _field(label, value, code_lang):
    value = value.strip("\n")
    if label == "Пример":
        return "Пример:\n```%s\n%s\n```\n" % (code_lang, value)
    if "\n" in value:
        return "%s:\n%s\n" % (label, value)
    if label == "Синтаксис":
        return "Синтаксис: `%s`\n" % value
    return "%s: %s\n" % (label, value)


def render_record(rec):
    out = ["## %s\n\n" % heading(rec)]
    if rec.prose:
        out.append(rec.prose.strip("\n") + "\n")
    # поля печатаются и у прозаической записи: у записи раздела из малой книги есть «Состав»
    head = [f for f in rec.fields if f[0] in _HEAD_FIELDS]
    rest = [f for f in rec.fields if f[0] not in _HEAD_FIELDS]
    for label, value in head:
        out.append(_field(label, value, rec.code_lang))
    for name, fields in rec.variants:
        out.append("Вариант: %s\n" % name)
        for label, value in fields:
            out.append(_field(label, value, rec.code_lang))
    for label, value in rest:
        out.append(_field(label, value, rec.code_lang))
    if rec.source:
        out.append("Источник: %s\n" % rec.source)
    return "".join(out)


def render_pointer(name, text):
    return "## %s\n\n%s\n" % (name, text)


def render_heading(text):
    return "### %s\n" % text


def render_file(title, parts):
    return "# %s\n" % title + "".join("\n" + p for p in parts)


def render_index(rows, commands, books, platform):
    out = ["# Оглавление справочника 1С 8.3\n\n"]
    for c in commands:
        out.append("- `%s`\n" % c)
    out.append("\nСобрано из синтакс-помощника платформы `%s`: %s.\n\n" % (
        platform, ", ".join("`%s` `%s`" % (n, s) for n, s in books)))
    out.append("| Раздел | Каталог | Файлов | Записей | Книги |\n|---|---|---:|---:|---|\n")
    files = records = 0
    for r in rows:
        out.append("| %s | [%s](<%s/>) | %d | %d | %s |\n" % (r["section"], r["dir"], r["dir"], r["files"], r["records"], r["books"]))
        files += r["files"]
        records += r["records"]
    out.append("| **Итого** | | %d | %d | |\n" % (files, records))
    return "".join(out)
