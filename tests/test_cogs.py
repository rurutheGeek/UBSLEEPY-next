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
    "cogs.help",
]

EXPECTED_COMMANDS = {
    "dex",
    "comp",
    "simil",
    "q",
    "quizrecord",
    "bmode",
    "search",
    "pocketmoney",
    "channel",
    "role",
    "help",
}


def _load_all(bot):
    async def _load():
        for cog in COGS:
            await bot.load_extension(cog)

    asyncio.run(_load())


def _global_command_names(bot):
    return {command.name for command in bot.tree.get_commands()}


def test_cogs_register_expected_commands_globally():
    bot = commands.Bot(
        command_prefix=commands.when_mentioned, intents=discord.Intents.none()
    )
    _load_all(bot)
    assert _global_command_names(bot) == EXPECTED_COMMANDS
    # 通常起動ではグローバル登録（ギルド限定コマンドは無い）
    for guild_id in cfg.GUILD_IDS:
        assert bot.tree.get_commands(guild=discord.Object(id=guild_id)) == []


def test_main_setup_hook_loads_all_cogs():
    from main import COGS as MAIN_COGS
    from main import UBSleepy

    bot = UBSleepy()
    asyncio.run(bot.setup_hook())

    assert set(bot.extensions) == set(MAIN_COGS)
    assert _global_command_names(bot) == EXPECTED_COMMANDS


def test_on_ready_syncs_globally_and_clears_the_guild_copies(monkeypatch):
    import main

    monkeypatch.setattr(main, "DEBUG_MODE", False)
    monkeypatch.setattr(main, "GUILD_IDS", [111111111111111111])
    bot = main.UBSleepy()
    calls = []
    cleared = []

    async def fake_sync(*, guild=None):
        calls.append(guild.id if guild else None)
        return []

    bot.tree.sync = fake_sync
    bot.tree.clear_commands = lambda guild: cleared.append(guild.id)
    bot.get_guild = lambda guild_id: type("G", (), {"id": guild_id})()

    asyncio.run(bot.on_ready())

    # グローバルだけ登録し、クラブのギルドに残るコピーは消す（2つずつ並ばないように）
    assert calls == [None, 111111111111111111]
    assert cleared == [111111111111111111]

    # 2回目のon_readyは何もしない
    asyncio.run(bot.on_ready())
    assert calls == [None, 111111111111111111]


def test_on_ready_debug_syncs_only_the_developer_guild(monkeypatch):
    import main

    monkeypatch.setattr(main, "DEBUG_MODE", True)
    monkeypatch.setattr(main, "DEVELOPER_GUILD_ID", "111111111111111111")
    bot = main.UBSleepy()
    synced = []

    async def fake_sync(**kwargs):
        synced.append(kwargs)

    bot.tree.sync = fake_sync
    bot.get_guild = lambda guild_id: type(
        "G", (), {"name": "dev", "id": 111111111111111111})()

    asyncio.run(bot.on_ready())

    assert len(synced) == 1
    assert synced[0]["guild"].id == 111111111111111111
