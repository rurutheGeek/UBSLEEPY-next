# -*- coding: utf-8 -*-
# tests/test_search.py
# サーチの条件解析・評価と、GUIの部品（Embed/View）。
import asyncio

import discord

import bot_module.config  # noqa: F401  設定を読み込むため
from bot_module.pokedex import Pokemon
from bot_module.search import SearchQuery, evaluate_expression, parse_expression
from cogs import search as search_cog


def _pokemon(**overrides):
    values = dict(
        ndex_number="0006",
        form_id="00",
        species="6",
        name="リザードン",
        species_name="リザードン",
        form_name=None,
        aliases=(),
        type_1="ほのお",
        type_2="ひこう",
        ability_1="もうか",
        ability_2=None,
        ability_h="サンパワー",
        hp=78,
        atk=84,
        dfn=78,
        spa=109,
        spd=85,
        spe=100,
        region="カントー",
        evolution_stage="最終進化",
        first_title="RGB",
        generation=1,
        eng="Charizard",
        cht="噴火龍",
        display_number="6",
    )
    values.update(overrides)
    return Pokemon(**values)


PIKACHU = _pokemon(
    ndex_number="0025",
    species="25",
    name="ピカチュウ",
    species_name="ピカチュウ",
    type_1="でんき",
    type_2=None,
    ability_1="せいでんき",
    ability_h="ひらいしん",
    hp=35,
    atk=55,
    dfn=40,
    spa=50,
    spd=50,
    spe=90,
    evolution_stage="中間進化",
    display_number="25",
)


def test_parse_categories_and_unknown():
    query = SearchQuery.parse(["ほのお", "ふゆう", "カントー", "8", "最終進化", "ほげ"])

    assert query.types == ["ほのお"]
    assert query.abilities == ["ふゆう"]
    assert query.regions == ["カントー"]
    assert query.generations == [8]
    assert query.stages == ["最終進化"]
    assert query.unknown == ["ほげ"]
    assert query.has_conditions is True


def test_parse_expression_and_words_round_trip():
    query = SearchQuery.parse(["みず", "A>=100", "合計<600"])

    assert query.to_words() == ["みず", "A>=100", "合計<600"]
    assert SearchQuery.parse(query.to_words()).types == ["みず"]
    labels = dict(query.describe())
    assert labels["タイプ"] == "みず"
    assert "A>=100" in labels["種族値"]


def test_only_unknown_words_have_no_conditions():
    query = SearchQuery.parse(["ほげ", "ふが"])

    assert query.has_conditions is False
    assert query.apply([PIKACHU]) == [PIKACHU]


def test_expression_evaluation():
    charizard = _pokemon()
    assert evaluate_expression(parse_expression("H>=70"), charizard) is True
    assert evaluate_expression(parse_expression("こうげき>=80"), charizard) is True
    assert evaluate_expression(parse_expression("合計>=500"), charizard) is True
    assert evaluate_expression(parse_expression("S>=100"), charizard) is True
    assert evaluate_expression(parse_expression("H>=100"), charizard) is False
    assert evaluate_expression(parse_expression("A+25==C"), charizard) is True
    assert evaluate_expression(parse_expression("A==C"), charizard) is False
    assert evaluate_expression(parse_expression("(H*B)/(B+D)<2000"), charizard) is True
    assert evaluate_expression(parse_expression("Ｈ＞＝７０"), charizard) is True
    assert evaluate_expression(parse_expression("100<=H"), charizard) is False


def test_unsafe_expressions_are_rejected():
    assert parse_expression("__import__('os').system('id')") is None
    assert parse_expression("H.__class__") is None
    assert parse_expression("H**2>=100") is None
    assert parse_expression("(lambda: 1)()") is None
    assert parse_expression("H>=100 and 1") is None
    assert SearchQuery.parse(["__import__('os').system('id')"]).unknown


def test_matches_filters_records():
    records = [_pokemon(), PIKACHU]

    assert SearchQuery.parse(["ほのお", "最終進化"]).apply(records) == [records[0]]
    assert SearchQuery.parse(["でんき"]).apply(records) == [PIKACHU]
    assert SearchQuery.parse(["S>=90"]).apply(records) == records
    assert SearchQuery.parse(["S>=95"]).apply(records) == [records[0]]
    assert SearchQuery.parse(["8"]).apply(records) == []


def test_panel_embed_has_query_and_conditions():
    embed = search_cog.build_panel_embed(SearchQuery.parse(["みず", "8"]))

    assert embed.description == "条件: みず 8"
    names = [field.name for field in embed.fields]
    assert "現在の検索条件" in names
    assert "使い方" in names


def test_result_embed_lists_page():
    embed = search_cog.build_result_embed(SearchQuery.parse(["でんき"]), [PIKACHU], 0)

    assert embed.title == "検索結果: 1匹 (ページ 1/1)"
    names = [field.name for field in embed.fields]
    assert "No.25 ピカチュウ" in names
    assert search_cog._page_from_embed(embed) == 0
    assert search_cog._words_from_embed(embed) == ["でんき"]


def test_result_embed_pages():
    records = [_pokemon(display_number=str(i), name=f"ポケモン{i}") for i in range(15)]
    embed = search_cog.build_result_embed(SearchQuery(), records, 1)

    assert embed.title == "検索結果: 15匹 (ページ 2/2)"
    listed = [field.name for field in embed.fields if field.name.startswith("No.")]
    assert len(listed) == 5


def test_panel_view_marks_selected_values():
    async def build():
        return search_cog.SearchPanelView(["みず", "8", "最終進化", "カントー"])

    view = asyncio.run(build())
    selects = {
        child.custom_id: child
        for child in view.children
        if isinstance(child, discord.ui.Select)
    }

    assert [option.value for option in selects["search_type"].options if option.default] == ["みず"]
    assert [option.value for option in selects["search_generation"].options if option.default] == ["8"]
    assert [option.value for option in selects["search_stage"].options if option.default] == ["最終進化"]
    assert [option.value for option in selects["search_region"].options if option.default] == ["カントー"]


def test_result_view_disables_edges():
    async def build(page):
        return search_cog.SearchResultView(page=page, pages=3)

    first = asyncio.run(build(0))
    buttons = {child.custom_id: child for child in first.children}
    assert buttons["search_prev"].disabled is True
    assert buttons["search_next"].disabled is False

    last = asyncio.run(build(2))
    buttons = {child.custom_id: child for child in last.children}
    assert buttons["search_prev"].disabled is False
    assert buttons["search_next"].disabled is True


def test_modal_keeps_default_query():
    async def build():
        return search_cog.SearchModal("みず 8")

    modal = asyncio.run(build())
    assert modal.query_input.default == "みず 8"


class FakeResponse:
    def __init__(self):
        self.edits = []
        self.messages = []

    async def edit_message(self, **kwargs):
        self.edits.append(kwargs)

    async def send_message(self, *args, **kwargs):
        self.messages.append(kwargs)


class FakeInteraction:
    def __init__(self, embed):
        self.message = type("Message", (), {"embeds": [embed]})()
        self.response = FakeResponse()


def _find(view, custom_id):
    return next(child for child in view.children if child.custom_id == custom_id)


def test_type_select_updates_panel_query():
    async def run():
        view = search_cog.SearchPanelView(["みず"])
        interaction = FakeInteraction(
            search_cog.build_panel_embed(SearchQuery.parse(["みず"]))
        )
        select = _find(view, "search_type")
        select._values = ["みず", "でんき"]
        await select.callback(interaction)
        return interaction

    interaction = asyncio.run(run())
    embed = interaction.response.edits[0]["embed"]
    assert search_cog._words_from_embed(embed) == ["みず", "でんき"]


def test_run_button_requires_conditions():
    async def run():
        view = search_cog.SearchPanelView()
        interaction = FakeInteraction(search_cog.build_panel_embed(SearchQuery()))
        await _find(view, "search_run").callback(interaction)
        return interaction

    interaction = asyncio.run(run())
    assert interaction.response.messages[0]["ephemeral"] is True


def test_run_button_sends_results():
    async def run():
        view = search_cog.SearchPanelView(["でんき"])
        interaction = FakeInteraction(
            search_cog.build_panel_embed(SearchQuery.parse(["でんき"]))
        )
        await _find(view, "search_run").callback(interaction)
        return interaction

    interaction = asyncio.run(run())
    embed = interaction.response.messages[0]["embed"]
    assert embed.title.startswith("検索結果:")
    assert interaction.response.messages[0]["ephemeral"] is True


def test_page_button_moves_page():
    async def run():
        query = SearchQuery.parse(["でんき"])
        results = query.apply(search_cog.get_pokedex().records)
        embed = search_cog.build_result_embed(query, results, 0)
        interaction = FakeInteraction(embed)
        await _find(search_cog.SearchResultView(), "search_next").callback(interaction)
        return interaction

    interaction = asyncio.run(run())
    embed = interaction.response.edits[0]["embed"]
    assert "(ページ 2/" in embed.title
