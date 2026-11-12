# build/layout.py
"""Раскладка: виды узлов, карта корней, узлы → каталоги и файлы."""
from dataclasses import dataclass, field

import hbk

MEMBER_DIRS = ("properties", "methods", "events", "ctors", "fields", "params", "formparams")
GROUP_NAMES = {"properties": "Свойства", "methods": "Методы", "events": "События",
               "ctors": "Конструкторы", "fields": "Поля", "params": "Параметры",
               "formparams": "Параметры формы"}
VALUE_ROOTS = ("Системные перечисления", "Системные наборы значений")
KIND_MEMBER, KIND_OWNER, KIND_LEAF, KIND_SECTION, KIND_GROUP, KIND_SUBDIR = (
    "member", "owner", "leaf", "section", "group", "subdir")
ROOT_MAP = {
    ("shcntx_ru", "Глобальный контекст"): "global",
    ("shcntx_ru", "Универсальные коллекции значений"): "collections",
    ("shcntx_ru", "Общие объекты"): "objects",
    ("shcntx_ru", "Прикладные объекты"): "applied",
    ("shcntx_ru", "Интерфейс (управляемый)"): "forms",
    ("shcntx_ru", "Интерфейс (обычный)"): "forms-ordinary",
    ("shcntx_ru", "Системные перечисления"): "enums",
    ("shcntx_ru", "Системные наборы значений"): "values",
    ("shcntx_ru", "Работа с запросами"): "queries",
    ("shcntx_ru", "Средства интеграции и администрирования"): "admin",
    ("shlang_ru", "Общее описание встроенного языка"): "lang",
    ("shquery_ru", "Работа с запросами"): "queries",
    ("shclang_ru", "Встроенный язык", "Общее описание встроенного языка"): "lang",
    ("shclang_ru", "Встроенный язык", "Общие объекты"): "objects",
    ("shclang_ru", "Встроенный язык", "Работа с запросами"): "queries",
}
OUTSIDE_FILE = "Вне оглавления"
PROSE_HEADING = "Из описания языка"
_FORBIDDEN = '/\\:*?"<>|'


class LayoutError(ValueError):
    pass


@dataclass
class Item:
    kind: str
    node: int = 0
    text: str = ""
    book: str = ""


@dataclass
class FileSpec:
    path: str
    title: str
    items: list = field(default_factory=list)

    @property
    def dir(self):
        return self.path.rsplit("/", 1)[0]


def safe_name(name):
    """Имя файла или каталога: запрещённые в имени символы (`/\\:*?"<>|`) заменяются
    на «-»; пробелы и точки по краям снимаются — имя книги в оглавлении
    иногда несёт хвостовой пробел (например, «Инструкции препроцессора »), а Windows
    такое имя файла не выкладывает."""
    replaced = "".join("-" if ch in _FORBIDDEN else ch for ch in name)
    return replaced.strip(" .")


def member_dir(path):
    """Каталог члена — любой сегмент КАТАЛОГА страницы (без имени файла), берётся
    ближайший к файлу. Не всегда непосредственный родитель: функции глобального
    контекста лежат в methods/catalogNNNN/Файл.html — сама методы-группа на сегмент
    выше родительской папки страницы."""
    segs = path.split("/")[:-1]
    for seg in reversed(segs):
        if seg in MEMBER_DIRS:
            return seg
    return ""


def _depth(book, nid):
    d = 0
    while book.nodes[nid].parent in book.nodes:
        nid = book.nodes[nid].parent
        d += 1
    return d


def classify(book):
    kinds = {}
    order = sorted(book.nodes, key=lambda i: -_depth(book, i))
    for nid in order:
        n = book.nodes[nid]
        ch = [kinds[c] for c in n.children if c in kinds]
        if not n.path:
            if not n.children:
                raise LayoutError("узел %d «%s»: папка без страницы и без детей" % (nid, n.ru))
            if all(k == KIND_MEMBER for k in ch):
                kinds[nid] = KIND_GROUP
            elif KIND_MEMBER not in ch and KIND_GROUP not in ch:
                kinds[nid] = KIND_SUBDIR
            else:
                raise LayoutError("узел %d «%s»: папка со смешанными детьми (члены и не члены)" % (nid, n.ru))
        elif not n.children:
            kinds[nid] = KIND_MEMBER if member_dir(n.path) else KIND_LEAF
        elif KIND_MEMBER in ch:
            if all(k == KIND_MEMBER for k in ch):
                kinds[nid] = KIND_OWNER
            else:
                raise LayoutError("узел %d «%s»: у страницы и члены, и не члены" % (nid, n.ru))
        elif all(k == KIND_GROUP for k in ch):
            kinds[nid] = KIND_OWNER
        else:
            kinds[nid] = KIND_SECTION
    return kinds


def _root_dir(book, root):
    key = (book.name, book.nodes[root].ru)
    if key not in ROOT_MAP:
        raise LayoutError("%s: корень «%s» не назван в карте разделов" % (book.name, book.nodes[root].ru))
    return ROOT_MAP[key]


class _Files:
    def __init__(self):
        self.list = []
        self.by_path = {}

    def add(self, path, title, items, nid):
        if path in self.by_path:
            raise LayoutError("два файла на один путь %s (узлы %s и %d)" % (path, self.by_path[path][1], nid))
        spec = FileSpec(path, title, items)
        self.list.append(spec)
        self.by_path[path] = (spec, nid)
        return spec


def _member_items(book, kinds, owner, root_ru):
    items = []
    last = None
    for c in book.nodes[owner].children:
        node = book.nodes[c]
        if kinds[c] == KIND_GROUP:
            items.append(Item("heading", 0, node.ru, book.name))
            items.extend(Item("page", m, "", book.name) for m in node.children)
            last = None
        else:
            d = member_dir(node.path)
            head = "Значения" if d == "properties" and root_ru in VALUE_ROOTS else GROUP_NAMES[d]
            if head != last:
                items.append(Item("heading", 0, head, book.name))
                last = head
            items.append(Item("page", c, "", book.name))
    return items


def plan_context(book):
    kinds = classify(book)
    files = _Files()

    def walk(nid, dirpath, root_ru):
        node = book.nodes[nid]
        kind = kinds[nid]
        if kind == KIND_SECTION:
            here = dirpath if node.parent == 0 else dirpath + "/" + safe_name(node.ru)
            path = here + "/" + safe_name(node.ru) + ".md"
            spec = files.add(path, node.ru.strip(), [Item("section", nid, "", book.name)], nid)
            for c in node.children:
                walk(c, here, root_ru)
            return spec
        if kind == KIND_SUBDIR:
            here = dirpath + "/" + safe_name(node.ru)
            for c in node.children:
                walk(c, here, root_ru)
            return None
        path = dirpath + "/" + safe_name(node.ru) + ".md"
        if kind == KIND_GROUP:
            return files.add(path, node.ru.strip(), [Item("page", m, "", book.name) for m in node.children], nid)
        if kind == KIND_LEAF:
            return files.add(path, node.ru.strip(), [Item("page", nid, "", book.name)], nid)
        items = [Item("page", nid, "", book.name)] + _member_items(book, kinds, nid, root_ru)
        parent = book.nodes.get(node.parent)
        if parent is not None and kinds.get(node.parent) == KIND_SECTION and parent.ru == node.ru and path in files.by_path:
            # владелец-тёзка своего раздела («XBase» в «XBase») идёт в файл раздела
            files.by_path[path][0].items.extend(items)
            return files.by_path[path][0]
        return files.add(path, node.ru.strip(), items, nid)

    for root in book.roots:
        walk(root, _root_dir(book, root), book.nodes[root].ru)
    return files.list


def composition(files, section_path):
    d = section_path.rsplit("/", 1)[0]
    return [f for f in files if f.dir == d and f.path != section_path]


def _mapped(book):
    """[(узел, каталог)] — корни или (у shclang) дети корней по карте §4.1."""
    out = []
    for root in book.roots:
        r = book.nodes[root]
        if (book.name, r.ru) in ROOT_MAP:
            out.append((root, ROOT_MAP[(book.name, r.ru)]))
            continue
        if not r.children:
            raise LayoutError("%s: корень «%s» не назван в карте разделов и без детей" % (book.name, r.ru))
        for c in r.children:
            key = (book.name, r.ru, book.nodes[c].ru)
            if key not in ROOT_MAP:
                raise LayoutError("%s: корень «%s» в карте не назван, узел «%s › %s» тоже не назван в карте разделов" % (book.name, r.ru, r.ru, book.nodes[c].ru))
            out.append((c, ROOT_MAP[key]))
    if not out:
        raise LayoutError("%s: ни один корень не назван в карте разделов" % book.name)
    return out


def plan_prose(book, files):
    new = []
    seen = {}      # путь страницы → (путь файла, ru первого узла)
    used = set()

    def has_page(n):
        return bool(n.path) and not hbk.is_stub(book.pages[n.path])

    def page_item(n, path):
        used.add(n.path)
        if n.path in seen:
            fpath, ru = seen[n.path]
            return Item("pointer", n.id, "См.: %s, запись «%s»" % (fpath, ru), book.name)
        seen[n.path] = (path, n.ru)
        return Item("page", n.id, "", book.name)

    def subtree(nid, path, items):
        n = book.nodes[nid]
        if has_page(n):
            items.append(page_item(n, path))
        elif n.path:
            used.add(n.path)
        for c in n.children:
            cn = book.nodes[c]
            if not cn.path and cn.children:
                items.append(Item("heading", 0, cn.ru, book.name))
            subtree(c, path, items)

    def add(path, title, items, nid):
        if path in files:
            existing = files[path]
            prev = next((i.node for i in existing.items if i.node), None)
            if prev is not None:
                raise LayoutError("два файла на один путь %s (узлы %d и %d «%s»)" % (path, prev, nid, title))
            raise LayoutError("два файла на один путь %s (узел %d «%s»)" % (path, nid, title))
        spec = FileSpec(path, title, items)
        files[path] = spec
        new.append(spec)

    first_dir = None
    for mid, d in _mapped(book):
        first_dir = first_dir or d
        m = book.nodes[mid]
        if has_page(m):
            path = d + "/" + safe_name(m.ru) + ".md"
            if path in files:
                files[path].items.append(page_item(m, path))
            else:
                used.add(m.path)
                seen[m.path] = (path, m.ru)
                add(path, m.ru.strip(), [Item("section", mid, "", book.name)], mid)
        elif m.path:
            used.add(m.path)
        for c in m.children:
            cn = book.nodes[c]
            if not cn.path and not cn.children:
                continue
            section_path = "%s/%s/%s.md" % (d, safe_name(cn.ru), safe_name(cn.ru))
            if section_path in files:
                items = [Item("heading", 0, PROSE_HEADING, book.name)]
                subtree(c, section_path, items)
                files[section_path].items.extend(items)
                continue
            path = d + "/" + safe_name(cn.ru) + ".md"
            items = []
            subtree(c, path, items)
            add(path, cn.ru.strip(), items, c)
    outside = [p for p in sorted(book.pages) if p not in used and not hbk.is_stub(book.pages[p])]
    if outside:
        path = first_dir + "/" + OUTSIDE_FILE + ".md"
        add(path, OUTSIDE_FILE, [Item("page", 0, p, book.name) for p in outside], 0)
    return new
