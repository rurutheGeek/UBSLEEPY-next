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
from bot_module.config import DEBUG_MODE, DEVELOPER_GUILD_ID
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
    "cogs.help",
]


def greeting_channel(guild):
    """追加時の案内を送るチャンネル。システムチャンネル→最初のテキスト。"""
    if guild.system_channel is not None:
        return guild.system_channel
    for channel in guild.text_channels:
        return channel
    return None


class UBSleepy(commands.Bot):
    """UBSLEEPY本体。"""

    def __init__(self):
        # 必要なintentだけ要求する。
        # members / message_content は特権intentなので、Developer Portalで有効にする。
        intents = discord.Intents.none()
        intents.guilds = True
        intents.members = True
        intents.guild_messages = True
        intents.message_content = True
        # 鳴き声クイズのボイス再生（入っているVCの取得・退出）に使う
        intents.voice_states = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            activity=discord.Activity(name="研修チュウ", type=discord.ActivityType.unknown),
        )
        self._commands_synced = False

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

        if self._commands_synced:
            return
        self._commands_synced = True

        if DEBUG_MODE:
            # テストBotは開発用ギルドにだけ登録する
            guild = self.get_guild(int(DEVELOPER_GUILD_ID))
            if guild is None:
                ub.output_log(f"登録済のサーバーが見つかりません: {DEVELOPER_GUILD_ID}")
                return
            await self.tree.sync(guild=discord.Object(id=guild.id))
            ub.output_log(f"登録済のサーバーを1個読み込みました\n#0 {guild.name}")
            return

        # コマンドは、居るサーバーそれぞれへギルドコマンドとして登録する（すぐ反映される）。
        # グローバルにも登録すると同じコマンドが2つずつ並ぶので、グローバルは空にする
        # （手元のコマンド定義は、サーバーへ写す元として残す）
        await self.http.bulk_upsert_global_commands(self.application_id, [])
        for guild in self.guilds:
            await self.register_commands(guild)

        synced = [f"\n#{i} {guild.name}" for i, guild in enumerate(self.guilds)]
        ub.output_log(
            f"コマンドを登録しました（{len(self.tree.get_commands())}個）"
            f"{''.join(synced)}")

    async def register_commands(self, guild):
        """コマンドをそのサーバーのギルドコマンドとして登録する。"""
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def on_guild_join(self, guild):
        ub.output_log(f"サーバーに追加されました: {guild.name}（{guild.id}）")
        if not DEBUG_MODE:
            await self.register_commands(guild)
        channel = greeting_channel(guild)
        if channel is None:
            return
        embed = discord.Embed(
            title=f"{self.user.display_name}を追加してくれてありがとう！",
            description=(
                "`/help` でコマンド一覧が見られます。\n"
                "クイズの回答受付や日替わり投稿を使うには、管理者が"
                "`/channel` で投稿先チャンネルを設定してください。"),
            color=0x2EAFFF)
        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException) as error:
            ub.output_warning(f"追加の案内を送れませんでした: {error}")


client = UBSleepy()

# ===================================================================================================
# トークンの取得とBOTの起動

if __name__ == "__main__":
    load_dotenv(override=True)
    client.run(os.environ.get("DISCORD_TOKEN"), reconnect=True)