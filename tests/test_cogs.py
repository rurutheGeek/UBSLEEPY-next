# -*- coding: utf-8 -*-
# tests/test_cogs.py
# Cogを読み込み、登録されるスラッシュコマンドが従来と同じであることを確認する。
import asyncio

import discord
from discord.ext import commands

import bot_module.config as cfg

COGS = [
    "cogs.pokedex",
    "cogs.quiz",
    "cogs.daily",
    "cogs.calls",
    "cogs.auth",
    "cogs.logs",
    "cogs.admin",
]

EXPECTED_COMMANDS = {
    "dex",
    "comp",
    "simil",
    "q",
    "quizrate",
    "bmode",
    "pocketmoney",
    "calltitle",
    "invite",
    "devtest",
    "devlogin",
    "devimport",
}


def _load_all(bot):
    async def _load():
        for cog in COGS:
            await bot.load_extension(cog)

    asyncio.run(_load())


def _registered_command_names(bot):
    names = {command.name for command in bot.tree.get_commands()}
    for guild_id in cfg.GUILD_IDS:
        names |= {
            command.name
            for command in bot.tree.get_commands(guild=discord.Object(id=guild_id))
        }
    return names


def test_cogs_register_expected_commands():
    bot = commands.Bot(
        command_prefix=commands.when_mentioned, intents=discord.Intents.none()
    )
    _load_all(bot)
    assert _registered_command_names(bot) == EXPECTED_COMMANDS


def test_main_setup_hook_loads_all_cogs():
    from main import COGS as MAIN_COGS
    from main import UBSleepy

    bot = UBSleepy()
    asyncio.run(bot.setup_hook())

    assert set(bot.extensions) == set(MAIN_COGS)
    assert _registered_command_names(bot) == EXPECTED_COMMANDS