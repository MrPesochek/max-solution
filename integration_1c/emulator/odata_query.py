from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

Predicate = Callable[[dict[str, Any]], bool]


class QueryError(Exception):
    pass


_TOKEN_RE = re.compile(
    r"""\s*(?:
        (?P<guid>guid'[0-9a-fA-F-]{36}')
      | (?P<datetime>datetime'[^']*')
      | (?P<string>'(?:[^']|'')*')
      | (?P<number>-?\d+(?:\.\d+)?)
      | (?P<paren>[(),])
      | (?P<name>[^\s(),']+)
    )""",
    re.VERBOSE,
)
_COMPARISONS = {"eq", "ne", "gt", "ge", "lt", "le"}


@dataclass(frozen=True)
class _Token:
    kind: str
    text: str


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    position = 0
    while position < len(text):
        if text[position:].strip() == "":
            break
        match = _TOKEN_RE.match(text, position)
        if match is None or match.end() == position:
            raise QueryError(f"Ошибка разбора $filter в позиции {position}")
        kind = match.lastgroup
        assert kind is not None
        tokens.append(_Token(kind, match.group(kind)))
        position = match.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[_Token], fields: set[str]) -> None:
        self.tokens = tokens
        self.index = 0
        self.fields = fields

    def peek(self) -> _Token | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def take(self) -> _Token:
        token = self.peek()
        if token is None:
            raise QueryError("Неожиданный конец $filter")
        self.index += 1
        return token

    def keyword(self, word: str) -> bool:
        token = self.peek()
        if token is not None and token.kind == "name" and token.text == word:
            self.index += 1
            return True
        return False

    def parse(self) -> Predicate:
        predicate = self.parse_or()
        if self.peek() is not None:
            raise QueryError(f"Лишний фрагмент $filter: {self.peek().text!r}")  # type: ignore[union-attr]
        return predicate

    def parse_or(self) -> Predicate:
        left = self.parse_and()
        while self.keyword("or"):
            right = self.parse_and()
            left = (lambda a, b: lambda o: a(o) or b(o))(left, right)
        return left

    def parse_and(self) -> Predicate:
        left = self.parse_unary()
        while self.keyword("and"):
            right = self.parse_unary()
            left = (lambda a, b: lambda o: a(o) and b(o))(left, right)
        return left

    def parse_unary(self) -> Predicate:
        if self.keyword("not"):
            inner = self.parse_unary()
            return lambda o: not inner(o)
        token = self.peek()
        if token is not None and token.kind == "paren" and token.text == "(":
            self.take()
            inner = self.parse_or()
            self.expect(")")
            return inner
        if token is not None and token.kind == "name" and token.text == "substringof":
            self.take()
            self.expect("(")
            needle = self.operand()
            self.expect(",")
            haystack = self.operand()
            self.expect(")")
            return lambda o: str(needle(o) or "").lower() in str(haystack(o) or "").lower()
        left = self.operand()
        op = self.take()
        if op.kind != "name" or op.text not in _COMPARISONS:
            raise QueryError(f"Ожидалась операция сравнения, получено {op.text!r}")
        right = self.operand()
        return _compare(op.text, left, right)

    def expect(self, text: str) -> None:
        token = self.take()
        if token.text != text:
            raise QueryError(f"Ожидалось {text!r}, получено {token.text!r}")

    def operand(self) -> Callable[[dict[str, Any]], Any]:
        token = self.take()
        if token.kind == "guid":
            value: Any = token.text[5:-1].lower()
            return lambda o: value
        if token.kind == "datetime":
            moment = _parse_datetime(token.text[9:-1])
            return lambda o: moment
        if token.kind == "string":
            text = token.text[1:-1].replace("''", "'")
            return lambda o: text
        if token.kind == "number":
            number = float(token.text)
            return lambda o: number
        if token.kind == "name":
            if token.text in {"true", "false"}:
                flag = token.text == "true"
                return lambda o: flag
            if token.text == "null":
                return lambda o: None
            if token.text not in self.fields:
                raise QueryError(f"Неизвестное свойство «{token.text}» в $filter")
            name = token.text
            return lambda o: o.get(name)
        raise QueryError(f"Неожиданный элемент $filter: {token.text!r}")


def _parse_datetime(text: str) -> datetime:
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise QueryError(f"Некорректная дата {text!r}") from exc


def _coerce(value: Any, other: Any) -> Any:
    if isinstance(other, datetime) and isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(other, float) and isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str) and isinstance(other, str) and _looks_like_guid(value):
        return value.lower()
    return value


def _looks_like_guid(value: str) -> bool:
    return len(value) == 36 and value.count("-") == 4


def _compare(
    op: str, left: Callable[[dict[str, Any]], Any], right: Callable[[dict[str, Any]], Any]
) -> Predicate:
    def predicate(obj: dict[str, Any]) -> bool:
        a, b = left(obj), right(obj)
        a, b = _coerce(a, b), _coerce(b, a)
        if op == "eq":
            return bool(a == b)
        if op == "ne":
            return bool(a != b)
        if a is None or b is None:
            return False
        try:
            if op == "gt":
                return bool(a > b)
            if op == "ge":
                return bool(a >= b)
            if op == "lt":
                return bool(a < b)
            return bool(a <= b)
        except TypeError:
            return False

    return predicate


def parse_filter(text: str, fields: set[str]) -> Predicate:
    return _Parser(_tokenize(text), fields).parse()


def parse_select(text: str | None, fields: set[str]) -> list[str] | None:
    if not text:
        return None
    names = [part.strip() for part in text.split(",") if part.strip()]
    for name in names:
        if name not in fields:
            raise QueryError(f"Неизвестное свойство «{name}» в $select")
    return names


def apply_orderby(
    items: list[dict[str, Any]], text: str | None, fields: set[str]
) -> list[dict[str, Any]]:
    if not text:
        return items
    result = list(items)
    for clause in reversed([c.strip() for c in text.split(",") if c.strip()]):
        parts = clause.split()
        name = parts[0]
        if name not in fields:
            raise QueryError(f"Неизвестное свойство «{name}» в $orderby")
        descending = len(parts) > 1 and parts[1].lower() == "desc"
        result.sort(key=lambda o: _sort_key(o.get(name)), reverse=descending)
    return result


def _sort_key(value: Any) -> tuple[int, float, str]:
    if value is None:
        return (2, 0.0, "")
    if isinstance(value, int | float) and not isinstance(value, bool):
        return (0, float(value), "")
    return (1, 0.0, str(value))


def parse_int(text: str | None, name: str) -> int | None:
    if text is None or text == "":
        return None
    if not text.isdigit():
        raise QueryError(f"Некорректное значение {name}")
    return int(text)
