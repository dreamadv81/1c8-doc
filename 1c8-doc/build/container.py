# build/container.py
"""Контейнер 1С v8 (.hbk, .cf, .epf) стандартной библиотекой.

Заголовок файла 16 байт; с адреса 16 — блок оглавления: тройки int32 (адрес заголовка
элемента, адрес тела, 7fffffff). Заголовок блока — 31 байт:
\\r\\n<8 hex длины документа> <8 hex длины блока> <8 hex адреса следующего> \\r\\n.
Тела в книгах помощника не сжаты."""
import struct
from pathlib import Path

END = 0x7FFFFFFF
_HEADER = 31


class ContainerError(ValueError):
    pass


def _block(data, addr):
    h = data[addr:addr + _HEADER]
    if len(h) < _HEADER or h[:2] != b"\r\n" or h[-2:] != b"\r\n":
        raise ContainerError("нет заголовка блока по адресу 0x%x" % addr)
    try:
        doc_len, blk_len, nxt = (int(x, 16) for x in h[2:-2].split())
    except ValueError:
        raise ContainerError("испорчен заголовок блока по адресу 0x%x: %r" % (addr, h)) from None
    return doc_len, blk_len, nxt, addr + _HEADER


def read_doc(data, addr):
    """Цепочка блоков от addr → байты документа длиной из первого заголовка."""
    doc_len, blk_len, nxt, body = _block(data, addr)
    out = bytearray(data[body:body + blk_len])
    seen = {addr}
    while nxt != END:
        if nxt in seen:
            raise ContainerError("цепочка блоков зациклена на 0x%x" % nxt)
        seen.add(nxt)
        _, blk_len, nxt, body = _block(data, nxt)
        out += data[body:body + blk_len]
    return bytes(out[:doc_len])


def list_files(data):
    """[(имя, тело)] в порядке оглавления контейнера. Первое поле заголовка файла — адрес
    списка свободных страниц — не читается: у 81 книги из 82 он не пуст, и именно на нём
    падает pip-овский v8unpack."""
    if len(data) < 16:
        raise ContainerError("файл короче заголовка контейнера (16 байт)")
    index = read_doc(data, 16)
    files = []
    for off in range(0, len(index) - len(index) % 12, 12):
        hdr_addr, body_addr, _ = struct.unpack("<III", index[off:off + 12])
        hdr = read_doc(data, hdr_addr)
        name = hdr[20:].decode("utf-16-le", "replace").split("\x00", 1)[0]
        body = read_doc(data, body_addr) if body_addr != END else b""
        files.append((name, body))
    return files


def read_container(path):
    return dict(list_files(Path(path).read_bytes()))
