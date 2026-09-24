"""Pure parsing and evaluation for the restricted policy condition language."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Final, TypeGuard

from .errors import PolicyExpressionError
from .types import DecisionInput, JsonValue

if TYPE_CHECKING:
    from .models import ConditionId, PolicyCondition

_TRUST_RANK: Final = {"untrusted": 0, "internal": 1, "trusted": 2}
_FIELD_ROOTS: Final = frozenset({"params", "context", "run", "environment"})


class _TokenKind(StrEnum):
    STRING = auto()
    NUMBER = auto()
    IDENTIFIER = auto()
    TRUE = auto()
    FALSE = auto()
    NULL = auto()
    ALL = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    IN = auto()
    ENDS_WITH = auto()
    EQUAL = auto()
    NOT_EQUAL = auto()
    LESS = auto()
    LESS_EQUAL = auto()
    GREATER = auto()
    GREATER_EQUAL = auto()
    DOT = auto()
    COMMA = auto()
    LEFT_PAREN = auto()
    RIGHT_PAREN = auto()
    LEFT_BRACE = auto()
    RIGHT_BRACE = auto()
    LEFT_BRACKET = auto()
    RIGHT_BRACKET = auto()
    END = auto()


_TOKEN_PATTERN: Final = re.compile(
    r"""
    (?P<WHITESPACE>\s+)
    |(?P<STRING>"(?:\\.|[^"\\])*")
    |(?P<NUMBER>-?(?:\d+\.\d+|\d+))
    |(?P<LESS_EQUAL><=)
    |(?P<GREATER_EQUAL>>=)
    |(?P<EQUAL>==)
    |(?P<NOT_EQUAL>!=)
    |(?P<LESS><)
    |(?P<GREATER>>)
    |(?P<LEFT_PAREN>\()
    |(?P<RIGHT_PAREN>\))
    |(?P<LEFT_BRACE>\{)
    |(?P<RIGHT_BRACE>\})
    |(?P<LEFT_BRACKET>\[)
    |(?P<RIGHT_BRACKET>\])
    |(?P<COMMA>,)
    |(?P<DOT>\.)
    |(?P<IDENTIFIER>[A-Za-z_][A-Za-z0-9_]*)
    """,
    re.VERBOSE,
)

_KEYWORDS: Final = {
    "all": _TokenKind.ALL,
    "and": _TokenKind.AND,
    "or": _TokenKind.OR,
    "not": _TokenKind.NOT,
    "in": _TokenKind.IN,
    "endsWith": _TokenKind.ENDS_WITH,
    "true": _TokenKind.TRUE,
    "false": _TokenKind.FALSE,
    "null": _TokenKind.NULL,
}


@dataclass(frozen=True, slots=True)
class ConditionResult:
    """Record whether one named policy condition passed."""

    id: ConditionId
    passed: bool


@dataclass(frozen=True, slots=True)
class _Token:
    kind: _TokenKind
    text: str


@dataclass(frozen=True, slots=True)
class _LiteralNode:
    value: JsonValue


@dataclass(frozen=True, slots=True)
class _FieldNode:
    root: str
    path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _CurrentItemNode:
    pass


@dataclass(frozen=True, slots=True)
class _ListNode:
    values: tuple[_ExpressionNode, ...]


@dataclass(frozen=True, slots=True)
class _ComparisonNode:
    operator: _TokenKind
    left: _ExpressionNode
    right: _ExpressionNode


@dataclass(frozen=True, slots=True)
class _BooleanNode:
    operator: _TokenKind
    left: _ExpressionNode
    right: _ExpressionNode


@dataclass(frozen=True, slots=True)
class _NotNode:
    operand: _ExpressionNode


@dataclass(frozen=True, slots=True)
class _AllNode:
    collection: _ExpressionNode
    predicate: _ExpressionNode


type _ExpressionNode = (
    _LiteralNode
    | _FieldNode
    | _CurrentItemNode
    | _ListNode
    | _ComparisonNode
    | _BooleanNode
    | _NotNode
    | _AllNode
)


class _MissingCurrentItem:
    pass


_MISSING_CURRENT_ITEM: Final = _MissingCurrentItem()
type _CurrentItem = JsonValue | _MissingCurrentItem


class _Parser:
    def __init__(self, tokens: tuple[_Token, ...]) -> None:
        self._tokens = tokens
        self._position = 0

    def parse(self) -> _ExpressionNode:
        expression = self._parse_or()
        self._expect(_TokenKind.END)
        return expression

    def _parse_or(self) -> _ExpressionNode:
        expression = self._parse_and()
        while self._match(_TokenKind.OR):
            expression = _BooleanNode(_TokenKind.OR, expression, self._parse_and())
        return expression

    def _parse_and(self) -> _ExpressionNode:
        expression = self._parse_not()
        while self._match(_TokenKind.AND):
            expression = _BooleanNode(_TokenKind.AND, expression, self._parse_not())
        return expression

    def _parse_not(self) -> _ExpressionNode:
        if self._match(_TokenKind.NOT):
            return _NotNode(self._parse_not())
        return self._parse_comparison()

    def _parse_comparison(self) -> _ExpressionNode:
        left = self._parse_primary()
        comparison_kinds = (
            _TokenKind.EQUAL,
            _TokenKind.NOT_EQUAL,
            _TokenKind.LESS,
            _TokenKind.LESS_EQUAL,
            _TokenKind.GREATER,
            _TokenKind.GREATER_EQUAL,
            _TokenKind.IN,
            _TokenKind.ENDS_WITH,
        )
        if self._peek().kind in comparison_kinds:
            operator = self._advance().kind
            return _ComparisonNode(operator, left, self._parse_primary())
        return left

    def _parse_primary(self) -> _ExpressionNode:
        token = self._advance()
        literal = _literal_node(token)
        if literal is not None:
            return literal
        if token.kind is _TokenKind.IDENTIFIER:
            return self._parse_field(token.text)
        if token.kind is _TokenKind.DOT:
            return _CurrentItemNode()
        if token.kind is _TokenKind.LEFT_PAREN:
            expression = self._parse_or()
            self._expect(_TokenKind.RIGHT_PAREN)
            return expression
        if token.kind is _TokenKind.LEFT_BRACKET:
            return self._parse_list()
        if token.kind is _TokenKind.ALL:
            return self._parse_all()
        message = f"expected expression, found {token.text!r}"
        raise PolicyExpressionError(message)

    def _parse_field(self, root: str) -> _ExpressionNode:
        if root not in _FIELD_ROOTS:
            message = f"unknown field root {root!r}"
            raise PolicyExpressionError(message)
        path: list[str] = []
        while self._match(_TokenKind.DOT):
            path.append(self._expect(_TokenKind.IDENTIFIER).text)
        if not path:
            message = f"field root {root!r} requires a path"
            raise PolicyExpressionError(message)
        return _FieldNode(root, tuple(path))

    def _parse_list(self) -> _ExpressionNode:
        values: list[_ExpressionNode] = []
        if not self._check(_TokenKind.RIGHT_BRACKET):
            values.append(self._parse_or())
            while self._match(_TokenKind.COMMA):
                values.append(self._parse_or())
        self._expect(_TokenKind.RIGHT_BRACKET)
        return _ListNode(tuple(values))

    def _parse_all(self) -> _ExpressionNode:
        self._expect(_TokenKind.LEFT_PAREN)
        collection = self._parse_or()
        self._expect(_TokenKind.COMMA)
        self._expect(_TokenKind.LEFT_BRACE)
        predicate = self._parse_or()
        self._expect(_TokenKind.RIGHT_BRACE)
        self._expect(_TokenKind.RIGHT_PAREN)
        return _AllNode(collection, predicate)

    def _match(self, kind: _TokenKind) -> bool:
        if not self._check(kind):
            return False
        self._advance()
        return True

    def _check(self, kind: _TokenKind) -> bool:
        return self._peek().kind is kind

    def _expect(self, kind: _TokenKind) -> _Token:
        if self._check(kind):
            return self._advance()
        token = self._peek()
        message = f"expected {kind.value}, found {token.text!r}"
        raise PolicyExpressionError(message)

    def _peek(self) -> _Token:
        return self._tokens[self._position]

    def _advance(self) -> _Token:
        token = self._peek()
        if token.kind is not _TokenKind.END:
            self._position += 1
        return token


def evaluate_condition(
    condition: PolicyCondition, decision_input: DecisionInput
) -> ConditionResult:
    """Evaluate one condition, converting every language error into a failed result."""
    try:
        expression = _Parser(_tokenize(str(condition.expr))).parse()
        passed = _require_boolean(
            _evaluate(expression, decision_input, _MISSING_CURRENT_ITEM),
        )
    except PolicyExpressionError:
        passed = False
    return ConditionResult(id=condition.id, passed=passed)


def evaluate_conditions(
    conditions: tuple[PolicyCondition, ...],
    decision_input: DecisionInput,
) -> tuple[ConditionResult, ...]:
    """Evaluate conditions independently while preserving their document order."""
    return tuple(evaluate_condition(condition, decision_input) for condition in conditions)


def _tokenize(expression: str) -> tuple[_Token, ...]:
    tokens: list[_Token] = []
    position = 0
    while position < len(expression):
        match = _TOKEN_PATTERN.match(expression, position)
        if match is None:
            message = f"unsupported token at position {position}"
            raise PolicyExpressionError(message)
        kind_name = match.lastgroup
        if kind_name is None:
            message = f"token at position {position} has no kind"
            raise PolicyExpressionError(message)
        text = match.group()
        position = match.end()
        if kind_name == "WHITESPACE":
            continue
        kind = _TokenKind(kind_name.lower())
        if kind is _TokenKind.IDENTIFIER:
            kind = _KEYWORDS.get(text, kind)
        tokens.append(_Token(kind, text))
    tokens.append(_Token(_TokenKind.END, "<end>"))
    return tuple(tokens)


def _decode_string(text: str) -> str:
    try:
        value: object = json.loads(text)
    except json.JSONDecodeError as error:
        message = "invalid string literal"
        raise PolicyExpressionError(message) from error
    if not isinstance(value, str):
        message = "string literal did not decode to text"
        raise PolicyExpressionError(message)
    return value


def _literal_node(token: _Token) -> _LiteralNode | None:
    if token.kind is _TokenKind.STRING:
        return _LiteralNode(value=_decode_string(token.text))
    if token.kind is _TokenKind.NUMBER:
        value: int | float = float(token.text) if "." in token.text else int(token.text)
        return _LiteralNode(value=value)
    if token.kind is _TokenKind.TRUE:
        return _LiteralNode(value=True)
    if token.kind is _TokenKind.FALSE:
        return _LiteralNode(value=False)
    if token.kind is _TokenKind.NULL:
        return _LiteralNode(value=None)
    return None


def _evaluate(
    node: _ExpressionNode,
    decision_input: DecisionInput,
    current_item: _CurrentItem,
) -> JsonValue:
    if isinstance(node, (_LiteralNode, _FieldNode, _CurrentItemNode, _ListNode)):
        return _evaluate_value_node(node, decision_input, current_item)
    if isinstance(node, _ComparisonNode):
        left = _evaluate(node.left, decision_input, current_item)
        right = _evaluate(node.right, decision_input, current_item)
        return _compare(node.operator, left, right)
    if isinstance(node, _BooleanNode):
        return _evaluate_boolean(node, decision_input, current_item)
    if isinstance(node, _NotNode):
        return not _require_boolean(_evaluate(node.operand, decision_input, current_item))
    return _evaluate_all(node, decision_input, current_item)


def _evaluate_value_node(
    node: _LiteralNode | _FieldNode | _CurrentItemNode | _ListNode,
    decision_input: DecisionInput,
    current_item: _CurrentItem,
) -> JsonValue:
    if isinstance(node, _LiteralNode):
        return node.value
    if isinstance(node, _FieldNode):
        return _resolve_field(node, decision_input)
    if isinstance(node, _CurrentItemNode):
        if isinstance(current_item, _MissingCurrentItem):
            message = "current-item marker is valid only inside all"
            raise PolicyExpressionError(message)
        return current_item
    return [_evaluate(value, decision_input, current_item) for value in node.values]


def _evaluate_boolean(
    node: _BooleanNode,
    decision_input: DecisionInput,
    current_item: _CurrentItem,
) -> bool:
    left = _require_boolean(_evaluate(node.left, decision_input, current_item))
    if node.operator is _TokenKind.AND:
        return left and _require_boolean(_evaluate(node.right, decision_input, current_item))
    return left or _require_boolean(_evaluate(node.right, decision_input, current_item))


def _evaluate_all(
    node: _AllNode,
    decision_input: DecisionInput,
    current_item: _CurrentItem,
) -> bool:
    collection = _evaluate(node.collection, decision_input, current_item)
    if not isinstance(collection, list):
        message = "all requires a list"
        raise PolicyExpressionError(message)
    return all(
        _require_boolean(_evaluate(node.predicate, decision_input, item)) for item in collection
    )


def _resolve_field(node: _FieldNode, decision_input: DecisionInput) -> JsonValue:
    roots = {
        "params": decision_input.parameters,
        "context": decision_input.context_provenance,
        "run": decision_input.run_metadata,
        "environment": decision_input.environment,
    }
    current_mapping = roots[node.root]
    value: JsonValue
    first, *remaining = node.path
    if first not in current_mapping:
        message = f"field {node.root}.{first} is missing"
        raise PolicyExpressionError(message)
    value = current_mapping[first]
    for segment in remaining:
        if not isinstance(value, dict) or segment not in value:
            message = f"field {node.root}.{'.'.join(node.path)} is missing"
            raise PolicyExpressionError(message)
        value = value[segment]
    return value


def _compare(operator: _TokenKind, left: JsonValue, right: JsonValue) -> bool:
    if operator is _TokenKind.ENDS_WITH:
        return _ends_with(left, right)
    if operator is _TokenKind.IN:
        return _is_in(left, right)
    if operator in (_TokenKind.EQUAL, _TokenKind.NOT_EQUAL):
        equal = _values_equal(left, right)
        return equal if operator is _TokenKind.EQUAL else not equal
    return _compare_ordered(operator, left, right)


def _ends_with(left: JsonValue, right: JsonValue) -> bool:
    if not isinstance(left, str) or not isinstance(right, str):
        message = "endsWith requires two strings"
        raise PolicyExpressionError(message)
    return left.endswith(right)


def _is_in(left: JsonValue, right: JsonValue) -> bool:
    if not isinstance(right, list):
        message = "in requires a list on the right"
        raise PolicyExpressionError(message)
    return any(_values_equal(left, candidate) for candidate in right)


def _compare_ordered(operator: _TokenKind, left: JsonValue, right: JsonValue) -> bool:
    if _is_number(left) and _is_number(right):
        return _compare_numbers(operator, left, right)
    if isinstance(left, str) and isinstance(right, str):
        if left in _TRUST_RANK and right in _TRUST_RANK:
            return _compare_numbers(operator, _TRUST_RANK[left], _TRUST_RANK[right])
        return _compare_strings(operator, left, right)
    message = "ordered comparison requires two numbers or two strings"
    raise PolicyExpressionError(message)


def _compare_numbers(operator: _TokenKind, left: float, right: float) -> bool:
    if operator is _TokenKind.LESS:
        return left < right
    if operator is _TokenKind.LESS_EQUAL:
        return left <= right
    if operator is _TokenKind.GREATER:
        return left > right
    if operator is _TokenKind.GREATER_EQUAL:
        return left >= right
    message = f"unsupported comparison operator {operator.value}"
    raise PolicyExpressionError(message)


def _compare_strings(operator: _TokenKind, left: str, right: str) -> bool:
    if operator is _TokenKind.LESS:
        return left < right
    if operator is _TokenKind.LESS_EQUAL:
        return left <= right
    if operator is _TokenKind.GREATER:
        return left > right
    if operator is _TokenKind.GREATER_EQUAL:
        return left >= right
    message = f"unsupported comparison operator {operator.value}"
    raise PolicyExpressionError(message)


def _values_equal(left: JsonValue, right: JsonValue) -> bool:
    if _is_number(left) and _is_number(right):
        return left == right
    if type(left) is not type(right):
        return False
    return left == right


def _is_number(value: JsonValue) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_boolean(value: JsonValue) -> bool:
    if not isinstance(value, bool):
        message = "condition expression must produce a boolean"
        raise PolicyExpressionError(message)
    return value
