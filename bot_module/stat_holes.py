# -*- coding: utf-8 -*-
# stat_holes.py
"""種族値の一部を伏せる（? にする）ための計算。Discord に依存しない。

種族値穴埋めクイズ（bhq）と、種族値クイズの「1匹に決まる欄だけ」で使う。
欄の並びは H A B C D S（Pokemon.stats と同じ）。
"""
import itertools
import random
import re
import unicodedata
from collections import Counter

LABELS = ("H", "A", "B", "C", "D", "S")
SPEED = 5
HOLE = "?"

# 回答の欄の書き方 -> 欄の番号（長いものから照らす）
LABEL_WORDS = {
    "hp": 0, "h": 0, "こうげき": 1, "攻撃": 1, "a": 1, "ぼうぎょ": 2, "防御": 2, "b": 2,
    "とくこう": 3, "特攻": 3, "c": 3, "とくぼう": 4, "特防": 4, "d": 4,
    "すばやさ": 5, "素早さ": 5, "素早": 5, "s": 5,
}
_LABEL_RE = "|".join(sorted(map(re.escape, LABEL_WORDS), key=len, reverse=True))
PAIR_RE = re.compile(rf"({_LABEL_RE})\s*[:：=]?\s*(\d{{1,3}})")
# 回答として読むのは「欄＋数字」の並びか、数字だけの並び（雑談は拾わない）
PAIRS_ONLY_RE = re.compile(rf"(?:\s*(?:{_LABEL_RE})\s*[:：=]?\s*\d{{1,3}}[\s,、]*)+")
NUMBERS_ONLY_RE = re.compile(r"(?:\s*\d{1,3}[\s,、]*)+")


def show(stats, holes) -> str:
    """「H108 A130 B? C80 D? S102」の形。holes の欄は ? にする。"""
    return " ".join(
        f"{label}{HOLE if index in holes else value}"
        for index, (label, value) in enumerate(zip(LABELS, stats)))


def parse_shown(text):
    """show の文字列から、欄ごとの値（? は None）。読めなければ None。"""
    values = re.findall(r"\b([HABCDS])(\d+|\?)", text or "")
    if [label for label, _ in values] != list(LABELS):
        return None
    return tuple(None if value == HOLE else int(value) for _, value in values)


def matches(stats, shown) -> bool:
    """見せている欄がみな一致するか。"""
    return all(value is None or value == stat for stat, value in zip(stats, shown))


def full_text(stats) -> str:
    return show(stats, ())


def rare_slot(stats, all_stats) -> int:
    """その値を持つ種族値がいちばん少ない欄（その欄の中で数える。同数なら前の欄）。"""
    counts = [Counter(other[index] for other in all_stats) for index in range(6)]
    return min(range(6), key=lambda index: counts[index][stats[index]])


def kept_slots(stats, all_stats) -> set:
    """手がかりとして残す欄: いちばん高い欄（同じ値は全部）・いちばんめずらしい値の欄・すばやさ。"""
    top = max(stats)
    kept = {index for index, value in enumerate(stats) if value == top}
    kept.add(rare_slot(stats, all_stats))
    kept.add(SPEED)
    return kept


def choose_holes(stats, count, all_stats, keep=True, rng=random) -> tuple:
    """穴にする欄を count 個えらぶ。keep なら手がかりの欄を避ける（足りなければ使う）。"""
    kept = kept_slots(stats, all_stats) if keep else set()
    free = [index for index in range(6) if index not in kept]
    rng.shuffle(free)
    rest = [index for index in range(6) if index in kept]
    rng.shuffle(rest)
    return tuple(sorted((free + rest)[:count]))


def minimal_views(stats, all_stats) -> list:
    """1匹（同じ種族値）に決まる、いちばん少ない欄の組み合わせの一覧。"""
    others = {other for other in all_stats if other != tuple(stats)}
    for size in range(1, 7):
        views = [
            combo for combo in itertools.combinations(range(6), size)
            if not any(all(other[i] == stats[i] for i in combo) for other in others)]
        if views:
            return views
    return [tuple(range(6))]  # 同じ種族値しかいない（ここへは来ない）


def parse_answer(text, holes):
    """回答を {欄の番号: 値} に。「a120b50」「こうげき120」、数字だけ（穴の順）も読む。

    回答として読めない（雑談など）ときは None。
    """
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip().lower()
    if not normalized:
        return None
    if PAIRS_ONLY_RE.fullmatch(normalized):
        return {LABEL_WORDS[label]: int(value)
                for label, value in PAIR_RE.findall(normalized)}
    if NUMBERS_ONLY_RE.fullmatch(normalized):
        numbers = [int(number) for number in re.findall(r"\d+", normalized)]
        if len(numbers) == len(holes):
            return dict(zip(holes, numbers))
    return None


def looks_like_answer(text) -> bool:
    """チャンネルに書かれた言葉が、穴埋めの回答の形か（欄＋数字の並び・数字だけ）。"""
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip().lower()
    return bool(normalized) and bool(
        PAIRS_ONLY_RE.fullmatch(normalized) or NUMBERS_ONLY_RE.fullmatch(normalized))
