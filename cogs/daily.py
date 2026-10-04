# -*- coding: utf-8 -*-
# cogs/daily.py
"""日替わり投稿・ログ投稿・おこづかい・IDくじ。"""
import random
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks
import pandas as pd

import bot_module.config as cfg
import bot_module.embed as ub_embed
import bot_module.func as ub

GUILDS = [discord.Object(id=guild_id) for guild_id in cfg.GUILD_IDS]

# 最後に日替わり投稿を出した日付を残すファイル（save/ はバックアップ対象）
LAST_DAILY_PATH = "save/last_daily.txt"


def read_last_daily_date() -> str | None:
    """最後に日替わり投稿を出した日付（%Y/%m/%d）を返す。無ければNone。"""
    try:
        with open(LAST_DAILY_PATH, encoding="utf-8") as file:
            value = file.read().strip()
    except FileNotFoundError:
        return None
    return value or None


def save_last_daily_date(day: datetime) -> None:
    with open(LAST_DAILY_PATH, "w", encoding="utf-8") as file:
        file.write(day.strftime("%Y/%m/%d"))


def should_post_daily(last_date: str | None, now: datetime) -> bool:
    """起動時に日替わり投稿を出すべきか。5時前は出さない。"""
    if now.hour < 5:
        return False
    return last_date != now.strftime("%Y/%m/%d")


async def post_daily(bot, now: datetime, channelid: int):
    """日付が変わったときの投稿（時報・カレンダー・川柳・IDくじ）。"""
    ub.output_log("ログインジョブを実行します")
    todayId = str(random.randint(0, 99999)).zfill(5)

    dairyIdEmbed = discord.Embed(
        title="IDくじセンター 抽選コーナー",
        color=0xFF297E,
        description=f"くじのナンバーと ユーザーIDが みごと あってると ステキな 景品を もらえちゃうんだロ{cfg.BANGBANG_ICON}",
    )
    dairyIdEmbed.add_field(
        name=f"{cfg.BALL_ICON}今日のナンバー", value=f"**{todayId}**", inline=False
    )
    dairyIdEmbed.set_footer(text="No.15 IDくじ")

    lotoButton = discord.ui.Button(
        label="くじをひく",
        style=discord.ButtonStyle.primary,
        custom_id=f'lotoIdButton:{todayId}:{datetime.now(ZoneInfo("Asia/Tokyo")).date()}',
    )
    dairyView = discord.ui.View()
    dairyView.add_item(lotoButton)

    lotoReset = pd.read_csv(cfg.REPORT_PATH)
    lotoReset["クジびきけん"] = 1
    lotoReset.to_csv(cfg.REPORT_PATH, index=False)

    dairyChannel = bot.get_channel(channelid)
    day = datetime.now(ZoneInfo("Asia/Tokyo"))
    await dairyChannel.send(
        f'日付が変わりました。 {day.strftime("%Y/%m/%d")} ({cfg.WEAK_DICT[str(day.weekday())]})',
        embeds=[ub.show_calendar(day), ub.show_senryu(True), dairyIdEmbed],
        view=dairyView,
    )


class Daily(commands.Cog):
    """定期投稿と、おこづかい・IDくじ。"""

    def __init__(self, bot):
        self.bot = bot

    @tasks.loop(time=time(hour=5, minute=0, tzinfo=ZoneInfo("Asia/Tokyo")))
    async def daily_bonus(self):
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        await post_daily(self.bot, now, cfg.DAIRY_CHANNEL_ID)
        save_last_daily_date(now)

    @commands.Cog.listener()
    async def on_ready(self):
        # 定期処理の開始
        if not self.daily_bonus.is_running():
            self.daily_bonus.start()

        # 時報の投稿済みチェック (5時以降の起動で)
        dairyChannel = self.bot.get_channel(cfg.DAIRY_CHANNEL_ID)
        if dairyChannel is not None:
            now = datetime.now(ZoneInfo("Asia/Tokyo"))
            lastDate = read_last_daily_date()
            if should_post_daily(lastDate, now):
                if lastDate is None and await self.__posted_today(dairyChannel, now):
                    # 状態ファイルを入れる前の投稿を確認できた場合は二重投稿しない
                    save_last_daily_date(now)
                    ub.output_log("本日の時報は投稿済みでした")
                else:
                    ub.output_warning("本日の時報が未投稿のようです.時報の投稿を試みます")
                    await post_daily(
                        self.bot,
                        now.replace(hour=5, minute=0, second=0, microsecond=0),
                        cfg.DAIRY_CHANNEL_ID,
                    )
                    save_last_daily_date(now)

            ub.output_log("botが起動しました")

    async def __posted_today(self, dairyChannel, now: datetime) -> bool:
        """日付入りの投稿が今日ぶんチャンネルにあるか確認する（状態ファイル導入前の互換）。"""
        async for message in dairyChannel.history(limit=10):
            if (
                message.author == self.bot.user
                and now.strftime("%Y/%m/%d") in message.content
            ):
                return True
        return False

    # おこづかいランキングを表示するコマンド
    @discord.app_commands.command(name="pocketmoney", description="おこづかいの残高照会をします")
    @discord.app_commands.guilds(*GUILDS)
    @discord.app_commands.describe()
    async def pocketmoney(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        money = ub.report(user_id, "おこづかい", 0, interaction.user.name)
        df = pd.read_csv(cfg.REPORT_PATH, dtype={"ユーザーID": str})
        user_id = str(user_id)

        user_wallet = df[["ユーザーID", "おこづかい"]]
        user_wallet_sorted = user_wallet.sort_values(
            by="おこづかい", ascending=False
        ).reset_index(drop=True)

        # ランキングを作成し順位を取得
        max_wallet = 0
        userRank = 0
        for i in range(1, len(user_wallet_sorted) + 1):
            if max_wallet == user_wallet_sorted["おこづかい"][i - 1]:
                rank = user_wallet_sorted.loc[i - 2, "rank"]
            else:
                max_wallet = user_wallet_sorted["おこづかい"][i - 1]
                rank = i
            user_wallet_sorted.loc[i - 1, "rank"] = rank
            if user_wallet_sorted.loc[i - 1, "ユーザーID"] == user_id:
                userRank = rank

            if userRank != 0 and i >= 5:
                break
        # ランキングのトップ5を取得
        top_n = 5
        top_users = user_wallet_sorted.head(top_n)

        ranking_list = top_users.values.tolist()

        pdwGuild = await self.bot.fetch_guild(cfg.PDW_SERVER_ID, with_counts=True)
        attachImage = ub.attachment_file("resource/image/command/mom_johto.png")
        embed = ub_embed.balance(
            userName=interaction.user.name,
            pocketMoney=money,
            numOfPeople=pdwGuild.approximate_member_count,
            userRank=userRank,
            rank_list=ranking_list,
            sendTime=datetime.now(ZoneInfo("Asia/Tokyo")),
            authorPath=attachImage[1],
        )

        await interaction.response.send_message(
            file=attachImage[0], embed=embed, ephemeral=True
        )

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """IDくじのボタンを処理する。"""
        data = interaction.data or {}
        custom_id = data.get("custom_id")
        if data.get("component_type") != 2 or not custom_id:
            return
        if not custom_id.startswith("lotoIdButton"):
            return

        ub.output_log(
            f'buttonが押されました\n {interaction.user.name}: {custom_id}'
        )
        ub.output_log("IDくじを実行します")
        # カスタムIDは,"lotoIdButton:00000:0000/00/00"という形式
        lotoId = custom_id.split(":")[1]
        birth = custom_id.split(":")[2]
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        today = now.date()
        if now.hour < 5:
            today = today - timedelta(days=1)

        if not birth == str(today):
            # 過去に投稿されたくじの場合
            await interaction.response.send_message(
                f"それは 今日のIDくじ じゃないロ{cfg.EXCLAMATION_ICON}", ephemeral=True
            )
        elif ub.report(interaction.user.id, "クジびきけん", 0, interaction.user.name) == 0:
            # すでにくじを引いている場合
            await interaction.response.send_message(
                "くじが ひけるのは 1日1回 まで なんだロ……", ephemeral=True
            )
        else:
            userId = str(interaction.user.id)[-6:].zfill(5)  # ID下6ケタを取得

            matchCount = 0
            for i in range(1, 6):
                if userId[-i] == lotoId[-i]:
                    matchCount += 1
                else:
                    break

            matchCount = str(matchCount)
            prize = cfg.PRIZE_DICT[matchCount]["prize"]
            value = cfg.PRIZE_DICT[matchCount]["value"]
            text = cfg.PRIZE_DICT[matchCount]["text"]
            place = cfg.PRIZE_DICT[matchCount]["place"]

            pocketMoney = ub.report(interaction.user.id, "おこづかい", value, interaction.user.name)

            dialogText = f"\n"

            try:
                # おこづかいランキングを確認し,1位になっていた場合ロールを付与する
                df = pd.read_csv(cfg.REPORT_PATH, dtype={"ユーザーID": str})
                user_wallet = df[["ユーザーID", "おこづかい"]]
                user_wallet_sorted = user_wallet.sort_values(
                    by="おこづかい", ascending=False
                ).reset_index(drop=True)

                if pocketMoney == user_wallet_sorted.loc[0, "おこづかい"]:
                    dialogText = f"ロロ{cfg.EXCLAMATION_ICON}{interaction.guild.name}で いちばんの おかねもち だロト{cfg.EXCLAMATION_ICON}\n"
                    # おかねもちロール付与の処理
                    menymoneyRole = interaction.user.guild.get_role(cfg.MENYMONEY_ROLE_ID)
                    if menymoneyRole not in interaction.user.roles:
                        ub.output_log(
                            f"おこづかい一位が変わりました: {interaction.user.name}"
                        )
                        await interaction.user.add_roles(menymoneyRole)
                        ub.output_log(
                            f"ロールを付与しました: {interaction.user.name}に{menymoneyRole.name}"
                        )

                    # 2位以下のおかねもちロールを剥奪する処理
                    for i in range(0, len(user_wallet_sorted)):
                        lowerUser = interaction.guild.get_member(
                            int(user_wallet_sorted.loc[i, "ユーザーID"])
                        )
                        # インタラクションユーザーには実施しない
                        if lowerUser and not interaction.user == lowerUser:
                            if pocketMoney > user_wallet_sorted.loc[i, "おこづかい"]:
                                if menymoneyRole in lowerUser.roles:
                                    await lowerUser.remove_roles(menymoneyRole)
                                    ub.output_log(
                                        f"ロールを剥奪しました: {lowerUser.name}から{menymoneyRole.name}"
                                    )
                                else:
                                    break

            except Exception as e:
                ub.output_error(f"おこづかいランキングの処理でエラーが発生しました\n{e}")

            attachImage = ub.attachment_file(f"resource/image/prize/{prize}.png")
            lotoEmbed = discord.Embed(
                title=text,
                color=0xFF99C2,
                description=f"{place}の 商品 **{prize}**をプレゼントだロ{cfg.BANGBANG_ICON}\n"
                f"{dialogText}"
                f"それじゃあ またの 挑戦を お待ちしてるロ~~{cfg.EXCLAMATION_ICON}",
            )
            lotoEmbed.set_thumbnail(url=attachImage[1])
            lotoEmbed.add_field(
                name=f"{interaction.user.name}は {prize}を 手に入れた!",
                value=f"売却価格: {value}えん\nおこづかい: {pocketMoney}えん",
                inline=False,
            )
            lotoEmbed.set_author(name=f"あなたのID: {userId}")
            lotoEmbed.set_footer(text="No.15 IDくじ")

            ub.report(interaction.user.id, "クジびきけん", -1, interaction.user.name)  # クジの回数を減らす
            await interaction.response.send_message(
                file=attachImage[0], embed=lotoEmbed, ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(Daily(bot))