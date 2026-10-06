# -*- coding: utf-8 -*-
# tests/test_help.py
import asyncio

import discord
from discord.ext import commands

import cogs.help as help_module

COGS = [
    "cogs.pokedex",
    "cogs.quiz",
    "cogs.search",
    "cogs.daily",
    "cogs.settings",
    "cogs.logs",
    "cogs.help",
]


def _load():
    bot = commands.Bot(
        command_prefix=commands.when_mentioned, intents=discord.Intents.none())

    async def _load_all():
        for cog in COGS:
            await bot.load_extension(cog)

    asyncio.run(_load_all())
    return bot


def test_overview_lists_commands():
    bot = _load()
    embed = bot.get_cog('Help')._overview()
    assert '/dex' in embed.description
    assert '/pocketmoney' in embed.description
    assert '/search' in embed.description


def test_overview_lists_the_text_commands():
    bot = _load()
    embed = bot.get_cog('Help')._overview()
    assert '/bqdata' in embed.description
    assert '/crydata' in embed.description


def test_text_command_detail_explains_the_modes():
    text = next(t for t in help_module.TEXT_COMMANDS if t[0] == 'crydata')
    embed = help_module.Help._text_detail(text)
    assert '/crydata' in embed.title
    assert '今' in embed.title and '昔' in embed.title  # モード
    assert '地方' in embed.description  # 絞り込みの例


def test_detail_for_a_command_lists_parameters():
    bot = _load()
    help_cog = bot.get_cog('Help')
    command = next(c for c in help_cog._commands() if c.name == 'dex')
    embed = help_cog._detail(command)
    assert [field.name for field in embed.fields] == ['name']
    assert '必須' in embed.fields[0].value
