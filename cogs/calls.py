# -*- coding: utf-8 -*-
# cogs/calls.py
"""通話通知（/calltitle /invite）とボイスチャンネルの入退室。"""
import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands
import pandas as pd

import bot_module.config as cfg
import bot_module.func as ub

GUILDS = [discord.Object(id=guild_id) for guild_id in cfg.GUILD_IDS]


class Calls(commands.Cog):
    """通話の開始・終了・タイトル・招待。"""

    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="calltitle", description="参加中の通話のタイトルを設定します")
    @discord.app_commands.guilds(*GUILDS)
    @discord.app_commands.describe(title="参加中の通話の内容や目的")
    async def calltitle(self, interaction: discord.Interaction, title: str):
        if interaction.user.voice is not None:
            if await CallPost(self.bot, interaction.user.voice.channel).title(title):
                await interaction.response.send_message(
                    f"タイトルを`{title}`に変更しました", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "通話通知が見つかりませんでした", ephemeral=True
                )
        else:
            await interaction.response.send_message(
                "あなたは通話チュウに見えません", ephemeral=True
            )

    @discord.app_commands.command(name="invite", description="このチャンネルにメンバーを招待します")
    @discord.app_commands.guilds(*GUILDS)
    @discord.app_commands.describe(member="招待したいメンバー", anonymity="こっそり招待")
    async def invite(
        self, interaction: discord.Interaction, member: discord.Member, anonymity: bool = False
    ):
        x = discord.Embed(
            title="招待失敗",
            color=0xFF0000,
            description=f"{member.name}に招待を送信できませんでした",
        )
        if not member.bot:
            try:
                attachImage = ub.attachment_file("resource/image/command/invite_mail.png")
                inviteEmbed = discord.Embed(
                    title="おさそいメール",
                    color=0xFE71E4,
                    description=f"**{interaction.channel}** に招待されています!\n`招待を受け取りたくない場合はこのbotをブロックしてください`",
                )
                inviteEmbed.set_author(
                    name=f"{interaction.user.name} からの招待" if not anonymity else ""
                )
                inviteEmbed.set_thumbnail(url=attachImage[1])
                inviteEmbed.set_footer(
                    text=datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y/%m/%d %H:%M:%S")
                )
                inviteLink = f"https://discord.com/channels/{interaction.guild.id}/{interaction.channel.id}"
                linkButton = discord.ui.Button(
                    label="参加する", style=discord.ButtonStyle.primary, url=inviteLink
                )
                linkView = discord.ui.View()
                linkView.add_item(linkButton)
                await member.send(file=attachImage[0], embed=inviteEmbed, view=linkView)

                x = discord.Embed(
                    title="招待成功",
                    color=0x51FF2E,
                    description=f"{member.name}に招待を送信しました",
                )

            except discord.errors.Forbidden:
                pass
        await interaction.response.send_message(embed=x, ephemeral=anonymity)

    # ボイスチャンネルへの参加・退出を検知
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        time = datetime.now(ZoneInfo("Asia/Tokyo"))

        if os.path.exists(cfg.CALLDATA_PATH):
            call_df = pd.read_csv(cfg.CALLDATA_PATH, dtype={"累計参加メンバー": str})
        else:
            call_df = pd.DataFrame(
                columns=[
                    "チャンネルID",
                    "メッセージID",
                    "通話開始",
                    "タイトル",
                    "名前読み上げ",
                    "累計参加メンバー",
                ]
            )
        call_df.set_index("チャンネルID", inplace=True)

        if after.channel:
            if member.bot:
                return
            # ボイスチャンネルにメンバーが入室
            callch = after.channel
            if after.channel.type == discord.ChannelType.voice:
                ub.output_log(f"ボイスチャンネル参加\n {callch.name}: {member.name}")
                if len(after.channel.members) == 1:  # 入室時ひとりなら
                    if before.channel and len(before.channel.members) == 1:
                        return
                    await asyncio.sleep(5)  # 5秒後に通話開始処理
                    if len(callch.members) > 0:
                        member = callch.members[0]
                        await CallPost(self.bot, callch).start(member, time)

                        if (
                            not member.voice or not member.voice.channel == callch
                        ):  # 参加したメンバーがいなくなっていたら
                            ub.output_log("参加したメンバーが退出しています")
                            return
                    else:
                        ub.output_log(
                            f"通話は開始されませんでした\n {callch.name}: {member.name}"
                        )
                        return
                else:
                    if not callch.id in call_df.index:
                        await asyncio.sleep(5)
                        call_df = pd.read_csv(
                            cfg.CALLDATA_PATH, dtype={"累計参加メンバー": str}
                        ).set_index(
                            "チャンネルID"
                        )  # 更新する

                    if callch.id in call_df.index and str(member.id) not in call_df.loc[
                        callch.id, "累計参加メンバー"
                    ].split(" "):
                        call_df.loc[callch.id, "累計参加メンバー"] += f" {member.id}"
                        call_df.to_csv(cfg.CALLDATA_PATH)

        if before.channel:
            # ボイスチャンネルからメンバーが退室
            if before.channel.type == discord.ChannelType.voice:
                ub.output_log(
                    f"ボイスチャンネル退出\n {before.channel.name}: {member.name}"
                )

                if len(before.channel.members) == 0:  # ボイスチャンネルに人がいなくなったら
                    await CallPost(self.bot, before.channel).stop(time)


class CallPost:  # await CallPost(bot, discord.channel).start(member,time) /.stop(time) /.title(title)
    def __init__(self, bot, channel, sendChannelId: int = None):
        self.bot = bot
        self.channel = channel
        if sendChannelId is None:
            if self.channel.permissions_for(
                channel.guild.default_role
            ).view_channel:  # プライベートなら送信先を変更:
                sendChannelId = cfg.CALLSTATUS_CHANNEL_ID
            else:
                sendChannelId = cfg.DEBUG_CHANNEL_ID
        self.sendChannel = bot.get_channel(sendChannelId)
        self.message = None

        if self.channel.type == discord.ChannelType.stage_voice:
            self.chType = "放送"
        else:
            self.chType = "通話"

        if os.path.exists(cfg.CALLDATA_PATH):
            self.call_df = pd.read_csv(
                cfg.CALLDATA_PATH, dtype={"累計参加メンバー": str}
            ).set_index("チャンネルID",drop=False)
        else:
            self.call_df = pd.DataFrame(
                columns=[
                    "チャンネルID",
                    "メッセージID",
                    "通話開始",
                    "タイトル",
                    "名前読み上げ",
                    "累計参加メンバー",
                ]
            ).set_index("チャンネルID",drop=False)

    async def start(
        self, member, time: datetime = datetime.now(ZoneInfo("Asia/Tokyo"))
    ):
        defaultTitle = "設定無し"
        if self.chType == "放送":
            embedColor = 0xA7FF8F
        else:
            embedColor = 0xFF8E8E

        attachedImage = ub.attachment_file("resource/image/command/start_call.gif")
        startEmbed = discord.Embed(title=f"{self.chType}開始", color=embedColor)
        startEmbed.set_author(
            name=f"{member.name} さん", icon_url=member.display_avatar.url
        )
        startEmbed.set_thumbnail(url=attachedImage[1])
        startEmbed.add_field(name="タイトル", value=f"`{defaultTitle}`", inline=False)
        startEmbed.add_field(
            name="チャンネル", value=self.channel.mention, inline=False
        )
        startEmbed.add_field(
            name=f"{self.chType}開始",
            value=f'```{time.strftime("%Y/%m/%d")}\n{time.strftime("%H:%M:%S")}```',
            inline=True,
        )

        startMessage = await self.sendChannel.send(
            file=attachedImage[0], embed=startEmbed
        )

        #FutureWarning: In a future version, object-dtype columns with all-bool values will not be included in reductions with bool_only=True. Explicitly cast to bool dtype instead. 
        newBusyData = pd.DataFrame(
            data=[[self.channel.id,startMessage.id,time.strftime("%Y/%m/%d %H:%M:%S"),defaultTitle,False,member.id]],
            index=[self.channel.id],
            columns=["チャンネルID","メッセージID","通話開始","タイトル","名前読み上げ","累計参加メンバー"]
        ).astype({"名前読み上げ":bool})
        if self.channel.id not in self.call_df.index:
            # appendは使用しない AttributeError: 'DataFrame' object has no attribute 'append'
            self.call_df = pd.concat([self.call_df, newBusyData])

        else:
            self.call_df.loc[self.channel.id] = newBusyData
            #self.call_df[self.call_df[self.channel.id]] = newBusyData
            ub.output_log("通話キャッシュを更新しました")

        self.call_df.to_csv(cfg.CALLDATA_PATH,index=False)

        await self.channel.send(
            embed=discord.Embed(
                title="通話開始",
                description="`/calltitle` 通話目的を変更できます\n`/invite` メンバーを招待できます",
                color=embedColor,
            ).set_footer(text=time.strftime("%Y/%m/%d %H:%M:%S")),
        )
        ub.output_log(
            f"{self.chType}が開始されました\n {self.channel.name}: {member.name}"
        )

    async def title(self, newTitle: str):
        if not await self.__load():
            return False

        self.message.embeds[0].set_field_at(0, name="タイトル", value=f"`{newTitle}`")

        oldTitle = self.call_df.loc[self.channel.id, "タイトル"]
        self.call_df.loc[self.channel.id, "タイトル"] = newTitle
        self.call_df.to_csv(cfg.CALLDATA_PATH)

        await self.message.edit(
            embed=self.message.embeds[0], attachments=self.message.attachments
        )
        ub.output_log(
            f"通話タイトルを更新しました\n{self.channel.name}: [{oldTitle} > {newTitle}]"
        )
        return True

    async def stop(self, time: datetime = datetime.now(ZoneInfo("Asia/Tokyo"))):
        if not await self.__load():
            return False
        if self.chType == "放送":
            embedColor = 0x8FFFF8
        else:
            embedColor = 0x8E8EFF

        diff = (
            time.replace(tzinfo=None)
            - pd.to_datetime(
                self.call_df.loc[self.channel.id, "通話開始"],
                format="%Y/%m/%d %H:%M:%S",
            )
        ).total_seconds()
        hours = int(diff // 3600)
        minutes = int((diff % 3600) // 60)
        seconds = int(diff % 60)
        attachImage = ub.attachment_file("resource/image/command/stop_call.gif")

        stopEmbed = self.message.embeds[0]
        stopEmbed.title = (
            f'{self.chType}終了・{f"{hours}時間 " if hours>0 else " "}{minutes}分'
        )
        stopEmbed.color = embedColor
        stopEmbed.set_thumbnail(url=attachImage[1])
        stopEmbed.set_footer(
            text=f'Total Visitors: {len(self.call_df.loc[self.channel.id,"累計参加メンバー"].split(" "))}'
        )
        stopEmbed.add_field(
            name=f"{self.chType}終了",
            value=f'```{time.strftime("%Y/%m/%d")}\n{time.strftime("%H:%M:%S")}```',
            inline=True,
        )

        await self.message.edit(embed=stopEmbed, attachments=[attachImage[0]])

        self.call_df.drop(self.channel.id).to_csv(cfg.CALLDATA_PATH, index=True)

        visitor_ids = self.call_df.loc[self.channel.id, "累計参加メンバー"].split(" ")
        visitor_names = []
        for visitor_id in visitor_ids:
            visitor = await self.bot.fetch_user(visitor_id)
            visitor_names.append(visitor.name)
        visitors = " ".join(visitor_names)

        if os.path.exists(cfg.CALLLOG_PATH):
            log_df = pd.read_csv(cfg.CALLLOG_PATH)
        else:
            log_df = pd.DataFrame(
                columns=[
                    "通話開始",
                    "通話終了",
                    "通話時間",
                    "タイトル",
                    "チャンネル",
                    "参加メンバー",
                ]
            )

        newLog = pd.DataFrame(
            {
                "通話開始": self.call_df.loc[self.channel.id, "通話開始"],
                "通話終了": time.strftime("%Y/%m/%d %H:%M:%S"),
                "通話時間": f"{hours:02}:{minutes:02}:{seconds:02}",
                "タイトル": self.call_df.loc[self.channel.id, "タイトル"],
                "チャンネル": self.channel.name,
                "参加メンバー": visitors,
            },
            index=[0],
        )
        # log_df = pd.concat([log_df.iloc[:1], newLog, log_df.iloc[1:]], ignore_index=True)
        log_df = pd.concat([newLog, log_df], ignore_index=True)
        log_df.to_csv(cfg.CALLLOG_PATH, mode="w", header=True, index=False)

        embed = discord.Embed(title=f"{self.chType}終了", color=embedColor)
        embed.set_footer(text=time.strftime("%Y/%m/%d %H:%M:%S"))

        await self.channel.send(embed=embed)
        ub.output_log(
            f"{self.chType}が終了しました\n {self.channel.name}: {visitor_names[-1]}"
        )
        return True

    async def __load(self):
        #"チャンネルID"列に指定のチャンネルIDがあるか確認 (indexではない)
        if self.channel.id in self.call_df.index:
            try:
                self.message = await self.sendChannel.fetch_message(
                    #指定の"チャンネルID"の"メッセージID"を取得
                    self.call_df.loc[self.channel.id, "メッセージID"]
                )
            except discord.NotFound:
                ub.output_error("指定のメッセージが見つかりませんでした")
                return False
        else:
            ub.output_error("指定チャンネルの通話記録がありません")
            return False
        return True


async def setup(bot):
    await bot.add_cog(Calls(bot))