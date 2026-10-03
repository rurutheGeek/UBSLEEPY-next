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
    assert result is not None
    assert result.iloc[0]["おなまえ"] == "ピカチュウ"
    assert result.iloc[0]["ぜんこくずかんナンバー"] == "25"


def test_fetch_pokemon_by_index_alias():
    result = ub.fetch_pokemon("ピカチュー")
    assert result is not None
    assert result.iloc[0]["おなまえ"] == "ピカチュウ"


def test_fetch_pokemon_not_found():
    assert ub.fetch_pokemon("でんきだま") is None


def test_filter_dataframe_by_type():
    filtered = ub.filter_dataframe({"タイプ": ["はがね"]})
    assert not filtered.empty
    matched = (filtered["タイプ1"] == "はがね") | (filtered["タイプ2"] == "はがね")
    assert matched.all()