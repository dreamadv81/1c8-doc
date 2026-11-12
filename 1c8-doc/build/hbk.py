# build/hbk.py
"""Книга синтакс-помощника: Book, оглавление, страницы."""
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import bracket
import container

SKIP_SUFFIXES = (".st", ".gif", ".png", ".jpg", ".bmp")
SKIP_NAMES = ("__categories__",)

_TAG = re.compile(r"<[^>]+>")


class BookError(ValueError):
    pass


def is_stub(data):
    """Страница без текста: заглушки вроде <html><body></body></html>."""
    text = _TAG.sub(" ", data.decode("utf-8-sig", "replace"))
    return not text.replace("\xa0", " ").strip()


@dataclass
class Node:
    id: int
    parent: int
    children: list
    ru: str
    en: str
    path: str


@dataclass
class Book:
    name: str
    book_id: str
    nodes: dict
    roots: list
    pages: dict
    sha256: str
    missing: list = field(default_factory=list)


def _zip_files(blob, what, name):
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise BookError("%s: %s не ZIP" % (name, what)) from None
    return {i.filename: z.read(i) for i in z.infolist() if not i.is_dir()}


def _node(item, name):
    try:
        nid, parent, n = int(item[0]), int(item[1]), int(item[2])
        children = [int(x) for x in item[3:3 + n]]
        meta = item[3 + n]
        names = {p[0]: p[1] for p in meta[2][2:]}
        path = meta[3] if len(meta) > 3 else ""
    except (IndexError, ValueError, TypeError):
        raise BookError("%s: узел оглавления не разобран: %r" % (name, str(item)[:80])) from None
    ru = names.get("ru", names.get("#", ""))
    return Node(nid, parent, children, ru, names.get("en", ""), path.lstrip("/"))


def load_book_bytes(name, data):
    files = dict(container.list_files(data))
    for part in ("Book", "PackBlock", "FileStorage"):
        if part not in files:
            raise BookError("%s: в контейнере нет элемента %s" % (name, part))
    try:
        book = bracket.parse(files["Book"].decode("utf-8-sig"))
    except bracket.BracketError as exc:
        raise BookError("%s: элемент Book не разобран: %s" % (name, exc)) from None
    book_id = book[1] if len(book) > 1 else ""
    toc_files = _zip_files(files["PackBlock"], "PackBlock", name)
    if not toc_files:
        raise BookError("%s: PackBlock пуст" % name)
    toc_name = max(toc_files, key=lambda k: len(toc_files[k]))
    try:
        parsed = bracket.parse(toc_files[toc_name].decode("utf-8-sig"))
    except bracket.BracketError as exc:
        raise BookError("%s: оглавление (%s в PackBlock) не разобрано: %s" % (name, toc_name, exc)) from None
    try:
        declared = int(parsed[0])
    except (IndexError, ValueError):
        raise BookError("%s: первое число оглавления (%s в PackBlock) не число: %r" % (name, toc_name, parsed[0] if parsed else parsed)) from None
    nodes = {}
    roots = []
    for item in parsed[1:]:
        node = _node(item, name)
        nodes[node.id] = node
        if node.parent == 0:
            roots.append(node.id)
    if declared != len(nodes):
        raise BookError("%s: в оглавлении объявлено %d узлов, разобрано %d" % (name, declared, len(nodes)))
    pages = {}
    for fname, body in _zip_files(files["FileStorage"], "FileStorage", name).items():
        base = fname.rsplit("/", 1)[-1]
        if base in SKIP_NAMES or fname.lower().endswith(SKIP_SUFFIXES):
            continue
        pages[fname] = body
    # Путь оглавления без страницы в FileStorage — не отказ здесь: у shquery_ru таких узлов
    # два («Ключевые слова и функции» → KeyWordsFunctions, «Операторы» → Operations), и это
    # свойство книги, а не брак разбора. Узел превращается в папку без страницы (path = ""),
    # адрес запоминается в missing по порядку оглавления; решение, отказывать ли книге с
    # непустым missing (у shcntx — да), принимает build_docs.py.
    missing = []
    for node in nodes.values():
        if node.path and node.path not in pages:
            missing.append((node.id, node.ru, node.path))
            node.path = ""
    return Book(name, book_id, nodes, roots, pages, hashlib.sha256(data).hexdigest(), missing)


def load_book(path):
    path = Path(path)
    return load_book_bytes(path.stem, path.read_bytes())


def toc_path(book, node_id):
    out = []
    while node_id in book.nodes:
        node = book.nodes[node_id]
        out.append(node.ru)
        node_id = node.parent
    return list(reversed(out))
