# -*- coding: utf-8 -*-
# tests/test_stat_holes.py
# 種族値の穴あけ（stat_holes）と、種族値穴埋めクイズ・種族値クイズ（1匹に決まる欄だけ）。
import asyncio
import random

import pytest

from bot_module import stat_holes

GARCHOMP = (108, 130, 95, 80, 85, 102)


def test_show_and_parse_shown_round_trip():
    text = stat_holes.show(GARCHOMP, (2, 4))
    assert text == "H108 A130 B? C80 D? S102"
    assert stat_holes.parse_shown(text) == (108, 130, None, 80, None, 102)
    assert stat_holes.parse_shown("108-130-95-80-85-102 合計600") is None


def test_kept_slots_are_the_top_the_rarest_and_the_speed():
    others = {GARCHOMP, (108, 50, 95, 80, 85, 50), (60, 50, 95, 80, 85, 60)}
    # A130 がいちばん高い。H108 はほかにもいるが A130・S102 ほどではない
    kept = stat_holes.kept_slots(GARCHOMP, others)
    assert {1, 5} <= kept
    # いちばん高い値が並ぶときは全部残す
    assert stat_holes.kept_slots((100, 100, 100, 100, 100, 100), others) == set(range(6))


def test_choose_holes_avoids_the_kept_slots():
    others = {GARCHOMP, (1, 2, 3, 4, 5, 6)}
    kept = stat_holes.kept_slots(GARCHOMP, others)
    for seed in range(30):
        holes = stat_holes.choose_holes(GARCHOMP, 3, others, rng=random.Random(seed))
        assert len(holes) == 3
        assert not kept & set(holes) or len(kept) > 3


def test_choose_holes_uses_the_kept_slots_when_not_enough_are_left():
    stats = (100, 100, 100, 100, 100, 100)
    holes = stat_holes.choose_holes(stats, 2, {stats}, rng=random.Random(0))
    assert len(holes) == 2


def test_minimal_views_pick_the_fewest_slots_that_decide_one():
    others = {GARCHOMP, (108, 130, 1, 1, 1, 1), (1, 130, 95, 1, 1, 1)}
    views = stat_holes.minimal_views(GARCHOMP, others)
    assert all(len(view) == len(views[0]) for view in views)
    for view in views:
        shown = tuple(GARCHOMP[i] if i in view else None for i in range(6))
        assert [s for s in others if stat_holes.matches(s, shown)] == [GARCHOMP]


@pytest.mark.parametrize("text, expected", [
    ("b95d85", {2: 95, 4: 85}),
    ("B95 D85", {2: 95, 4: 85}),
    ("ｂ９５　ｄ８５", {2: 95, 4: 85}),
    ("ぼうぎょ95 とくぼう85", {2: 95, 4: 85}),
    ("HP108", {0: 108}),
    ("95 85", {2: 95, 4: 85}),
    ("95、85", {2: 95, 4: 85}),
])
def test_parse_answer_reads_slots_and_numbers(text, expected):
    assert stat_holes.parse_answer(text, (2, 4)) == expected


@pytest.mark.parametrize("text", ["ガブリアス", "95", "b95はどう？", "おはよう", ""])
def test_parse_answer_ignores_chat(text):
    assert stat_holes.parse_answer(text, (2, 4)) is None


def test_looks_like_answer():
    assert stat_holes.looks_like_answer("a120b50")
    assert stat_holes.looks_like_answer("120")
    assert not stat_holes.looks_like_answer("ガブリアス")
    assert not stat_holes.looks_like_answer("a120くらい？")


# --- クイズ（debug_cli の偽Discordで本物のCogを呼ぶ） ---

@pytest.fixture
def harness(monkeypatch, tmp_path):
    import bot_module.config as cfg
    import bot_module.func as ub

    report_path = str(tmp_path / "report.csv")
    monkeypatch.setattr(cfg, "REPORT_PATH", report_path)
    monkeypatch.setattr(ub, "REPORT_PATH", report_path)
    monkeypatch.setattr(ub, "BSS_GRAPH_PATH", str(tmp_path / "graph.png"))

    from debug_cli import Harness

    instance = Harness(save=False)
    yield instance
    instance.restore()


def _fix_pokemon(monkeypatch, name):
    from bot_module.pokedex import get_pokedex

    dex = get_pokedex()
    target = next(p for p in dex.records if p.name == name)
    monkeypatch.setattr(type(dex), "random", lambda self, filter_dict: target)
    return target


def _holes(harness):
    shown = stat_holes.parse_shown(harness.quiz_message.content)
    return [i for i, value in enumerate(shown) if value is None]


def _answer(stats, holes, wrong=()):
    return "".join(
        f"{stat_holes.LABELS[i]}{stats[i] + (1 if i in wrong else 0)}" for i in holes)


def test_the_hole_quiz_takes_the_numbers(harness, monkeypatch, capsys):
    pokemon = _fix_pokemon(monkeypatch, "ガブリアス")
    asyncio.run(harness.dispatch(["q", "bhq", "-", "2"]))
    out = capsys.readouterr().out
    assert "種族値穴埋めクイズ" in out
    assert "**ガブリアス**" in out
    holes = _holes(harness)
    assert len(holes) == 2
    # 既定の出し方では、いちばん高い A130 とすばやさは穴にならない
    assert 1 not in holes and 5 not in holes

    # 一部だけ合った誤答は、合った欄を教える
    asyncio.run(harness.dispatch(["answer", _answer(pokemon.stats, holes, wrong=holes[1:])]))
    out = capsys.readouterr().out
    assert "bhq誤答" in out
    assert f"{stat_holes.LABELS[holes[0]]} は 合ってるロ" in out

    # 片方の穴だけでは判定しない（戦績に数えない）
    asyncio.run(harness.dispatch(["answer", _answer(pokemon.stats, holes[:1])]))
    out = capsys.readouterr().out
    assert "まとめて答えてね" in out
    assert "bhq" not in out.split("まとめて")[1]

    asyncio.run(harness.dispatch(["answer", _answer(pokemon.stats, holes).lower()]))
    out = capsys.readouterr().out
    assert "⭕" in out
    assert "bhq正答" in out
    assert "こたえ: H108 A130" in out.replace("**", "")


def test_the_hole_quiz_takes_bare_numbers_and_gives_the_total(harness, monkeypatch, capsys):
    pokemon = _fix_pokemon(monkeypatch, "ガブリアス")
    asyncio.run(harness.dispatch(["q", "bhq"]))
    holes = _holes(harness)
    assert len(holes) == 1  # 既定は穴1つ
    asyncio.run(harness.dispatch(["hint", "合計"]))
    assert "合計は600です" in capsys.readouterr().out
    asyncio.run(harness.dispatch(["answer", str(pokemon.stats[holes[0]])]))
    assert "bhq正答" in capsys.readouterr().out


def test_the_random_hole_quiz_says_so_in_the_title(harness, monkeypatch, capsys):
    _fix_pokemon(monkeypatch, "ガブリアス")
    asyncio.run(harness.dispatch(["q", "bhq", "穴の位置ランダム", "3"]))
    out = capsys.readouterr().out
    assert "種族値穴埋めクイズ（穴の位置ランダム）" in out
    assert len(_holes(harness)) == 3


def test_the_stats_quiz_can_show_only_the_deciding_slots(harness, monkeypatch, capsys):
    _fix_pokemon(monkeypatch, "ガブリアス")
    asyncio.run(harness.dispatch(["q", "bq", "1匹に決まる欄だけ"]))
    out = capsys.readouterr().out
    assert "種族値クイズ（1匹に決まる欄だけ）" in out
    assert "合計" not in harness.quiz_message.content
    assert len(_holes(harness)) >= 3  # ガブリアスは2欄で決まる

    asyncio.run(harness.dispatch(["answer", "ガブリアス"]))
    out = capsys.readouterr().out
    assert "bq正答" in out
    assert "H108 A130 B95 C80 D85 S102" in out
