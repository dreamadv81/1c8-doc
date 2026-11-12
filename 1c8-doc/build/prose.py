# build/prose.py
"""HTML малых книг помощника → текст."""
from html.parser import HTMLParser

import hbk

_SKIP_TAGS = ("head", "script", "style")
_BLOCK_TAGS = ("p", "div", "blockquote", "li", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "table", "tr", "td", "th", "ul", "ol")


class _Prose(HTMLParser):
    """Блоки: ('text', str) | ('code', str) | ('table', [[str]]). Заголовок h1 — отдельно."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = None
        self.blocks = []
        self.buf = []          # куски текущего блока
        self.kind = "text"     # 'text' | 'code' | 'h' | 'li'
        self.skip = []         # стек пропускаемых тегов
        self.font_depth = 0    # вложенность <font> с Courier New
        self.pre = 0
        self.tables = []       # стек таблиц: [rows]; row = [cells]; cell = [blocks]
        self.in_h1 = False
        self.h1 = []
        self.done = False      # после <HR> — подвал «Методическая информация», в тело не идёт

    def _flush(self):
        text = "".join(self.buf)
        self.buf = []
        kind = self.kind
        self.kind = "text"
        lines = [l.rstrip() for l in text.replace("\xa0", " ").split("\n")]
        if kind == "code":
            while lines and not lines[0].strip():
                lines.pop(0)
            while lines and not lines[-1].strip():
                lines.pop()
            if lines:
                self._emit(("code", "\n".join(lines)))
            return
        lines = [" ".join(l.split()) for l in lines]
        lines = [l for l in lines if l]
        if not lines:
            return
        if kind == "h":
            self._emit(("text", "**" + " ".join(lines) + "**"))
        elif kind == "li":
            self._emit(("text", "- " + " ".join(lines)))
        else:
            self._emit(("text", "\n".join(lines)))

    def _emit(self, block):
        if self.tables:
            row = self.tables[-1][-1] if self.tables[-1] else None
            if row is not None and row:
                row[-1].append(block)
                return
        self.blocks.append(block)

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if self.skip:
            return
        if tag == "hr":
            self._flush()
            self.done = True
            return
        a = dict(attrs)
        # элемент с классом V8SH_title дублирует <h1> (заголовок страницы второй раз,
        # обычно в <div>/<p> сразу после него) — в тело идти не должен, пропускается
        # целиком, как head/script/style.
        if tag in _SKIP_TAGS or "V8SH_title" in (a.get("class") or "").split():
            self.skip.append(tag)
            return
        if tag == "h1":
            if self.title is None:
                self.in_h1 = True
                return
        if tag in _BLOCK_TAGS:
            self._flush()
        if tag == "br":
            self.buf.append("\n")
        elif tag in ("h2", "h3", "h4", "h5", "h6"):
            self.kind = "h"
        elif tag == "li":
            self.kind = "li"
        elif tag == "pre":
            self.pre += 1
            self.kind = "code"
        elif tag == "p" and (a.get("class") or "") == "SourceCode":
            self.kind = "code"
        elif tag == "font" and "courier" in (a.get("face") or "").lower():
            self.font_depth += 1
            if not "".join(self.buf).strip():
                self.kind = "code"
        elif tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self.tables[-1].append([])
        elif tag in ("td", "th") and self.tables and self.tables[-1]:
            self.tables[-1][-1].append([])

    def handle_endtag(self, tag):
        if self.done:
            return
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
            return
        if tag == "h1" and self.in_h1:
            self.in_h1 = False
            self.title = " ".join("".join(self.h1).split())
            return
        if tag == "font" and self.font_depth:
            self.font_depth -= 1
            return
        if tag == "pre":
            self.pre = max(0, self.pre - 1)
        if tag in _BLOCK_TAGS:
            self._flush()
        if tag == "table" and self.tables:
            rows = self.tables.pop()
            self._emit_table(rows)

    def _emit_table(self, rows):
        rows = [[cell for cell in row] for row in rows if row]
        if not rows:
            return
        if all(len(row) == 1 for row in rows):
            for row in rows:
                for block in row[0]:
                    self._emit(block)
            return
        out = []
        for row in rows:
            cells = []
            for cell in row:
                parts = []
                for kind, val in cell:
                    if kind == "table":
                        parts.extend(" ".join(r) for r in val)
                    else:
                        parts.append(" ".join(val.split()))
                cells.append(" ".join(p for p in parts if p).replace("|", "\\|"))
            out.append(cells)
        self._emit(("table", out))

    def handle_data(self, data):
        if self.done:
            return
        if self.skip:
            return
        if self.in_h1:
            self.h1.append(data)
            return
        self.buf.append(data)


def _render(blocks, code_lang):
    out = []
    for kind, val in blocks:
        if kind == "code":
            if out and out[-1].startswith("```") and out[-1].endswith("```"):
                out[-1] = out[-1][:-3].rstrip("\n") + "\n" + val + "\n```"
            else:
                out.append("```%s\n%s\n```" % (code_lang, val))
        elif kind == "table":
            width = max(len(r) for r in val)
            rows = [r + [""] * (width - len(r)) for r in val]
            lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
            lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
            out.append("\n".join(lines))
        else:
            if out and out[-1].startswith("- ") and val.startswith("- "):
                out[-1] = out[-1] + "\n" + val
            else:
                out.append(val)
    return "\n\n".join(out)


def html_to_text(html, code_lang="bsl"):
    if hbk.is_stub(html):
        return "", ""
    p = _Prose()
    p.feed(html.decode("utf-8-sig", "replace"))
    p.close()
    p._flush()
    return p.title or "", _render(p.blocks, code_lang)


def bilingual_keywords(html):
    p = _Prose()
    p.feed(html.decode("utf-8-sig", "replace"))
    p.close()
    out = {}
    for kind, rows in p.blocks:
        if kind != "table":
            continue
        for row in rows:
            if len(row) >= 2 and row[0] and row[1] and "написание" not in row[0].lower():
                out[row[0].strip()] = row[1].strip()
    return out
