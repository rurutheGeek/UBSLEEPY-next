# -*- coding: utf-8 -*-
# tests/test_dex_text.py
# 図鑑説明クイズ: 名前の伏せ字、問題文からの答えの引き直し、出題から開示まで。
import asyncio

import pytest

import bot_module.config  # noqa: F401  設定を読み込む
from bot_module import dex_text
from bot_module.pokedex import get_pokedex

YADORAN = "ヤドンが 海へ エサを 取りにいったとき シェルダーに 尻尾を かまれ ヤドランになった。"
UB_TEXT = "この世界では 異質で 危険だが 本来 棲んでいる 世界では 普通に 見かける 生物らしい。"
ROWS = [
    ("0080", "00", "赤", YADORAN),
    ("0080", "00", "緑", YADORAN),
    ("0080", "00", "青", "くっついている シェルダーは ヤドンの たべのこした ものを エサにして いきているという。"),
    ("0080", "02", "ソード", "ガラルの すがたの 説明。"),
    ("0794", "00", "ウルトラサン", UB_TEXT),
    ("0795", "00", "ウルトラサン", UB_TEXT),
    ("9999", "00", "赤", "図鑑に 居ない ポケモン。"),
]


@pytest.fixture
def catalog():
    made = dex_text.DexTextCatalog(ROWS, get_pokedex())
    dex_text.set_catalog(made)
    yield made
    dex_text.set_catalog(None)


def _mask(text, *names):
    return dex_text.mask_names(text, dex_text.name_pattern(names))


def test_every_pokemon_name_is_masked():
    # 進化前（ヤドン）やかかわるポケモン（シェルダー）の名前でも答えが分かるので伏せる
    M = dex_text.MASK
    assert _mask(YADORAN, "ヤドン", "ヤドラン", "シェルダー") == (
        f"{M}が 海へ エサを 取りにいったとき {M}に 尻尾を かまれ {M}になった。")


def test_the_longer_name_is_masked_first():
    assert _mask("レアコイルは コイルが 3つ。", "コイル", "レアコイル") == (
        f"{dex_text.MASK}は {dex_text.MASK}が 3つ。")


def test_the_mask_ignores_the_form_and_hides_the_sex():
    assert _mask(
        "デオキシスの 胸の 水晶体。", "デオキシス(ノーマルフォルム)"
    ) == f"{dex_text.MASK}の 胸の 水晶体。"
    assert _mask(
        "ニドラン♀より 耳が 大きい。", "ニドラン♂"
    ) == f"{dex_text.MASK}より 耳が 大きい。"
    assert _mask("名前の 無い 説明。") == "名前の 無い 説明。"


def test_the_catalog_masks_with_the_whole_pokedex(catalog):
    question = catalog.by_species["80"][0].question
    assert not any(name in question for name in ("ヤドラン", "ヤドン", "シェルダー"))
    assert catalog.by_species["80"][0].text == YADORAN  # 開示用のもとの文は残す


def test_the_same_text_is_one_question_with_every_title(catalog):
    entries = catalog.by_species["80"]
    assert len(entries) == 3  # 赤・緑は1つにまとまる。フォームの説明も同じ種族の問題
    assert entries[0].titles == ("赤", "緑")
    assert "9999" not in catalog.by_species


def test_the_answer_is_found_from_the_question(catalog):
    question = catalog.by_species["80"][0].question
    assert [entry.species for entry in catalog.find(question)] == ["80"]
    assert catalog.find("こんな説明は ない。") == []
    # 伏せ字にしても同じ文になる種族は、みな答え
    assert [entry.species for entry in catalog.find(UB_TEXT)] == ["794", "795"]


def test_every_title_is_listed():
    entry = dex_text.DexText("80", "x", ("赤", "緑", "青", "ピカチュウ"), "x")
    assert entry.titles_label() == "赤・緑・青・ピカチュウ"


def test_without_any_source_the_catalog_is_empty(monkeypatch, tmp_path):
    monkeypatch.delenv("PKDB_PASSWORD", raising=False)
    assert len(dex_text.load_catalog(tmp_path / "none.csv")) == 0


def test_the_csv_is_read(monkeypatch, tmp_path):
    monkeypatch.delenv("PKDB_PASSWORD", raising=False)
    path = tmp_path / "pokedex_text.csv"
    path.write_text(
        "ndex_number,form_id,title,text\n0080,00,赤,ヤドランの 説明。\n",
        encoding="utf-8")
    loaded = dex_text.load_catalog(path)
    assert loaded.by_species["80"][0].question == f"{dex_text.MASK}の 説明。"


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


def _only(monkeypatch, catalog, species, index=0):
    monkeypatch.setattr(
        catalog, "random", lambda: catalog.by_species[species][index])


def test_the_quiz_is_answered_by_the_name(harness, catalog, monkeypatch, capsys):
    _only(monkeypatch, catalog, "80")
    asyncio.run(harness.dispatch(["q", "dexq"]))
    out = capsys.readouterr().out
    assert "出題: 図鑑説明クイズ" in out
    assert "ヤド" not in out and "シェルダー" not in out  # 問題文に名前が出ない

    asyncio.run(harness.dispatch(["answer", "ピカチュウ"]))
    assert "❌" in capsys.readouterr().out

    asyncio.run(harness.dispatch(["answer", "ヤドラン"]))
    out = capsys.readouterr().out
    assert "⭕" in out
    assert "ヤドランになった。" in out  # 開示ではもとの文を出す
    assert "こたえ: ヤドラン" in out
    assert "作品: 赤・緑" in out  # 名前の下に、載っている作品を全部
    assert "dexq(done)" in out


def test_any_pokemon_with_the_same_text_is_correct(
        harness, catalog, monkeypatch, capsys):
    _only(monkeypatch, catalog, "795")
    asyncio.run(harness.dispatch(["q", "dexq"]))
    asyncio.run(harness.dispatch(["answer", "フェローチェ"]))
    out = capsys.readouterr().out
    assert "⭕" in out
    assert "こたえ: マッシブーン,フェローチェ" in out


def test_hint_and_give_work(harness, catalog, monkeypatch, capsys):
    _only(monkeypatch, catalog, "80")
    asyncio.run(harness.dispatch(["q", "dexq"]))
    asyncio.run(harness.dispatch(["hint", "タイプ"]))
    asyncio.run(harness.dispatch(["give"]))
    out = capsys.readouterr().out
    assert "タイプ1はみずです" in out
    assert "答えはヤドランでした" in out


def test_without_texts_the_quiz_is_not_posted(harness, monkeypatch, capsys):
    monkeypatch.setattr(
        dex_text, "get_catalog",
        lambda: dex_text.DexTextCatalog([], get_pokedex()))
    asyncio.run(harness.dispatch(["q", "dexq"]))
    out = capsys.readouterr().out
    assert "読み込めて いないロ" in out
    assert "出題: 図鑑説明クイズ" not in out
