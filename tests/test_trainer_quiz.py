# -*- coding: utf-8 -*-
# tests/test_trainer_quiz.py
# トレーナークイズ: 手持ちのまとめ方、問題文からの答えの引き直し、出題から開示まで。
import asyncio

import pytest

import bot_module.config  # noqa: F401  設定を読み込む
from bot_module import trainer_quiz
from bot_module.pokedex import get_pokedex


def _battle(title_id, title, key, role, name, party, note=None, cls="ジムリーダー"):
    """party は (図鑑番号, レベル) の並び。"""
    return [(title_id, title, key, role, cls, name, slot, ndex, "00", level, note)
            for slot, (ndex, level) in enumerate(party, 1)]


ROXANNE = [("0074", 12), ("0074", 12), ("0299", 15)]
ROWS = [
    *_battle("0320", "エメラルド", "ROXANNE_1", "ジムリーダー", "ツツジ", ROXANNE),
    *_battle("0300", "ルビー", "ROXANNE", "ジムリーダー", "ツツジ", ROXANNE),
    # 同じ手持ちで組んで戦う2人は、どちらも正解
    *_battle("0720", "Let's Go! ピカチュウ", "JESSIE", "悪の組織の幹部", "ムサシ",
             [("0023", 12), ("0109", 12)], cls="ロケットだん"),
    *_battle("0720", "Let's Go! ピカチュウ", "JAMES", "悪の組織の幹部", "コジロウ",
             [("0023", 12), ("0109", 12)], cls="ロケットだん"),
    # 3人以上が同じ手持ちなのは、ゲームのデータに残る仮の手持ち
    *[row for name in ("クロツグ", "ケイト", "ダリア")
      for row in _battle("0410", "プラチナ", name, "バトル施設のボス", name, [("0019", 5)])],
    # バトル施設の候補の一覧・レベルの決まっていない対戦は出さない
    *_battle("0830", "ブリリアントダイヤモンド", "POOL", "バトル施設のボス", "クロツグ",
             [("0025", 50)], note="pool=yes; party_size=3"),
    *_battle("0830", "ブリリアントダイヤモンド", "NOLV", "ジムリーダー", "ヒョウタ",
             [("0074", None)]),
    # 一般トレーナー（役割の無いトレーナー）は出さない
    *_battle("0100", "赤", "YOUNGSTER_1", None, None, [("0019", 11)]),
]
# 御三家で変わる手持ち（同じ枠に3匹）は、3つの手持ちに分ける
ROWS += [
    ("0900", "スカーレット", "NEMONA_0", "ライバル", "ポケモントレーナー", "ネモ", 1, ndex, "00", 5, None)
    for ndex in ("0906", "0909", "0912")
]


@pytest.fixture
def catalog():
    made = trainer_quiz.TrainerCatalog(ROWS, get_pokedex())
    trainer_quiz.set_catalog(made)
    yield made
    trainer_quiz.set_catalog(None)


def _question(*lines):
    return "\n".join(lines)


ROXANNE_Q = _question("イシツブテ Lv.12", "イシツブテ Lv.12", "ノズパス Lv.15")
ROCKETS_Q = _question("アーボ Lv.12", "ドガース Lv.12")


def test_the_same_party_in_two_games_is_one_question(catalog):
    party = catalog.find(ROXANNE_Q)
    assert party.names() == ["ツツジ"]
    assert party.titles_label() == "ルビー・エメラルド"  # 作品の順


def test_two_trainers_with_the_same_party_are_both_correct(catalog):
    assert catalog.find(ROCKETS_Q).names() == ["ムサシ", "コジロウ"]


def test_placeholder_pools_unknown_levels_and_generic_trainers_are_left_out(catalog):
    names = {name for party in catalog.by_question.values() for name in party.names()}
    assert "クロツグ" not in names and "ヒョウタ" not in names
    assert catalog.find("コラッタ Lv.11") is None
    assert len(catalog) == 2 + 3  # ツツジ・ロケット団の2人・ネモの3つの手持ち


def test_alternatives_in_one_slot_become_separate_questions(catalog):
    for name in ("ニャオハ", "ホゲータ", "クワッス"):
        assert catalog.find(f"{name} Lv.5").names() == ["ネモ"]


def test_only_the_trainers_in_the_questions_are_recognized(catalog):
    assert catalog.is_trainer("つつじ")  # ひらがなでも
    assert not catalog.is_trainer("ヒョウタ")
    assert not catalog.is_trainer("ピカチュウ")


@pytest.fixture
def harness(monkeypatch, tmp_path):
    import bot_module.config as cfg
    import bot_module.func as ub

    report_path = str(tmp_path / "report.csv")
    monkeypatch.setattr(cfg, "REPORT_PATH", report_path)
    monkeypatch.setattr(ub, "REPORT_PATH", report_path)

    from debug_cli import Harness

    instance = Harness(save=False)
    yield instance
    instance.restore()


def _only(monkeypatch, catalog, question):
    monkeypatch.setattr(catalog, "random", lambda: catalog.find(question))


def test_the_quiz_is_answered_by_the_trainer_name(harness, catalog, monkeypatch, capsys):
    _only(monkeypatch, catalog, ROXANNE_Q)
    asyncio.run(harness.dispatch(["q", "trq"]))
    out = capsys.readouterr().out
    assert "トレーナークイズ" in out
    assert "ノズパス Lv.15" in out
    assert "エメラルド" not in out  # 作品は開示まで出さない

    asyncio.run(harness.dispatch(["answer", "トウキ"]))
    assert "❌" in capsys.readouterr().out

    asyncio.run(harness.dispatch(["answer", "つつじ"]))
    out = capsys.readouterr().out
    assert "⭕" in out
    assert "こたえ: ツツジ" in out
    assert "作品: ルビー・エメラルド" in out
    assert "trq(done)" in out


def test_either_trainer_of_the_same_party_is_correct(harness, catalog, monkeypatch, capsys):
    _only(monkeypatch, catalog, ROCKETS_Q)
    asyncio.run(harness.dispatch(["q", "trq"]))
    asyncio.run(harness.dispatch(["answer", "コジロウ"]))
    out = capsys.readouterr().out
    assert "⭕" in out
    assert "こたえ: ムサシ・コジロウ" in out


def test_hints_show_the_role_and_the_games(harness, catalog, monkeypatch, capsys):
    _only(monkeypatch, catalog, ROXANNE_Q)
    asyncio.run(harness.dispatch(["q", "trq"]))
    asyncio.run(harness.dispatch(["hint", "役割"]))
    asyncio.run(harness.dispatch(["hint", "作品"]))
    asyncio.run(harness.dispatch(["give"]))
    out = capsys.readouterr().out
    assert "役割はジムリーダーです" in out
    assert "作品はルビー・エメラルドです" in out
    assert "答えはツツジでした" in out


def test_without_parties_the_quiz_is_not_posted(harness, monkeypatch, capsys):
    monkeypatch.setattr(
        trainer_quiz, "get_catalog",
        lambda: trainer_quiz.TrainerCatalog([], get_pokedex()))
    asyncio.run(harness.dispatch(["q", "trq"]))
    out = capsys.readouterr().out
    assert "読み込めて いないロ" in out
