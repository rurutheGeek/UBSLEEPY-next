# -*- coding: utf-8 -*-
# cogs/auth.py
"""入室時の案内と学籍番号の受け付け。

サーバー固有の機能なので、将来は認証Bot（別リポジトリ・別トークン）へ移す。
"""
import os
import random
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands
import numpy as np
import pandas as pd

import bot_module.config as cfg
import bot_module.func as ub

GUILDS = [discord.Object(id=guild_id) for guild_id in cfg.GUILD_IDS]


class Auth(commands.Cog):
    """新規メンバーの案内と、学籍番号・好きなポケモンの登録。"""

    def __init__(self, bot):
        self.bot = bot

    # 新規メンバーが参加したときの処理
    @commands.Cog.listener()
    async def on_member_join(self, member):
        if not member.bot:
            await member.add_roles(
                member.guild.get_role(cfg.UNKNOWN_ROLE_ID)
            )  # ロールがある場合に付与に変更
            ub.output_log(f"ロールを付与しました: {member.name}にID{cfg.UNKNOWN_ROLE_ID}")
            if helloCh := self.bot.get_channel(cfg.HELLO_CHANNEL_ID):
                helloEmbed = discord.Embed(
                    title="メンバー認証ボタンを押して 学籍番号を送信してね",
                    color=0x5EFF24,
                    description="送信するとサーバーが使用可能になります\n工学院大学の学生でない人は個別にご相談ください",
                )
                helloEmbed.set_author(name=f"{member.guild.name}の せかいへ ようこそ!")
                helloEmbed.add_field(
                    name="サーバーの ガイドラインは こちら",
                    value=f"{cfg.BALL_ICON}<#1067423922477355048>",
                    inline=False,
                )
                helloEmbed.add_field(
                    name="みんなにみせるロールを 変更する",
                    value=f"{cfg.BALL_ICON}<#1068903858790731807>",
                    inline=False,
                )
                helloEmbed.set_thumbnail(
                    url=f"{cfg.EX_SOURCE_LINK}sprites/Gen1/{random.randint(1, 151)}.png"
                )

                authButton = discord.ui.Button(
                    label="メンバー認証",
                    style=discord.ButtonStyle.primary,
                    custom_id="authButton",
                )
                helloView = discord.ui.View()
                helloView.add_item(authButton)

                await helloCh.send(
                    f"はじめまして! {member.mention}さん", embed=helloEmbed, view=helloView
                )
                ub.output_log(f"サーバーにメンバーが参加しました: {member.name}")
            else:
                ub.output_log(f"チャンネルが見つかりません: {cfg.HELLO_CHANNEL_ID}")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """メンバー認証ボタンと、学籍番号モーダルの送信を処理する。"""
        data = interaction.data or {}
        custom_id = data.get("custom_id")

        # ボタン: モーダルを開く
        if data.get("component_type") == 2 and custom_id == "authButton":
            ub.output_log(
                f'buttonが押されました\n {interaction.user.name}: {custom_id}'
            )
            ub.output_log("学籍番号取得を実行します")
            authModal = discord.ui.Modal(
                title="メンバー認証", timeout=None, custom_id="authModal"
            )
            authInput = discord.ui.TextInput(
                label="学籍番号",
                placeholder="J111111",
                min_length=7,
                max_length=7,
                custom_id="studentIdInput",
            )
            authModal.add_item(authInput)
            favePokeInput = discord.ui.TextInput(
                label="好きなポケモン(任意)",
                placeholder="ヤブクロン",
                required=False,
                custom_id="favePokeInput",
            )
            authModal.add_item(favePokeInput)
            await interaction.response.send_modal(authModal)
            return

        # モーダル送信: 学籍番号を照合する
        if custom_id != "authModal":
            return

        ub.output_log("学籍番号を処理します")
        listPath = cfg.MEMBERDATA_PATH
        studentId = data["components"][0]["components"][0]["value"]

        if (
            (studentId := studentId.upper()).startswith(
                ("S", "A", "C", "J", "D", "B", "E", "G")
            )
            and re.match(r"^[A-Z0-9]+$", studentId)
            and len(studentId) == 7
        ):
            member = interaction.user
            role = interaction.guild.get_role(cfg.UNKNOWN_ROLE_ID)
            favePokeName = data["components"][1]["components"][0]["value"]
            response = "登録を修正したい場合はもう一度ボタンを押してください"

            if role in member.roles:  # ロールを持っていれば削除
                await member.remove_roles(role)
                response += "\nサーバーが利用可能になりました"
                ub.output_log(f"学籍番号が登録されました\n {member.name}: {studentId}")
            else:
                ub.output_log(
                    f"登録の修正を受け付けました\n {member.name}: {studentId}"
                )
            response += "\n`※このメッセージはあなたにしか表示されていません`"

            thanksEmbed = discord.Embed(
                title="登録ありがとうございました", color=0x2EAFFF, description=response
            )
            thanksEmbed.add_field(name="登録した学籍番号", value=studentId)
            thanksEmbed.add_field(
                name="好きなポケモン",
                value=favePokeName if not favePokeName == "" else "登録なし",
            )

            if not favePokeName == "":
                if (favePokedata := ub.fetch_pokemon(favePokeName)) is not None:
                    favePokeName = favePokedata.iloc[0]["おなまえ"]

            times = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y/%m/%d %H:%M:%S")
            authData = {
                "登録日時": [times],
                "ユーザーID": [str(member.id)],
                "ユーザー名": [member.name],
                "学籍番号": [studentId],
                "好きなポケモン": [favePokeName],
            }
            df = pd.DataFrame(authData)
            df.to_csv(
                cfg.MEMBERLIST_PATH,
                mode="a",
                index=False,
                header=not os.path.exists(cfg.MEMBERLIST_PATH),
            )

            content = "照合に失敗しました ?\n※メンバーリストにまだ学籍番号のデータがない可能性があります"
            if os.path.exists(listPath):
                member_df = pd.read_csv(listPath).set_index("学籍番号")
                if studentId in member_df.index:
                    memberData = pd.DataFrame(
                        {
                            "ユーザーID": [member.id],
                            "ユーザー名": [member.name],
                            "好きなポケモン": [favePokeName],
                        },
                        index=[studentId],
                    ).iloc[0]
                    member_df.loc[studentId] = memberData
                    member_df["ユーザーID"] = (
                        member_df["ユーザーID"]
                        .dropna()
                        .replace([np.inf, -np.inf], np.nan)
                        .dropna()
                        .astype(int)
                    )

                    member_df.to_csv(listPath, index=True, float_format="%.0f")
                    content = "照合に成功しました"
                    ub.output_log(
                        f"サークルメンバー照合ができました\n {studentId}: {member.name}"
                    )
                else:
                    ub.output_log(
                        f"サークルメンバー照合ができませんでした\n {studentId}: {member.name}"
                    )
            else:
                ub.output_log(f"認証用   ファイルが存在しません: {listPath}")

            await interaction.response.send_message(
                content, embed=thanksEmbed, ephemeral=True
            )

        else:  # 学籍番号が送信されなかった場合の処理
            ub.output_log(f"学籍番号として認識されませんでした: {studentId}")
            errorEmbed = discord.Embed(
                title="401 Unauthorized",
                color=0xFF0000,
                description=f"あなたの入力した学籍番号: **{studentId}**\n申し訳ございませんが、もういちどお試しください。",
            )
            errorEmbed.set_author(
                name="Porygon-Z.com", url="https://wiki.ポケモン.com/wiki/ポリゴンZ"
            )
            errorEmbed.set_thumbnail(url=f"{cfg.EX_SOURCE_LINK}art/474.png")
            errorEmbed.add_field(
                name="入力形式は合っていますか?",
                value="半角英数字7ケタで入力してください",
                inline=False,
            )
            errorEmbed.add_field(
                name="工学院生ではありませんか?",
                value="個別にご相談ください",
                inline=False,
            )
            errorEmbed.add_field(
                name="解決しない場合",
                value=f"管理者にお問い合わせください: <@!{cfg.DEVELOPER_USER_ID}>",
                inline=False,
            )
            await interaction.response.send_message(embed=errorEmbed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Auth(bot))