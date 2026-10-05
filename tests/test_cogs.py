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
    "cogs.search",
    "cogs.daily",
    "cogs.settings",
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
    "search",
    "pocketmoney",
    "channel",
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

def test_on_ready_logs_missing_guilds_once_without_warning(caplog):
    import logging

    from main import UBSleepy

    bot = UBSleepy()
    bot.get_guild = lambda guild_id: None

    with caplog.at_level(logging.INFO, logger="ubsleepy"):
        asyncio.run(bot.on_ready())
        asyncio.run(bot.on_ready())

    missing = [r for r in caplog.records if "見つかりません" in r.message]
    assert len(missing) == 1
    assert all(record.levelno < logging.WARNING for record in missing)


def test_on_ready_debug_syncs_only_the_developer_guild(monkeypatch):
    import main

    monkeypatch.setattr(main, "DEBUG_MODE", True)
    monkeypatch.setattr(main, "DEVELOPER_GUILD_ID", "111111111111111111")
    bot = main.UBSleepy()
    synced = []

    async def fake_sync(**kwargs):
        synced.append(kwargs)

    bot.tree.sync = fake_sync
    bot.get_guild = lambda guild_id: type("G", (), {"name": "dev"})()

    asyncio.run(bot.on_ready())

    assert len(synced) == 1
    assert synced[0]["guild"].id == 111111111111111111
