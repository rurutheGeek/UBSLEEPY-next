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


def _guild_only_bot(monkeypatch):
    import main

    monkeypatch.setattr(main, "DEBUG_MODE", False)
    bot = main.UBSleepy()
    calls = []

    async def fake_sync(*, guild=None):
        calls.append(("sync", guild.id if guild else None))
        return []

    async def fake_upsert(application_id, payload):
        calls.append(("global", payload))

    bot.tree.sync = fake_sync
    bot.tree.copy_global_to = lambda guild: calls.append(("copy", guild.id))
    monkeypatch.setattr(bot.http, "bulk_upsert_global_commands", fake_upsert)
    monkeypatch.setattr(
        type(bot), "application_id", property(lambda self: 1), raising=False)
    return bot, calls


def test_on_ready_registers_guild_commands_only(monkeypatch):
    import main

    bot, calls = _guild_only_bot(monkeypatch)
    guilds = [type("G", (), {"id": guild_id, "name": "g"})() for guild_id in (11, 22)]
    monkeypatch.setattr(main.UBSleepy, "guilds", property(lambda self: guilds))

    asyncio.run(bot.on_ready())

    # グローバルは空にし、居るサーバーごとにギルドコマンドを登録（2つずつ並ばないように）
    expected = [("global", []), ("copy", 11), ("sync", 11), ("copy", 22), ("sync", 22)]
    assert calls == expected

    # 2回目のon_readyは何もしない
    asyncio.run(bot.on_ready())
    assert calls == expected


def test_a_joined_guild_gets_the_commands(monkeypatch):
    bot, calls = _guild_only_bot(monkeypatch)
    guild = type("G", (), {"id": 33, "name": "new", "system_channel": None,
                           "text_channels": []})()

    asyncio.run(bot.on_guild_join(guild))

    assert calls == [("copy", 33), ("sync", 33)]


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
