# -*- coding: utf-8 -*-
# tests/test_func.py
# 図鑑CSVを読み込む現在の実装に対するテスト。
# DBへ切り替えたら、このファイルは差し替える。
import pandas as pd

import bot_module.func as ub


def test_format_text_is_reexported():
    assert ub.format_text("ぴかちゅう") == "ピカチュウ"


def test_bss_to_text_from_list():
    assert ub.bss_to_text([45, 49, 49, 65, 65, 45]) == "45-49-49-65-65-45 合計318"


def test_bss_to_text_from_series():
    row = pd.Series(
        {"HP": 45, "こうげき": 49, "ぼうぎょ": 49, "とくこう": 65, "とくぼう": 65, "すばやさ": 45}
    )
    assert ub.bss_to_text(row) == "45-49-49-65-65-45 合計318"


def test_bss_to_text_from_dataframe():
    df = pd.DataFrame(
        [
            {
                "HP": 45,
                "こうげき": 49,
                "ぼうぎょ": 49,
                "とくこう": 65,
                "とくぼう": 65,
                "すばやさ": 45,
            }
        ]
    )
    assert ub.bss_to_text(df) == "45-49-49-65-65-45 合計318"


def test_pinyin_to_text_keeps_heteronyms():
    assert ub.pinyin_to_text("妙蛙種子") == "(miào,miǎo) (wā,jué) (zhǒng,chóng,zhòng) (zi,zǐ)"


def test_make_filter_dict_type():
    assert ub.make_filter_dict(["はがね"]) == {"タイプ": ["はがね"]}


def test_make_filter_dict_stats_prefix():
    assert ub.make_filter_dict(["S100"]) == {"すばやさ": ["100"]}


def test_make_filter_dict_drops_unknown_words():
    assert ub.make_filter_dict(["ジョウト", "いかく", "めざめるパワー"]) == {
        "出身地": ["ジョウト"],
        "特性": ["いかく"],
    }


def test_fetch_pokemon_by_name():
    result = ub.fetch_pokemon("ぴかちゅう")
    assert result
    assert result[0].name == "ピカチュウ"
    assert result[0].display_number == "25"


def test_fetch_pokemon_by_index_alias():
    result = ub.fetch_pokemon("ピカチュー")
    assert result
    assert result[0].name == "ピカチュウ"


def test_fetch_pokemon_not_found():
    assert ub.fetch_pokemon("でんきだま") == []


def test_fetch_pokemon_empty_input():
    assert ub.fetch_pokemon("") == []


def test_fetch_pokemon_shared_alias_returns_all_rows():
    result = ub.fetch_pokemon("ミライテラキオン")
    assert [poke.name for poke in result] == ["テツノイワオ", "テツノカシラ"]


def test_filter_by_type():
    from bot_module.pokedex import get_pokedex

    filtered = get_pokedex().filter({"タイプ": ["はがね"]})
    assert filtered
    assert all("はがね" in poke.types for poke in filtered)


def test_report_creates_row_with_given_user_name(tmp_path, monkeypatch):
    path = tmp_path / "report.csv"
    path.write_text(
        "ユーザーID,ユーザー名,クジびきけん,おこづかい\n", encoding="utf-8"
    )
    monkeypatch.setattr(ub, "REPORT_PATH", str(path))

    value = ub.report(555, 123456789, "おこづかい", 100, "テスト")

    assert value == 100
    saved = pd.read_csv(path, index_col=0)
    assert saved.loc[123456789, "ユーザー名"] == "テスト"
    assert saved.loc[123456789, "クジびきけん"] == 1


def test_report_updates_existing_row(tmp_path, monkeypatch):
    path = tmp_path / "report.csv"
    path.write_text(
        "ユーザーID,ユーザー名,クジびきけん,おこづかい\n123456789,テスト,0,50\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ub, "REPORT_PATH", str(path))

    assert ub.report(555, 123456789, "おこづかい", 25, "テスト") == 75
    assert ub.report(555, 123456789, "おこづかい", 0, "テスト") == 75