# -*- coding: utf-8 -*-
# cogs/daily.py
"""日替わり投稿・ログ投稿・おこづかい・IDくじ。"""
import asyncio
import random
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

import bot_module.config as cfg
from bot_module.command_scope import scoped
import bot_module.embed as ub_embed
import bot_module.func as ub
import bot_module.guild_settings as guild_settings
import bot_module.save as save
from bot_module.save import SaveError


# 最後に日替わり投稿を出した日付（ギルドごと）。DBが無い手元（開発用）はファイル。
LAST_DAILY_KEY = 'LAST_DAILY_DATE'


def _last_daily_path(guild_id) -> str:
    return f"save/last_daily_{guild_id}.txt"


def read_last_daily_date(guild_id) -> str | None:
    """最後に日替わり投稿を出した日付（%Y/%m/%d）を返す。無ければNone。"""
    value = save.get_guild_setting(guild_id, LAST_DAILY_KEY)
    if value:
        text = str(value)
        return f"{text[0:4]}/{text[4:6]}/{text[6:8]}"
    if save.get_store() is None:
        try:
            with open(_last_daily_path(guild_id), encoding="utf-8") as file:
                return file.read().strip() or None
        except FileNotFoundError:
            return None
    return None


def save_last_daily_date(guild_id, day: datetime) -> None:
    if save.set_guild_setting(
            guild_id, LAST_DAILY_KEY, int(day.strftime('%Y%m%d'))):
        return
    # DB未設定の手元はファイルに残す
    with open(_last_daily_path(guild_id), "w", encoding="utf-8") as file:
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

    dairyChannel = bot.get_channel(channelid)
    ub.reset_value("クジびきけん", 1)
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
        # 5時のループと起動時のキャッチアップが重なっても二重投稿しない
        self._daily_lock = asyncio.Lock()

    @tasks.loop(time=time(hour=5, minute=0, tzinfo=ZoneInfo("Asia/Tokyo")))
    async def daily_bonus(self):
        await self._post_daily_all_guilds()

    async def _post_daily_guild(self, guild, now: datetime, catch_up: bool):
        """1ギルド分の日替わり投稿。設定が無いギルドは何もしない。"""
        channel_id = guild_settings.setting(guild.id, 'DAIRY_CHANNEL_ID')
        channel = self.bot.get_channel(channel_id) if channel_id else None
        if channel is None:
            return
        last_date = read_last_daily_date(guild.id)
        if not should_post_daily(last_date, now):
            return
        if catch_up and await self.__posted_today(channel, now):
            # 投稿済みなら状態だけ入れる（このBotの投稿でも、もう1つのBotの
            # 投稿でも、今日ぶんが出ていれば二重投稿しない）
            save_last_daily_date(guild.id, now)
            ub.output_log(f"本日の時報は投稿済みでした: {guild.name}")
            return
        if catch_up:
            ub.output_warning(
                f"本日の時報が未投稿のようです.時報の投稿を試みます: {guild.name}")
        await post_daily(
            self.bot,
            now.replace(hour=5, minute=0, second=0, microsecond=0),
            channel_id,
        )
        save_last_daily_date(guild.id, now)

    async def _post_daily_all_guilds(self, catch_up: bool = False):
        async with self._daily_lock:
            now = datetime.now(ZoneInfo("Asia/Tokyo"))
            for guild in list(self.bot.guilds):
                try:
                    await self._post_daily_guild(guild, now, catch_up)
                except Exception as e:
                    # 1ギルドの失敗でループ全体を止めない
                    ub.output_error(
                        f"日替わり投稿に失敗しました: {guild.name}（{guild.id}）\n{e}")

    @commands.Cog.listener()
    async def on_ready(self):
        # 定期処理の開始
        if not self.daily_bonus.is_running():
            self.daily_bonus.start()

        # 時報の投稿済みチェック (5時以降の起動で)
        await self._post_daily_all_guilds(catch_up=True)
        ub.output_log("botが起動しました")

    async def __posted_today(self, dairyChannel, now: datetime) -> bool:
        """今日ぶんの日付入り投稿がチャンネルにあるか確認する。

        テスト配備ではもう1つのBotが投稿していることもあるので、投稿者は問わない
        （Botの投稿だけを見る）。
        """
        async for message in dairyChannel.history(limit=20):
            author = getattr(message.author, "bot", False)
            if author and now.strftime("%Y/%m/%d") in (message.content or ""):
                return True
        return False

    # おこづかいランキングを表示するコマンド
    @discord.app_commands.command(name="pocketmoney", description="おこづかいの残高照会をします")
    @scoped
    @discord.app_commands.describe()
    async def pocketmoney(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        try:
            money = ub.report(user_id, "おこづかい", 0, interaction.user.name)
        except SaveError:
            await ub.save_error(interaction)
            return
        ranking_list = ub.ranking("おこづかい", 5)
        userRank = ub.rank(user_id, "おこづかい")

        try:
            pdwGuild = await self.bot.fetch_guild(
                cfg.PDW_SERVER_ID, with_counts=True)
        except discord.NotFound:
            # 本番ギルドに居ないとき（テストサーバーなど）はいまのサーバーを使う
            pdwGuild = await self.bot.fetch_guild(
                interaction.guild_id, with_counts=True)
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
        # ロールの付与・剥奪を待つあいだに3秒を超えないよう、先に応答を保留する
        await interaction.response.defer(ephemeral=True, thinking=True)
        # カスタムIDは,"lotoIdButton:00000:0000/00/00"という形式
        lotoId = custom_id.split(":")[1]
        birth = custom_id.split(":")[2]
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        today = now.date()
        if now.hour < 5:
            today = today - timedelta(days=1)

        try:
            if not birth == str(today):
                # 過去に投稿されたくじの場合
                await interaction.followup.send(
                    f"それは 今日のIDくじ じゃないロ{cfg.EXCLAMATION_ICON}", ephemeral=True
                )
            elif ub.report(
                interaction.user.id, "クジびきけん", 0, interaction.user.name
            ) == 0:
                # すでにくじを引いている場合
                await interaction.followup.send(
                    "くじが ひけるのは 1日1回 まで なんだロ……", ephemeral=True
                )
            else:
                # 引換券は、おこづかいを加算するより先に消費する（連打で2回引かれないように）
                ub.report(
                    interaction.user.id, "クジびきけん", -1,
                    interaction.user.name
                )
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

                pocketMoney = ub.report(
                    interaction.user.id, "おこづかい", value,
                    interaction.user.name)

                dialogText = f"\n"

                try:
                    # 1位になっていたら「おかねもち」ロールを付与し、2位以下から剥奪する
                    if pocketMoney == ub.top_value("おこづかい"):
                        dialogText = f"ロロ{cfg.EXCLAMATION_ICON}{interaction.guild.name}で いちばんの おかねもち だロト{cfg.EXCLAMATION_ICON}\n"
                        menymoneyRole = interaction.user.guild.get_role(
                            guild_settings.setting(
                                interaction.guild.id, 'MENYMONEY_ROLE_ID'))
                        if menymoneyRole is None:
                            ub.output_log("おかねもちロールが未設定です")
                        else:
                            # おかねもちロール付与の処理
                            if menymoneyRole not in interaction.user.roles:
                                ub.output_log(
                                    f"おこづかい一位が変わりました: {interaction.user.name}"
                                )
                                await interaction.user.add_roles(menymoneyRole)
                                ub.output_log(
                                    f"ロールを付与しました: {interaction.user.name}に{menymoneyRole.name}"
                                )

                            # 2位以下のおかねもちロールを剥奪する処理。
                            # 1位以外は持っていないはずなので、持っている人全員から外す
                            # （間に持っていない人がいても止めない）。
                            for user_id, _money, _rank in ub.ranking(
                                    "おこづかい", 100):
                                lowerUser = interaction.guild.get_member(int(user_id))
                                # インタラクションユーザーには実施しない
                                if lowerUser is None or lowerUser == interaction.user:
                                    continue
                                if menymoneyRole in lowerUser.roles:
                                    await lowerUser.remove_roles(menymoneyRole)
                                    ub.output_log(
                                        f"ロールを剥奪しました: {lowerUser.name}から{menymoneyRole.name}"
                                    )

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

                await interaction.followup.send(
                    file=attachImage[0], embed=lotoEmbed, ephemeral=True
                )
        except SaveError:
            await ub.save_error(
                interaction, write=True,
                log="IDくじのセーブデータの保存に失敗しました")


async def setup(bot):
    await bot.add_cog(Daily(bot))
