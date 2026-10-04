# -*- coding: utf-8 -*-
# tests/test_pokedex.py
# 図鑑カタログ（pkdb/CSV）の読み込みと検索。
import bot_module.config  # noqa: F401  設定を読み込むため
from bot_module import pokedex as pk

CSV_PATH = "resource/pokemon_database.csv"


def _row(
    ndex,
    form,
    name,
    form_name,
    official,
    alias,
    eng,
    cht,
    type_1,
    type_2,
    ability_1,
    ability_2,
    ability_h,
    stats,
    title,
    generation,
    region,
    stage,
):
    return (
        ndex,
        form,
        name,
        form_name,
        official,
        alias,
        eng,
        cht,
        type_1,
        type_2,
        ability_1,
        ability_2,
        ability_h,
        *stats,
        title,
        generation,
        region,
        stage,
    )


def _raichu_rows():
    return [
        _row(
            "0026", "00", "ライチュウ", "ライチュウのすがた", "ライチュウ", "",
            "Raichu", "雷丘", "でんき", None, "せいでんき", None, "ひらいしん",
            (60, 90, 55, 90, 80, 110), "RGB", 1, "カントー", "最終進化",
        ),
        _row(
            "0026", "02", "ライチュウ", "アローラのすがた",
            "ライチュウ（アローラのすがた）", "アローラライチュウ,アロライ",
            None, None, "でんき", "エスパー", "サーフテール", None, None,
            (60, 85, 50, 95, 85, 110), "SM", 7, "アローラ", "最終進化",
        ),
        _row(
            "0026", "03", "ライチュウ", "メガライチュウX", "メガライチュウX", "",
            None, None, "でんき", None, "エレキメイカー", None, None,
            (60, 100, 55, 110, 90, 130), "XY", 6, "カロス", "無進化",
        ),
    ]


def test_records_from_rows_numbers_forms_in_order():
    records = pk.records_from_rows(_raichu_rows())

    assert [r.display_number for r in records] == ["26", "26.1", "26.2"]
    assert records[1].name == "ライチュウ（アローラのすがた）"
    assert records[1].aliases == ("アローラライチュウ", "アロライ")
    assert records[2].name == "メガライチュウX"
    assert records[2].evolution_stage == "進化しない"
    assert records[0].stats == (60, 90, 55, 90, 80, 110)
    assert records[0].total == 485


def test_base_form_uses_species_name():
    rows = [
        _row(
            "0479", "00", "ロトム", "ロトムのすがた", "ロトム（ロトムのすがた）", "",
            "Rotom", "洛托姆", "でんき", "ゴースト", "レボリューション", None, None,
            (50, 50, 77, 95, 77, 91), "DP", 4, "シンオウ", "無進化",
        )
    ]
    records = pk.records_from_rows(rows)
    assert records[0].name == "ロトム"


def test_catalog_find_variants_and_get():
    dex = pk.Pokedex(pk.records_from_rows(_raichu_rows()))

    assert [p.display_number for p in dex.find("アロライ")] == ["26.1"]
    assert [p.display_number for p in dex.find("ライチュウ")] == ["26", "26.1", "26.2"]
    assert dex.base("26").display_number == "26"
    assert dex.get("26.2").name == "メガライチュウX"
    assert dex.get("99") is None
    assert dex.find("") == []


def test_catalog_filter_and_random():
    dex = pk.Pokedex(pk.records_from_rows(_raichu_rows()))

    assert [p.display_number for p in dex.filter({"タイプ": ["エスパー"]})] == ["26.1"]
    assert [p.display_number for p in dex.filter({"出身地": ["カロス"]})] == ["26.2"]
    assert [
        p.display_number for p in dex.filter({"進化段階": ["最終進化", "進化しない"]})
    ] == ["26", "26.1", "26.2"]
    assert dex.random({"タイプ": ["みず"]}) is None
    assert dex.random({"タイプ": ["エスパー"]}).display_number == "26.1"


def test_records_from_csv_reads_real_file():
    records = pk.records_from_csv(CSV_PATH)

    assert len(records) == 1208
    pikachu = next(r for r in records if r.display_number == "25")
    assert pikachu.name == "ピカチュウ"
    assert pikachu.eng == "Pikachu"
    assert "ピカチュー" in pikachu.aliases


def test_load_uses_csv_without_password(monkeypatch):
    monkeypatch.delenv("PKDB_PASSWORD", raising=False)
    dex = pk.load_pokedex(CSV_PATH)
    assert len(dex.records) == 1208


def test_load_falls_back_to_csv_on_pkdb_error(monkeypatch):
    monkeypatch.setenv("PKDB_PASSWORD", "dummy")

    def boom():
        raise RuntimeError("接続失敗")

    monkeypatch.setattr(pk, "records_from_pkdb", boom)
    dex = pk.load_pokedex(CSV_PATH)
    assert len(dex.records) == 1208


def test_load_uses_pkdb_when_available(monkeypatch):
    monkeypatch.setenv("PKDB_PASSWORD", "dummy")
    records = pk.records_from_rows(_raichu_rows())
    monkeypatch.setattr(pk, "records_from_pkdb", lambda: records)

    dex = pk.load_pokedex(CSV_PATH)
    assert [r.display_number for r in dex.records] == ["26", "26.1", "26.2"]
