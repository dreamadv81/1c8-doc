# build/page.py
"""Страница shcntx → запись."""
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

ORDER = ["Синтаксис", "Параметры", "Возвращает", "Использование", "Описание", "Элементы коллекции",
         "Свойства", "Методы", "События", "Конструкторы", "Значения", "Поля", "Параметры формы",
         "Доступность", "Версия", "Устарело", "Примечание", "Пример", "См. также"]
LABELS = {"Синтаксис": "Синтаксис", "Параметры": "Параметры", "Возвращаемое значение": "Возвращает",
          "Описание": "Описание", "Описание варианта метода": "Описание варианта",
          "Использование": "Использование", "Доступность": "Доступность",
          "Использование в версии": None, "Примечание": "Примечание", "Пример": "Пример",
          "См. также": "См. также", "Свойства": "Свойства", "Методы": "Методы", "События": "События",
          "Конструкторы": "Конструкторы", "Значения": "Значения", "Элементы коллекции": "Элементы коллекции",
          "Поля": "Поля", "Параметры формы": "Параметры формы",
          # «Замечание» — синоним «Примечание»: найдено при сборке 2026-09-10 на 152 страницах
          # shcntx_ru (пример — objects/catalog125/catalog279/object358/events/FormGetProcessing529.html),
          # заранее известна не была. Обе метки на одной странице склеиваются
          # переводом строки — этим занимается общая сборка fields (повтор метки конкатенируется).
          "Замечание": "Примечание"}
VARIANT_PREFIX = "Вариант синтаксиса:"
VARIANT_LABELS = ("Синтаксис", "Параметры", "Описание варианта")
LIST_LABELS = ("Свойства", "Методы", "События", "Конструкторы", "Значения", "Поля", "Параметры формы")
_SKIP = "_skip"
_PARAM_RUBRIC = re.compile(r"^(.+?) \((обязательный|необязательный)\)$")
_TITLE_EN = re.compile(r"^(.*?)\s*\(([A-Za-z0-9<][^()]*)\)\s*$")
_CLASSES = {"V8SH_pagetitle": "title", "V8SH_title": "owner", "V8SH_heading": "member",
            "V8SH_chapter": "chapter", "V8SH_rubric": "rubric", "V8SH_versionInfo": "version"}
_RUBRIC = "\x00"
_SHOW_STYLE_SUFFIX = "_SHOW_STYLE__"
_SINCE_CLASS = "__SINCE_SHOW_STYLE__"
_DEPRECATED_CLASS = "__DEPRECATED_SHOW_STYLE__"


class PageError(ValueError):
    pass


@dataclass
class Record:
    name: str
    name_en: str = ""
    fields: list = field(default_factory=list)
    variants: list = field(default_factory=list)
    prose: str = ""
    source: str = ""
    code_lang: str = "bsl"


def split_title(title):
    title = " ".join(title.split())
    m = _TITLE_EN.match(title)
    name, en = (m.group(1), m.group(2)) if m else (title, "")
    pre = "Глобальный контекст."
    if name.startswith(pre) and len(name) > len(pre):
        name = name[len(pre):]
    pre = "Global context."
    if en.startswith(pre) and len(en) > len(pre):
        en = en[len(pre):]
    return name, en


class _Tokens(HTMLParser):
    """Плоский список событий страницы: (вид, текст). Виды — title/owner/member/chapter/rubric/
    version (элементы по классу V8SH_*), deprecated (блок __DEPRECATED_SHOW_STYLE__, с
    сохранёнными переводами строк — как у обычного текста, а не схлопнутый в одну строку),
    bad_show_style (класс div с хвостом _SHOW_STYLE__, кроме двух известных — несёт имя класса,
    parse_page на нём отказывает) и text; переводы строк приходят текстом '\\n', пункты списка —
    '\\n- '."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events = []
        self.skip_tag = None
        self.skip_depth = 0
        self.cap_kind = None
        self.cap_tag = None
        self.cap_depth = 0
        self.cap = []
        self.block_kind = None
        self.block_tag = None
        self.block_depth = 0
        self.block_buf = []
        self.done = False

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if self.skip_tag:
            if tag == self.skip_tag:
                self.skip_depth += 1
            return
        if self.block_kind:
            if tag == self.block_tag:
                self.block_depth += 1
            if tag in ("br", "p", "tr", "div", "table"):
                self.block_buf.append("\n")
            elif tag == "li":
                self.block_buf.append("\n- ")
            return
        cls = dict(attrs).get("class") or ""
        if tag == "hr":
            self.done = True
            return
        if tag == "head" or (tag == "div" and cls == _SINCE_CLASS):
            self.skip_tag, self.skip_depth = tag, 1
            return
        if tag == "div" and cls == _DEPRECATED_CLASS:
            self.block_kind, self.block_tag, self.block_depth, self.block_buf = "deprecated", tag, 1, []
            return
        if tag == "div" and cls.endswith(_SHOW_STYLE_SUFFIX):
            self.events.append(("bad_show_style", cls))
            self.skip_tag, self.skip_depth = tag, 1
            return
        if self.cap_kind:
            if tag == self.cap_tag:
                self.cap_depth += 1
            return
        kind = _CLASSES.get(cls)
        if kind:
            self.cap_kind, self.cap_tag, self.cap_depth, self.cap = kind, tag, 1, []
            return
        if tag in ("br", "p", "tr", "div", "table"):
            self.events.append(("text", "\n"))
        elif tag == "li":
            self.events.append(("text", "\n- "))

    def handle_endtag(self, tag):
        if self.done:
            return
        if self.skip_tag:
            if tag == self.skip_tag:
                self.skip_depth -= 1
                if self.skip_depth == 0:
                    self.skip_tag = None
            return
        if self.block_kind:
            if tag == self.block_tag:
                self.block_depth -= 1
                if self.block_depth == 0:
                    self.events.append((self.block_kind, "".join(self.block_buf)))
                    self.block_kind = None
            elif tag in ("p", "tr", "div", "ul", "table"):
                self.block_buf.append("\n")
            return
        if self.cap_kind:
            if tag == self.cap_tag:
                self.cap_depth -= 1
                if self.cap_depth == 0:
                    self.events.append((self.cap_kind, " ".join("".join(self.cap).split())))
                    self.cap_kind = None
            return
        if tag in ("p", "tr", "div", "ul", "table"):
            self.events.append(("text", "\n"))

    def handle_data(self, data):
        if self.done or self.skip_tag:
            return
        if self.block_kind:
            self.block_buf.append(data)
        elif self.cap_kind:
            self.cap.append(data)
        else:
            self.events.append(("text", data))


def _norm_label(text):
    return text.rstrip(": ").strip()


def _lines(text):
    return [" ".join(l.split()) for l in text.replace("\xa0", " ").split("\n")]


def _plain(text):
    return "\n".join(l for l in _lines(text) if l)


def _example(text):
    lines = text.split("\n")
    # пустые строки по краям (от <table>/<tr>/... вокруг кода) режем ДО снятия артефакта —
    # str.strip() распознаёт \xa0 как пробельный символ так же, как обычный пробел, порядок
    # тут не важен, а important — что после обрезки в lines[0] лежит первая строка КОДА.
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    # разметка HBK кладёт перед первой строкой кода один пробел-артефакт — литеральный, сразу
    # после <font face="Courier New">, это не отступ кода. Настоящий отступ идёт через &nbsp;
    # (после разбора сущностей — символ \xa0), и его снимать нельзя: заменять \xa0 на пробел
    # можно только ПОСЛЕ того, как снят литеральный пробел-артефакт — иначе неотличимы.
    if lines and lines[0].startswith(" "):
        lines[0] = lines[0][1:]
    lines = [l.replace("\xa0", " ").rstrip() for l in lines]
    return "\n".join(lines)


def _param_lines(text):
    """Строки одного параметра: обычные строки склеены пробелом, пункты «- » — отдельно."""
    out = []
    for l in _lines(text):
        if not l:
            continue
        if l.startswith("- ") or not out or out[-1].startswith("- "):
            out.append(l)
        else:
            out[-1] += " " + l
    return out


def _params(text):
    out = []
    chunks = text.split(_RUBRIC)
    head = _plain(chunks[0])
    if head:
        out.append(head)
    for chunk in chunks[1:]:
        name, _, rest = chunk.partition("\n")
        lines = _param_lines(rest)
        first = name.strip()
        if lines:
            first += " — " + lines[0]
        out.append(first)
        out.extend(lines[1:])
    return "\n".join(out)


def _value(label, text):
    if label == "Пример":
        return _example(text)
    if label == "Параметры":
        return _params(text)
    if label in LIST_LABELS:
        return ", ".join(l for l in _lines(text) if l)
    if label == "См. также":
        return "; ".join(l for l in _lines(text) if l)
    return _plain(text)


def parse_page(html, *, in_params=False):
    tok = _Tokens()
    tok.feed(html.decode("utf-8-sig", "replace"))
    tok.close()
    title = next((t for k, t in tok.events if k == "title"), None)
    if title is None:
        raise PageError("нет заголовка V8SH_pagetitle")
    name, name_en = split_title(title)
    rec = Record(name, name_en)
    segments = [[None, -1, []]]     # [метка, индекс варианта или -1, куски текста]
    vidx = -1
    versions = []
    deprecated = ""
    param_field = None
    for kind, text in tok.events:
        if kind in ("title", "owner", "member"):
            continue
        if kind == "bad_show_style":
            raise PageError("неизвестный класс блока «%s» на странице «%s»" % (text, title))
        if kind == "version":
            # страница несёт сколько угодно пометок версии (найдено на 1 271 странице
            # shcntx_ru при сборке 2026-09-10): «Доступен, начиная с версии…», «Описание
            # изменено в версии…», «Не рекомендуется использовать, начиная с версии…» —
            # разные факты, все сохраняются в порядке появления; дословный повтор
            # (тот же текст ещё раз) отбрасывается, остальное склеивается переводом строки.
            if text not in versions:
                versions.append(text)
            continue
        if kind == "deprecated":
            deprecated = deprecated or text
            continue
        if kind == "rubric":
            segments[-1][2].append(_RUBRIC + text + "\n")
            continue
        if kind == "chapter":
            raw = _norm_label(text)
            if raw.startswith(VARIANT_PREFIX):
                rec.variants.append((raw[len(VARIANT_PREFIX):].strip(), []))
                vidx = len(rec.variants) - 1
                segments.append([_SKIP, vidx, []])
                continue
            if raw in LABELS:
                label = LABELS[raw] or _SKIP
            elif in_params and _PARAM_RUBRIC.match(raw):
                param_field = ("Параметр", raw)
                label = "Описание"
            else:
                raise PageError("неизвестная метка «%s» на странице «%s»" % (raw, title))
            if vidx >= 0 and label not in VARIANT_LABELS:
                vidx = -1
            segments.append([label, vidx, []])
            continue
        segments[-1][2].append(text)
    fields = {}
    for label, vi, parts in segments:
        text = "".join(parts)
        if label == _SKIP:
            continue
        if label is None:
            if not _plain(text):
                continue
            label = "Описание"
        value = _value(label, text)
        if not value:
            continue
        if vi >= 0:
            rec.variants[vi][1].append((label, value))
        elif label in fields:
            fields[label] += "\n" + value
        else:
            fields[label] = value
    if versions:
        fields["Версия"] = "\n".join(versions)
    if deprecated:
        value = _plain(deprecated)
        if value:
            fields["Устарело"] = value
    rec.fields = ([param_field] if param_field else []) + [(k, fields[k]) for k in ORDER if k in fields]
    return rec
