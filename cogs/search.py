# -*- coding: utf-8 -*-
# cogs/search.py
"""ポケモンサーチャー（/search）。

GUI（タイプ・世代・進化段階・地方のメニューと検索ボタン）を主に、
クエリ文字列とモーダルでも指定できる。パネルの状態はEmbedの
「条件:」行だけに持つので、Botを再起動してもボタンが動く。
"""
import re

import discord
from discord.ext import commands

import bot_module.config as cfg
from bot_module.pokedex import get_pokedex
from bot_module.search import SearchQuery

GUILDS = [discord.Object(id=guild_id) for guild_id in cfg.GUILD_IDS]

PAGE_SIZE = 10
_QUERY_PREFIX = "条件: "
_PAGE_PATTERN = re.compile(r"ページ\s*(\d+)\s*/\s*(\d+)")
_EVOLUTION_CHOICES = ("進化前", "中間進化", "最終進化", "進化しない")


def _query_line(query: SearchQuery) -> str:
    words = query.to_words()
    return _QUERY_PREFIX + (" ".join(words) if words else "(なし)")


def _words_from_embed(embed: discord.Embed) -> list[str]:
    for line in (embed.description or "").splitlines():
        if line.startswith(_QUERY_PREFIX):
            text = line[len(_QUERY_PREFIX):].strip()
            if text and text != "(なし)":
                return text.split()
    return []


def _page_from_embed(embed: discord.Embed) -> int:
    footer = embed.footer.text if embed.footer else None
    for text in (footer, embed.title):
        match = _PAGE_PATTERN.search(text or "")
        if match:
            return int(match.group(1)) - 1
    return 0


def _page_count(total: int) -> int:
    return max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)


def build_panel_embed(query: SearchQuery) -> discord.Embed:
    embed = discord.Embed(title="ポケモンサーチャー", color=0x00FF7F)
    embed.description = _query_line(query)
    conditions = query.describe()
    if conditions:
        embed.add_field(
            name="現在の検索条件",
            value="\n".join(f"**{name}**: {value}" for name, value in conditions),
            inline=False,
        )
    else:
        embed.add_field(name="現在の検索条件", value="(なし)", inline=False)
    embed.add_field(
        name="使い方",
        value=(
            "下のメニューで絞り込み、「検索する」を押してください。\n"
            "タイプ・特性は複数選ぶと**両方を持つ**ポケモンに絞ります（地方・世代・進化段階はどれか）。\n"
            "直接入力では `ノーマル&ひこう` で両方、`ノーマル ひこう` や `ノーマル|ひこう` でどちらかです。\n"
            "種族値の例: `ふゆう A>=130 合計<600`"
        ),
        inline=False,
    )
    embed.set_footer(text="No.27 ポケモンサーチャー")
    return embed


def build_result_embed(
    query: SearchQuery, results: list, page: int = 0
) -> discord.Embed:
    pages = _page_count(len(results))
    page = min(max(page, 0), pages - 1)
    embed = discord.Embed(
        title=f"検索結果: {len(results)}匹 (ページ {page + 1}/{pages})",
        color=0x00FF7F,
    )
    embed.description = _query_line(query)
    if conditions := query.describe():
        embed.add_field(
            name="条件",
            value=" / ".join(f"{name}: {value}" for name, value in conditions),
            inline=False,
        )
    for pokemon in results[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]:
        embed.add_field(
            name=f"No.{pokemon.display_number} {pokemon.name}",
            value=(
                f"`{'-'.join(map(str, pokemon.stats))} 合計{pokemon.total}`\n"
                f"{'/'.join(pokemon.types) or 'なし'} ・ "
                f"{pokemon.region or '不明'} ・ {pokemon.evolution_stage or '不明'}"
            ),
            inline=False,
        )
    embed.set_footer(text=f"No.27 ポケモンサーチャー - ページ {page + 1}/{pages}")
    return embed


async def _update_panel(interaction: discord.Interaction, category: str, values):
    words = _words_from_embed(interaction.message.embeds[0])
    query = SearchQuery.parse(words)
    if category == "type":
        query.types = list(values)
        query.types_any = []
    elif category == "generation":
        query.generations = [int(value) for value in values]
    elif category == "stage":
        query.stages = list(values)
    elif category == "region":
        query.regions = list(values)
    await interaction.response.edit_message(
        embed=build_panel_embed(query), view=SearchPanelView(query.to_words())
    )


async def _send_results(interaction: discord.Interaction, query: SearchQuery):
    results = query.apply(get_pokedex().records)
    pages = _page_count(len(results))
    await interaction.response.send_message(
        embed=build_result_embed(query, results, 0),
        view=SearchResultView(page=0, pages=pages),
        ephemeral=True,
    )


class _TypeSelect(discord.ui.Select):
    def __init__(self, query: SearchQuery):
        options = [
            discord.SelectOption(
                label=type_name,
                value=type_name,
                default=type_name in query.types or type_name in query.types_any,
            )
            for type_name in sorted(get_pokedex().types())
        ]
        super().__init__(
            placeholder="タイプで絞り込む（2つまで・両方に一致）",
            custom_id="search_type",
            min_values=0,
            max_values=2,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        await _update_panel(interaction, "type", self.values)


class _ChoiceSelect(discord.ui.Select):
    def __init__(self, category, placeholder, choices, selected):
        self.category = category
        options = [
            discord.SelectOption(label=label, value=value, default=value in selected)
            for value, label in choices
        ]
        super().__init__(
            placeholder=placeholder,
            custom_id=f"search_{category}",
            min_values=0,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        await _update_panel(interaction, self.category, self.values)


class _RunButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="検索する", style=discord.ButtonStyle.primary, custom_id="search_run"
        )

    async def callback(self, interaction: discord.Interaction):
        query = SearchQuery.parse(_words_from_embed(interaction.message.embeds[0]))
        if not query.has_conditions:
            await interaction.response.send_message(
                "条件を選ぶか、「直接入力」で指定してください。", ephemeral=True
            )
            return
        await _send_results(interaction, query)


class _ResetButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="リセット", style=discord.ButtonStyle.secondary, custom_id="search_reset"
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=build_panel_embed(SearchQuery()), view=SearchPanelView()
        )


class _ModalButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="直接入力", style=discord.ButtonStyle.success, custom_id="search_modal"
        )

    async def callback(self, interaction: discord.Interaction):
        words = _words_from_embed(interaction.message.embeds[0])
        await interaction.response.send_modal(SearchModal(" ".join(words)))


class _PageButton(discord.ui.Button):
    def __init__(self, label, custom_id, delta, style, disabled):
        self.delta = delta
        super().__init__(label=label, custom_id=custom_id, style=style, disabled=disabled)

    async def callback(self, interaction: discord.Interaction):
        embed = interaction.message.embeds[0]
        query = SearchQuery.parse(_words_from_embed(embed))
        results = query.apply(get_pokedex().records)
        page = _page_from_embed(embed) + self.delta
        pages = _page_count(len(results))
        await interaction.response.edit_message(
            embed=build_result_embed(query, results, page),
            view=SearchResultView(page=page, pages=pages),
        )


class _AgainButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="条件を変える", style=discord.ButtonStyle.success, custom_id="search_again"
        )

    async def callback(self, interaction: discord.Interaction):
        query = SearchQuery.parse(_words_from_embed(interaction.message.embeds[0]))
        await interaction.response.send_message(
            embed=build_panel_embed(query),
            view=SearchPanelView(query.to_words()),
            ephemeral=True,
        )


class SearchModal(discord.ui.Modal, title="検索条件の入力"):
    query_input = discord.ui.TextInput(
        label="検索条件",
        placeholder="例: みず ふゆう 8 A>=130",
        max_length=100,
        required=True,
    )

    def __init__(self, default: str = ""):
        super().__init__()
        self.query_input.default = default

    async def on_submit(self, interaction: discord.Interaction):
        await _send_results(interaction, SearchQuery.parse(str(self.query_input.value).split()))


class SearchPanelView(discord.ui.View):
    """条件選択のパネル。timeout=Noneで再起動後もボタンが効く。"""

    def __init__(self, words=None):
        super().__init__(timeout=None)
        query = SearchQuery.parse(words or [])
        self.add_item(_TypeSelect(query))
        self.add_item(
            _ChoiceSelect(
                "generation",
                "世代で絞り込む",
                [(str(number), f"第{number}世代") for number in range(1, 10)],
                [str(generation) for generation in query.generations],
            )
        )
        self.add_item(
            _ChoiceSelect(
                "stage",
                "進化段階で絞り込む",
                [(stage, stage) for stage in _EVOLUTION_CHOICES],
                query.stages,
            )
        )
        self.add_item(
            _ChoiceSelect(
                "region",
                "地方で絞り込む",
                [(region, region) for region in sorted(get_pokedex().regions())],
                query.regions,
            )
        )
        self.add_item(_RunButton())
        self.add_item(_ResetButton())
        self.add_item(_ModalButton())


class SearchResultView(discord.ui.View):
    def __init__(self, page: int = 0, pages: int = 1):
        super().__init__(timeout=None)
        self.add_item(
            _PageButton("前へ", "search_prev", -1, discord.ButtonStyle.secondary, page <= 0)
        )
        self.add_item(
            _PageButton("次へ", "search_next", 1, discord.ButtonStyle.primary, page >= pages - 1)
        )
        self.add_item(_AgainButton())


class Search(commands.Cog):
    """ポケモンサーチャー。"""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(SearchPanelView())
        self.bot.add_view(SearchResultView())

    @discord.app_commands.command(
        name="search", description="タイプや種族値などの条件でポケモンを検索します"
    )
    @discord.app_commands.guilds(*GUILDS)
    @discord.app_commands.describe(
        query="検索条件。未記入でGUIが開きます（例: みず ふゆう 8 A>=130）"
    )
    async def search(self, interaction: discord.Interaction, query: str = None):
        if query:
            await _send_results(interaction, SearchQuery.parse(query.split()))
        else:
            await interaction.response.send_message(
                embed=build_panel_embed(SearchQuery()),
                view=SearchPanelView(),
                ephemeral=True,
            )


async def setup(bot):
    await bot.add_cog(Search(bot))
