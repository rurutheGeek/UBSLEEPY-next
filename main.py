#!/usr/bin/python3
# -*- coding: utf-8 -*-
# main.py
# 起動とCogの読み込みだけを行う。

# 標準ライブラリ
import os

# 外部ライブラリ
import discord
from discord.ext import commands
from dotenv import load_dotenv  # type: ignore

# 分割されたモジュール
from bot_module.config import DEBUG_MODE, DEVELOPER_GUILD_ID, GUILD_IDS
import bot_module.func as ub
from bot_module.logging_setup import setup_logging
from bot_module.pokedex import get_pokedex

# main.pyのディレクトリに移動
os.chdir(os.path.dirname(os.path.abspath(__file__)))

setup_logging()

COGS = [
    "cogs.pokedex",
    "cogs.quiz",
    "cogs.search",
    "cogs.daily",
    "cogs.settings",
    "cogs.logs",
]


class UBSleepy(commands.Bot):
    """UBSLEEPY本体。"""

    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.all(),
            activity=discord.Activity(name="研修チュウ", type=discord.ActivityType.unknown),
        )
        self._missing_guilds_logged = False

    async def setup_hook(self):
        # 図鑑カタログを先に読み込む（pkdbが無ければCSV）
        get_pokedex()
        for cog in COGS:
            await self.load_extension(cog)

    async def on_message(self, message):
        # prefixコマンドは処理しない。Cogのon_messageリスナーだけを動かす。
        pass

    async def on_ready(self):
        if DEBUG_MODE:
            ub.output_log("debugモードで起動します")

        # デバッグ時は開発用ギルドだけを見る（テストBotは本番サーバーにいない）
        guild_ids = [int(DEVELOPER_GUILD_ID)] if DEBUG_MODE else list(GUILD_IDS)
        if not guild_ids:
            ub.output_log("登録済のサーバーが0個です")
            return

        synced = []
        missing = []
        for guild_id in guild_ids:
            guild = self.get_guild(guild_id)
            if guild is None:
                missing.append(str(guild_id))
                continue
            synced.append(f"\n#{len(synced)} {guild.name}")
            await self.tree.sync(guild=discord.Object(id=guild_id))

        if synced:
            ub.output_log(f"登録済のサーバーを{len(synced)}個読み込みました{''.join(synced)}")
        if missing and not self._missing_guilds_logged:
            # 再接続のたびに警告を出さない。1回だけINFOで残す。
            ub.output_log(f"登録済のサーバーが見つかりません: {', '.join(missing)}")
            self._missing_guilds_logged = True


client = UBSleepy()

# ===================================================================================================
# トークンの取得とBOTの起動

if __name__ == "__main__":
    load_dotenv(override=True)
    client.run(os.environ.get("DISCORD_TOKEN"), reconnect=True)