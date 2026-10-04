# -*- coding: utf-8 -*-
# search.py
"""ポケモン検索の条件解析と評価。Discordに依存しない。

条件は空白区切りの語。タイプ・特性・地方・世代・進化段階はカタログの
値と照合し、種族値の式（H>=100、A==C、(H*B)/(B+D)<2000 など）は
ASTで許可したノードだけを評価する（evalは使わない）。
"""
from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass, field

import jaconv

from .pokedex import EVOLUTION_STAGES, Pokemon, get_pokedex

# 種族値の記号 → Pokemonの属性。式の中ではこの記号だけを許す。
STAT_ATTRIBUTES = {
    "H": "hp",
    "A": "atk",
    "B": "dfn",
    "C": "spa",
    "D": "spd",
    "S": "spe",
    "T": "total",
}

# BASE_STATS_DICT（H/HP/A/攻撃/こうげき…）を式の記号へ寄せる
_CANONICAL_STATS = {
    "HP": "H",
    "こうげき": "A",
    "ぼうぎょ": "B",
    "とくこう": "C",
    "とくぼう": "D",
    "すばやさ": "S",
    "合計": "T",
}

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
_ALLOWED_OPERATOR_NODES = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.UAdd,
    ast.USub,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)


def _stat_replacements() -> list[tuple[str, str]]:
    from .settings import get_settings

    mapping = {}
    for key, value in get_settings().base_stats_dict.items():
        canonical = _CANONICAL_STATS.get(value)
        if canonical:
            mapping[key] = canonical
    # 長い語から置換する（HP → H の順番を守る）
    return sorted(mapping.items(), key=lambda item: -len(item[0]))


def _valid_expression(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                return False
        elif isinstance(node, ast.Name):
            if node.id not in STAT_ATTRIBUTES:
                return False
        elif isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Compare)):
            continue
        elif isinstance(node, ast.Load):
            continue
        elif isinstance(node, (ast.operator, ast.unaryop, ast.cmpop)):
            if not isinstance(node, _ALLOWED_OPERATOR_NODES):
                return False
        else:
            return False
    return True


def parse_expression(text: str) -> ast.Expression | None:
    """種族値の式をASTへ。許可外の式はNone。"""
    expression = jaconv.z2h(text, kana=False, ascii=True, digit=True).strip(",、")
    for word, symbol in _stat_replacements():
        expression = re.sub(
            r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])",
            symbol,
            expression,
            flags=re.IGNORECASE,
        )
    expression = re.sub(r"(?<![<>=!])=(?!=)", "==", expression)
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return None
    if not _valid_expression(tree):
        return None
    if not any(isinstance(node, ast.Name) for node in ast.walk(tree)):
        return None
    return tree


def evaluate_expression(tree: ast.Expression, pokemon: Pokemon):
    values = {
        symbol: getattr(pokemon, attribute)
        for symbol, attribute in STAT_ATTRIBUTES.items()
    }
    return _evaluate_node(tree.body, values)


def _evaluate_node(node: ast.AST, values: dict):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return values[node.id]
    if isinstance(node, ast.BinOp):
        return _BIN_OPS[type(node.op)](
            _evaluate_node(node.left, values), _evaluate_node(node.right, values)
        )
    if isinstance(node, ast.UnaryOp):
        operand = _evaluate_node(node.operand, values)
        return operand if isinstance(node.op, ast.UAdd) else -operand
    if isinstance(node, ast.Compare):
        left = _evaluate_node(node.left, values)
        for op, comparator in zip(node.ops, node.comparators):
            right = _evaluate_node(comparator, values)
            if not _CMP_OPS[type(op)](left, right):
                return False
            left = right
        return True
    raise ValueError(f"未対応の式です: {ast.dump(node)}")


@dataclass
class SearchQuery:
    """検索条件。GUIのパネルはこのオブジェクトを語の並びに戻して持つ。"""

    types: list[str] = field(default_factory=list)
    abilities: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    generations: list[int] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)
    expressions: list[tuple[str, ast.Expression]] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)

    @classmethod
    def parse(cls, words) -> "SearchQuery":
        pokedex = get_pokedex()
        generations = {str(number) for number in range(1, 10)}
        query = cls()
        for raw in words:
            word = str(raw).strip().strip(",、")
            if not word:
                continue
            if word in pokedex.types():
                query.types.append(word)
            elif word in pokedex.abilities():
                query.abilities.append(word)
            elif word in pokedex.regions():
                query.regions.append(word)
            elif word in EVOLUTION_STAGES:
                query.stages.append(word)
            elif word in generations:
                query.generations.append(int(word))
            else:
                tree = parse_expression(word)
                if tree is not None:
                    query.expressions.append((word, tree))
                else:
                    query.unknown.append(word)
        return query

    @property
    def has_conditions(self) -> bool:
        return bool(
            self.types
            or self.abilities
            or self.regions
            or self.generations
            or self.stages
            or self.expressions
        )

    def to_words(self) -> list[str]:
        return [
            *self.types,
            *self.abilities,
            *self.regions,
            *[str(generation) for generation in self.generations],
            *self.stages,
            *[expression for expression, _ in self.expressions],
        ]

    def describe(self) -> list[tuple[str, str]]:
        conditions = []
        if self.types:
            conditions.append(("タイプ", "・".join(self.types)))
        if self.abilities:
            conditions.append(("特性", "・".join(self.abilities)))
        if self.regions:
            conditions.append(("地方", "・".join(self.regions)))
        if self.generations:
            conditions.append(
                ("世代", "・".join(f"第{generation}世代" for generation in self.generations))
            )
        if self.stages:
            conditions.append(("進化段階", "・".join(self.stages)))
        if self.expressions:
            conditions.append(
                ("種族値", "、".join(expression for expression, _ in self.expressions))
            )
        if self.unknown:
            conditions.append(("未解釈", "・".join(self.unknown)))
        return conditions

    def matches(self, pokemon: Pokemon) -> bool:
        if self.types and not any(t in pokemon.types for t in self.types):
            return False
        if self.abilities and not any(a in pokemon.abilities for a in self.abilities):
            return False
        if self.regions and pokemon.region not in self.regions:
            return False
        if self.generations and pokemon.generation not in self.generations:
            return False
        if self.stages and pokemon.evolution_stage not in self.stages:
            return False
        for _, tree in self.expressions:
            try:
                if not evaluate_expression(tree, pokemon):
                    return False
            except (ZeroDivisionError, OverflowError, ValueError):
                return False
        return True

    def apply(self, records: list[Pokemon]) -> list[Pokemon]:
        return [pokemon for pokemon in records if self.matches(pokemon)]
