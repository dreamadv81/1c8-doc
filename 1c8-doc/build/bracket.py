# build/bracket.py
"""Скобкофайл 1С: {a,b,{c,"d"}} → вложенные списки строк."""


class BracketError(ValueError):
    pass


def parse(text):
    if text.startswith("﻿"):
        text = text[1:]
    pos = 0
    n = len(text)

    def skip():
        nonlocal pos
        while pos < n and text[pos] in " \t\r\n,":
            pos += 1

    def value():
        nonlocal pos
        skip()
        if pos >= n:
            raise BracketError("неожиданный конец скобкофайла на позиции %d" % pos)
        c = text[pos]
        if c == "{":
            brace_pos = pos
            pos += 1
            items = []
            while True:
                skip()
                if pos >= n:
                    raise BracketError("незакрытая скобка, открыта на позиции %d" % brace_pos)
                if text[pos] == "}":
                    pos += 1
                    return items
                items.append(value())
        if c == '"':
            quote_pos = pos
            pos += 1
            out = []
            while True:
                if pos >= n:
                    raise BracketError("незакрытая кавычка, открыта на позиции %d" % quote_pos)
                ch = text[pos]
                if ch == '"':
                    if pos + 1 < n and text[pos + 1] == '"':
                        out.append('"')
                        pos += 2
                        continue
                    pos += 1
                    return "".join(out)
                out.append(ch)
                pos += 1
        start = pos
        while pos < n and text[pos] not in " \t\r\n,{}":
            pos += 1
        if start == pos:
            raise BracketError("неожиданный знак %r на позиции %d" % (c, pos))
        return text[start:pos]

    result = value()
    skip()
    if pos != n:
        raise BracketError("лишний текст после скобкофайла на позиции %d" % pos)
    return result
