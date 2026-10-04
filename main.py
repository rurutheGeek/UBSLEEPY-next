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
from bot_module.config import DEBUG_MODE, GUILD_IDS
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
    "cogs.logs",
    "cogs.admin",
]


class UBSleepy(commands.Bot):
    """UBSLEEPY本体。"""

    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.all(),
            activity=discord.Activity(name="研修チュウ", type=discord.ActivityType.unknown),
        )

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

        if len(GUILD_IDS) == 0:
            ub.output_log("登録済のサーバーが0個です")
        else:
            syncGuildName = ""
            i = 0
            for guild_id in GUILD_IDS:
                #self.get_guild(guild_id)がNoneの場合はスキップ
                if self.get_guild(guild_id) is None:
                    ub.output_warning(f"登録済のサーバーが見つかりません: {guild_id}")
                    continue
                syncGuildName += f"\n#{i} {self.get_guild(guild_id).name}"
                await self.tree.sync(guild=discord.Object(id=guild_id))
                i += 1
            ub.output_log(
                f"登録済のサーバーを{len(GUILD_IDS)}個読み込みました{syncGuildName}"
            )


client = UBSleepy()

# ===================================================================================================
# トークンの取得とBOTの起動

if __name__ == "__main__":
    load_dotenv(override=True)
    client.run(os.environ.get("DISCORD_TOKEN"), reconnect=True)