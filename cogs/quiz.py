# -*- coding: utf-8 -*-
# cogs/quiz.py
"""ポケモンクイズ（/q /quizrate /bmode）と回答の受付。"""
import copy
import os
import random
import re

import discord
from discord.ext import commands
import jaconv
import pandas as pd

import bot_module.config as cfg
import bot_module.func as ub
from bot_module.pokedex import get_pokedex

GUILDS = [discord.Object(id=guild_id) for guild_id in cfg.GUILD_IDS]

# 実行時の状態（configから移した）
BQ_FILTER_DICT = copy.deepcopy(cfg.DEFAULT_FILTER_DICT)  # 現在の出題条件
BAKUSOKU_MODE = True  # 連続出題モード
QUIZ_PROCESSING_FLAG = 0  # 回答開示処理中フラグ


class Quiz(commands.Cog):
    """クイズの出題・戦績・連続出題モード。"""

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        # 起動時と再接続時に図鑑カタログを用意する（pkdbが無ければCSV）
        get_pokedex()

    @discord.app_commands.command(name="q", description="現在の出題設定に基づいてクイズを出題します")
    @discord.app_commands.guilds(*GUILDS)
    @discord.app_commands.describe(
        quizname="クイズの種別 未記入で種族値クイズが指定されます"
    )
    @discord.app_commands.choices(
        quizname=[
            discord.app_commands.Choice(name=val, value=val)
            for val in list(cfg.QUIZNAME_DICT.keys())
        ]
    )
    async def q(self, interaction: discord.Interaction, quizname: str = "種族値クイズ"):
        seiseiEmbed = discord.Embed(
            title="**妖精さん おしごとチュウ**",
            color=0xFFFFFF,  # デフォルトカラー
            description=f"{quizname}を生成しています",
        )
        await interaction.response.send_message(embed=seiseiEmbed, delete_after=1)
        await quiz(self.bot, cfg.QUIZNAME_DICT[quizname]).post(interaction.channel)

    @discord.app_commands.command(name="quizrate", description="クイズの戦績を表示します")
    @discord.app_commands.guilds(*GUILDS)
    @discord.app_commands.describe(
        user="表示したいメンバー名",
        quizname="クイズの種別 未記入で種族値クイズが指定されます",
    )
    @discord.app_commands.choices(
        quizname=[
            discord.app_commands.Choice(name=val, value=val)
            for val in list(cfg.QUIZNAME_DICT.keys())
        ]
    )
    async def quizrate(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None,
        quizname: str = "種族値クイズ",
    ):
        if user is not None:
            showId = user.id
            showName = user.name
        else:
            showId = interaction.user.id
            showName = interaction.user.name

        ub.output_log("戦績表示を実行します")
        w = ub.report(showId, f"{cfg.QUIZNAME_DICT[quizname]}正答", 0, showName)
        l = ub.report(showId, f"{cfg.QUIZNAME_DICT[quizname]}誤答", 0, showName)
        await interaction.response.send_message(
            f"""{showName}さんの{quizname}戦績
正答: {w}回 誤答: {l}回
正答率: {int(w/(w+l)*100) if not w+l==0 else 0}%"""
        )

    @discord.app_commands.command(name="bmode", description="クイズの連続出題モードを切り替えます")
    @discord.app_commands.guilds(*GUILDS)
    @discord.app_commands.describe(mode="連続出題モードのオンオフ 未記入でトグル切り替え")
    @discord.app_commands.choices(
        mode=[
            discord.app_commands.Choice(name="ON", value="ON"),
            discord.app_commands.Choice(name="OFF", value="OFF"),
        ]
    )
    async def bmode(self, interaction: discord.Interaction, mode: str = None):
        global BAKUSOKU_MODE
        if mode == "ON":
            BAKUSOKU_MODE = True
        elif mode == "OFF":
            BAKUSOKU_MODE = False
        else:
            BAKUSOKU_MODE = not BAKUSOKU_MODE
        ub.output_log("爆速モードが" + str(BAKUSOKU_MODE) + "になりました")
        await interaction.response.send_message(
            f"連続出題が{'ON' if BAKUSOKU_MODE else 'OFF'}になりました"
        )

    # メッセージの送受信を観測したときの処理
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:  # メッセージ送信者がBotだった場合は無視する
            return

        if message.content.startswith("/bqdata"):
            global BQ_FILTER_DICT
            bqFilterWords = message.content.split()[1:]

            if bqFilterWords:
                removeWords = [
                    "タイプ",
                    "特性",
                    "出身地",
                    "初登場世代",
                    "進化段階",
                    "HP",
                    "こうげき",
                    "ぼうぎょ",
                    "とくこう",
                    "とくぼう",
                    "すばやさ",
                    "合計",
                ]

                if "リセット" in bqFilterWords:
                    # 既定の条件（config.json）へ戻す。既定値そのものを書き換えないよう複製する
                    BQ_FILTER_DICT = copy.deepcopy(cfg.DEFAULT_FILTER_DICT)
                    bqFilterWords.remove("リセット")

                if "種族値" in bqFilterWords:
                    for key in [
                        "HP",
                        "こうげき",
                        "ぼうぎょ",
                        "とくこう",
                        "とくぼう",
                        "すばやさ",
                        "合計",
                    ]:
                        BQ_FILTER_DICT.pop(key, None)
                    bqFilterWords.remove("種族値")

                for word in bqFilterWords:
                    if word in removeWords:  # 絞り込みをリセット
                        # 設定されていない項目を指定されても落ちないようにする
                        BQ_FILTER_DICT.pop(word, None)

                bqFilterWords = [x for x in bqFilterWords if x not in removeWords]

                # インデックスの要素が更新されていない項目はそのまま
                BQ_FILTER_DICT.update(ub.make_filter_dict(bqFilterWords))
                response = "種族値クイズの出題条件が変更されました"
                ub.output_log("出題条件が更新されました")

            else:
                response = "現在の種族値クイズの出題条件は以下の通りです"

            bqFilteredEmbed = discord.Embed(
                title="種族値クイズの出題条件",
                color=0x9013FE,
                description=f"該当ポケモン数: {len(get_pokedex().filter(BQ_FILTER_DICT))}匹",
            )

            for i, key in enumerate(BQ_FILTER_DICT.keys()):
                values = "\n".join(BQ_FILTER_DICT[key])
                bqFilteredEmbed.add_field(name=key, value=values, inline=False)

            ub.output_log("出題条件を表示します")
            await message.channel.send(response, embed=bqFilteredEmbed)

        # bot自身へのリプライ(reference)に反応
        elif message.reference is not None:
            # リプライ先メッセージのキャッシュを取得
            message.reference.resolved = await message.channel.fetch_message(
                message.reference.message_id
            )

            # bot自身へのリプライに反応
            if message.reference.resolved.author == self.bot.user:
                embeds = message.reference.resolved.embeds
                embedFooterText = embeds[0].footer.text if embeds else None
                # リプライ先にembedが含まれるかつ未回答のクイズの投稿か
                if (
                    embedFooterText
                    and "No.26 ポケモンクイズ" in embedFooterText
                    and not "(done)" in embedFooterText
                ):
                    await quiz(self.bot, embedFooterText.split()[3]).try_response(message)

                else:
                    ub.output_log("botへのリプライは無視されました")

        #チャンネルのidがQUIZ_CHANNEL_IDの場合
        elif message.channel.id == cfg.QUIZ_CHANNEL_ID:
            #メッセージの内容がポケモン名であるか判定
            if ub.fetch_pokemon(message.content) is not None:
                #一番新しいクイズの投稿を探し,未回答の場合は
                foundQuiz = False
                async for quizMessage in message.channel.history(limit=10):
                    if quizMessage.embeds:
                        embedFooterText = quizMessage.embeds[0].footer.text or ""
                        if (
                            "No.26 ポケモンクイズ - bq" in embedFooterText
                            and not "(done)" in embedFooterText
                        ):
                            #メッセージをリプライに偽装する quizクラスの内容を修正すべき
                            message.reference = discord.MessageReference(
                                message_id=quizMessage.id,
                                channel_id=quizMessage.channel.id,
                                guild_id=quizMessage.guild.id,
                                #resolved=message
                            )
                            message.reference.resolved = quizMessage
                            await quiz(self.bot, embedFooterText.split()[3]).try_response(message)
                            foundQuiz = True
                            break
                if not foundQuiz:
                    ub.output_warning("ポケモン名が投稿されましたがクイズ投稿が見つかりませんでした")


class quiz:
    def __init__(self, bot, quizName):
        self.bot = bot
        self.quizName = quizName

    async def post(self, sendChannel):
        ub.output_log(f"{self.quizName}: クイズを出題します")

        quizContent = None
        quizFile = None
        quizEmbed = discord.Embed(title="", color=0x9013FE, description="")
        quizEmbed.set_footer(text=f"No.26 ポケモンクイズ - {self.quizName}")
        quizView = None
        # 必要な要素をクイズごとに編集

        if self.quizName == "bq":
            qDatas = get_pokedex().random(BQ_FILTER_DICT)
            if qDatas is not None:
                quizEmbed.title = "種族値クイズ"
                quizEmbed.description = "こたえ: ???"  # 正答後: こたえ: [ポケモン名](複数いる場合),[ポケモン名]
                quizFile = discord.File(
                    ub.generate_graph(list(qDatas.stats)), filename="image.png"
                )
                quizEmbed.set_image(
                    url="attachment://image.png"
                )  # 種族値クイズ図形の添付
                quizEmbed.set_thumbnail(
                    url=self.__imageLink()
                )  # 正解までDecamark(?)を表示
                quizContent = ub.bss_to_text(qDatas)

            else:
                # 条件に合うポケモンがいない場合は、空のクイズを投稿せずに終わる
                await sendChannel.send("現在の出題条件に合うポケモンがいません")
                return

        elif self.quizName == "acq":
            qDatas = get_pokedex().random({"進化段階": ["最終進化", "進化しない"]})
            if qDatas is None:
                await sendChannel.send("現在の出題条件に合うポケモンがいません")
                return
            quizEmbed.title = "ACクイズ"
            quizEmbed.description = (
                f"{qDatas.name} はこうげきととくこうどちらが高い?"
            )
            quizEmbed.set_thumbnail(url=self.__imageLink(qDatas.name))

            quizView = discord.ui.View()
            quizView.add_item(
                discord.ui.Button(
                    label="こうげき",
                    style=discord.ButtonStyle.primary,
                    custom_id="acq_こうげき",
                )
            )
            quizView.add_item(
                discord.ui.Button(
                    label="とくこう",
                    style=discord.ButtonStyle.primary,
                    custom_id="acq_とくこう",
                )
            )
            quizView.add_item(
                discord.ui.Button(
                    label="同値",
                    style=discord.ButtonStyle.secondary,
                    custom_id="acq_同値",
                )
            )

        elif self.quizName == "etojq":
            qDatas = self.__random_with({"進化段階": ["最終進化", "進化しない"]}, "eng")
            if qDatas is None:
                await sendChannel.send("現在の出題条件に合うポケモンがいません")
                return
            quizEmbed.title = "英和翻訳クイズ"
            quizEmbed.description = f"{qDatas.eng} -> [?]"

        elif self.quizName == "jtoeq":
            qDatas = self.__random_with({"進化段階": ["最終進化", "進化しない"]}, "eng")
            if qDatas is None:
                await sendChannel.send("現在の出題条件に合うポケモンがいません")
                return
            quizEmbed.title = "和英翻訳クイズ"
            quizEmbed.description = f"{qDatas.name} -> [?]"
            quizEmbed.set_thumbnail(url=self.__imageLink(qDatas.name))

        elif self.quizName == "ctojq":
            qDatas = self.__random_with({"進化段階": ["最終進化", "進化しない"]}, "cht")
            if qDatas is None:
                await sendChannel.send("現在の出題条件に合うポケモンがいません")
                return
            quizEmbed.title = "中日翻訳クイズ"
            quizEmbed.description = f"{qDatas.cht} -> [?]"

        else:
            ub.output_warning(f"不明なクイズ識別子(post): {self.quizName}")
            # ここでエラーを送信
            return

        self.qm = await sendChannel.send(
            content=quizContent, file=quizFile, embed=quizEmbed, view=quizView
        )

    async def try_response(self, response):

        # インスタンスがメッセージ/インタラクションかどうかで代入データを変える
        if isinstance(response, discord.Message):
            self.rm = response
            self.qm = response.reference.resolved
            self.ansText = ub.format_text(response.content)
            self.opener = self.rm.author
        elif isinstance(response, discord.Interaction):
            self.rm = response
            self.qm = response.message
            self.ansText = self.rm.data["custom_id"].split("_")[1]
            self.opener = self.rm.user
            # customIDが"acq_こうげき/とくこう/同値"のようなかたちを想定

        self.quizEmbed = self.qm.embeds[0]

        gives = ["ギブ", "ギブアップ", "降参", "敗北"]
        hints = []

        # クイズごとにヒント項目を作成する
        if self.quizName in ["bq", "ctojq"]:
            hints = [
                "ヒント",
                "タイプ",
                "特性",
                "トクセイ",
                "地方",
                "チホウ",
                "分類",
                "ブンルイ",
                "作品",
                "サクヒン",
            ]
        elif self.quizName == "etojq":
            hints = [
                "ヒント",
                "タイプ",
                "特性",
                "トクセイ",
                "地方",
                "チホウ",
                "分類",
                "ブンルイ",
                "作品",
                "サクヒン",
                "語源",
                "ゴゲン",
            ]
        elif self.quizName == "jtoeq":
            hints = ["文字数", "モジスウ", "頭文字", "カシラモジ", "イニシャル"]

        # ここでクイズの問題文を取得する
        if self.quizName == "bq":
            self.examText = self.qm.content.split(" ")[0]
        elif self.quizName == "acq":
            self.examText = self.quizEmbed.description.split(" ")[0]
        elif self.quizName in ["etojq", "jtoeq", "ctojq"]:
            self.examText = re.findall(r"^(.+)\s->", self.quizEmbed.description)[0]

        # ここでクイズの回答を取得する
        self.ansList, self.ansZero = self.__answers()

        if self.ansText in gives:
            await self.__giveup()
        elif self.ansText in hints:
            await self.__hint()
        else:
            await self.__judge()

    async def __giveup(self):
        ub.output_log(f"{self.quizName}: ギブアップを実行")
        if isinstance(self.rm, discord.Message):
            await self.rm.add_reaction("😅")
            await self.rm.reply(f"答えは{self.ansList[0]}でした")
        await self.__disclose(False)

    async def __judge(self):
        ub.output_log(f"{self.quizName}: 正誤判定を実行")

        fixAns = self.ansText
        repPokeData = None
        if self.quizName in ["bq", "etojq", "ctojq"]:
            if found := ub.fetch_pokemon(self.ansText):
                repPokeData = found[0]
                fixAns = repPokeData.name
        elif self.quizName == "jtoeq":
            fixAns = jaconv.z2h(
                jaconv.kata2alphabet(fixAns), kana=False, ascii=False, digit=True
            ).lower()
            self.ansList[0] = self.ansList[0].lower()

        if fixAns in self.ansList:
            judge = "正答"
            isMessage = isinstance(self.rm, discord.Message)
            if isMessage:
                await self.rm.add_reaction("⭕")
            result = await self.__disclose(True, fixAns)
            # リアクションは結果に基づいて付ける
            if isMessage and result == 1:
                await self.rm.remove_reaction("⭕", self.bot.user)
        else:
            judge = "誤答"
            if isinstance(self.rm, discord.Message):
                reaction = "❌"
            if isinstance(
                self.rm, discord.Interaction
            ):  # ボタンで回答しているときはギブアップになる
                await self.__disclose(False)

        if (
            self.quizName in ["bq", "etojq", "ctojq"] and repPokeData is None
        ):  # 例外処理
            judge = None
            if isinstance(self.rm, discord.Message):
                reaction = "❓"
                await self.rm.reply(f"{self.ansText} は図鑑に登録されていません")
        elif (
            judge == "誤答"
            and self.quizName == "jtoeq"
            and len(
                (
                    pokes := [
                        p
                        for p in get_pokedex().records
                        if p.eng and p.eng.lower() == fixAns
                    ]
                )
            )
            > 0
        ):
            if isinstance(self.rm, discord.Message):
                await self.rm.reply(f"{fixAns} は {pokes[0].name} の英名です")

        if judge != "正答" and isinstance(self.rm, discord.Message):
            await self.rm.add_reaction(reaction)

        if judge is not None:
            ub.report(
                self.opener.id, f"{self.quizName}{judge}", 1, self.opener.name
            )  # 回答記録のレポート

        self.__log(judge, self.ansList[0])

    async def __hint(self):
        ub.output_log(f"{self.quizName}: ヒント表示を実行")

        pokemon = self.ansZero
        hintIndex = None

        if self.quizName in ["bq", "etojq", "ctojq"]:
            if (
                self.ansText == "ヒント"
            ):  # まだ出ていないヒントからランダムにヒントを出す
                hintIndexs = [
                    "タイプ1",
                    "タイプ2",
                    "特性1",
                    "特性2",
                    "隠れ特性",
                    "出身地",
                    "分類",
                    "初登場作品",
                ]  # ヒントになるインデックスの一覧
                alreadyHints = [
                    field.name for field in self.quizEmbed.fields
                ]  # 既出のヒントの一覧
                stillHints = [
                    x
                    for x in hintIndexs
                    if x not in alreadyHints
                    and pokemon.hint_value(x) is not None
                ]  # 未出のヒントの一覧（値が無いものは出さない）
                if stillHints:
                    hintIndex = random.choice(stillHints)
                else:
                    shownHints = [
                        x
                        for x in alreadyHints
                        if pokemon.hint_value(x) is not None
                    ]
                    if not shownHints:
                        await self.rm.reply("これ以上 出せるヒントが ないロ")
                        return
                    hintIndex = random.choice(shownHints)

            elif self.ansText in ["タイプ"]:
                if pokemon.type_1 and not any(
                    field.name == "タイプ1" for field in self.quizEmbed.fields
                ):
                    hintIndex = "タイプ1"
                elif pokemon.type_2 and not any(
                    field.name == "タイプ2" for field in self.quizEmbed.fields
                ):
                    hintIndex = "タイプ2"
                else:
                    await self.rm.reply(
                        f"タイプは{pokemon.type_1 or 'なし'}/{pokemon.type_2 or 'なし'}です"
                    )
                    return

            elif self.ansText in ["特性", "トクセイ"]:
                if pokemon.ability_1 and not any(
                    field.name == "特性1" for field in self.quizEmbed.fields
                ):
                    hintIndex = "特性1"
                elif pokemon.ability_2 and not any(
                    field.name == "特性2" for field in self.quizEmbed.fields
                ):
                    hintIndex = "特性2"
                elif pokemon.ability_h and not any(
                    field.name == "隠れ特性" for field in self.quizEmbed.fields
                ):
                    hintIndex = "隠れ特性"
                else:
                    await self.rm.reply(
                        f"とくせいは{pokemon.ability_1 or 'なし'}/{pokemon.ability_2 or 'なし'}/{pokemon.ability_h or 'なし'}です"
                    )
                    return

            elif self.ansText in ["地方", "チホウ"]:
                hintIndex = "出身地"
            elif self.ansText in ["分類", "ブンルイ"]:
                hintIndex = "分類"
            elif self.ansText in ["作品", "サクヒン"]:
                hintIndex = "初登場作品"
            elif self.ansText in ["語源", "ゴゲン"]:
                hintIndex = "英語名由来"

        elif self.quizName == "jtoeq":
            if self.ansText in ["文字数", "モジスウ"]:
                hintIndex = "文字数"
            elif self.ansText in ["頭文字", "カシラモジ", "イニシャル"]:
                hintIndex = "イニシャル"

        else:
            ub.output_warning(f"不明なクイズ識別子(hint): {self.quizName}")
            return

        if hintIndex is None:
            return

        hintValue = pokemon.hint_value(hintIndex)
        if hintValue is None:
            await self.rm.reply(f"{hintIndex}は まだ 登録されて いないロ")
            return

        # 初出のヒントならEmbedにフィールドを追加
        if not any(field.name == hintIndex for field in self.quizEmbed.fields):
            self.quizEmbed.add_field(name=hintIndex, value=str(hintValue))
            try:
                await self.qm.edit(embed=self.quizEmbed, attachments=[])
            except discord.errors.Forbidden:
                pass

        await self.rm.reply(f"{hintIndex}は{hintValue}です")

    async def __disclose(self, tf, answered=None):
        global QUIZ_PROCESSING_FLAG
        if QUIZ_PROCESSING_FLAG == 1:
            ub.output_log(f"{self.quizName}: 応答処理実行中につき処理を中断")
            return 1

        QUIZ_PROCESSING_FLAG = 1  # 回答開示処理を始める
        ub.output_log(f"{self.quizName}: 回答開示を実行")

        if tf:  # 正解者がいる場合
            clearTime = self.rm.created_at - self.qm.created_at  # 所要時間を求める
            days, seconds = divmod(clearTime.total_seconds(), 86400)  # 所要時間を分解
            hours, seconds = divmod(seconds, 3600)
            minutes, seconds = divmod(seconds, 60)
            clearTimes = f"{int(seconds)}秒"
            if days >= 1:
                clearTimes = (
                    f"{int(days)}日 {int(hours):02}:{int(minutes):02}:{int(seconds):02}"
                )
            elif hours >= 1:
                clearTimes = f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"
            elif minutes >= 1:
                clearTimes = f"{int(minutes):02}:{int(seconds):02}"
            authorText = f"{self.opener.name} さんが正解! [TIME {clearTimes}]"
            link = self.__imageLink(answered)

        else:  # 正解者が存在せず,ギブアップされた場合
            authorText = f"{self.opener.name} さんがギブアップ"
            link = self.__imageLink(
                self.ansList[0]
            )  # self.ansZero['おなまえ']でもいいかも

        self.quizEmbed.set_author(name=authorText)  # 回答者の情報を表示

        if self.quizName == "bq":
            self.quizEmbed.description = f'こたえ: {",".join(self.ansList)}'
        elif self.quizName == "acq":
            self.quizEmbed.description = f"{ub.bss_to_text(self.ansZero)}\n"
            if self.ansList[0] == "同値":
                self.quizEmbed.description += (
                    f"{self.examText}はこうげきととくこうが同じ"
                )
            else:
                self.quizEmbed.description += (
                    f"{self.examText}は{self.ansList[0]}の方が高い"
                )

        elif self.quizName in ["etojq", "jtoeq", "ctojq"]:
            self.quizEmbed.description = f"{self.examText} -> [{self.ansList[0]}]"
            if self.quizName == "etojq":
                if self.ansZero.etymology:
                    self.quizEmbed.description += f"\n{self.ansZero.etymology}"
            elif self.quizName == "ctojq":
                self.quizEmbed.description += (
                    f"\n拼音: {ub.pinyin_to_text(self.examText)}"
                )

        if not "Decamark" in link:
            self.quizEmbed.set_thumbnail(url=link)  # サムネイルを変更する

        self.quizEmbed.set_footer(text=self.quizEmbed.footer.text + "(done)")

        # 処理前に最新のメッセージ状態を取得して確認
        try:
            # メッセージを再取得して最新の状態を確認
            updated_message = await self.qm.channel.fetch_message(self.qm.id)
            ub.output_log(f"クイズのフッター:{updated_message.embeds[0].footer.text}")
            if updated_message.embeds and "(done)" in updated_message.embeds[0].footer.text:
                ub.output_log("クイズの処理中にクイズが終了しています")
                QUIZ_PROCESSING_FLAG = 0  # 回答開示処理を終わる
                return 1  # 処理中断（失敗）を示す値
        except Exception as e:
            ub.output_log(f"メッセージ取得中にエラー: {e}")
            # エラーがあっても処理継続

        if isinstance(self.rm, discord.Message):
            try:
                await self.qm.edit(embed=self.quizEmbed, attachments=[])
            except discord.errors.Forbidden:
                await self.qm.channel.send(embed=self.quizEmbed)

        elif isinstance(self.rm, discord.Interaction):
            fixView = discord.ui.View()
            fixView.from_message(self.qm)
            for child in fixView.children:
                child.disabled = True
            try:
                await self.rm.response.edit_message(
                    embed=self.quizEmbed, attachments=[], view=fixView
                )
            except discord.errors.Forbidden:
                pass

        QUIZ_PROCESSING_FLAG = 0  # 回答開示処理を終わる
        await self.__continue()  # 連続出題を試みる

        return 0

    async def __continue(self):
        if BAKUSOKU_MODE:
            ub.output_log(f"{self.quizName}: 連続出題を実行")
            loadingEmbed = discord.Embed(
                title="**BAKUSOKU MODE ON**",
                color=0x0000FF,
                description="次のクイズを生成チュウ",
            )
            loadMessage = await self.qm.channel.send(embed=loadingEmbed)
            await quiz(self.bot, self.quizName).post(self.qm.channel)
            await loadMessage.delete()

    def __answers(self):
        ub.output_log(f"{self.quizName}: 正答リスト生成を実行")
        answers = []
        aData = None
        pokedex = get_pokedex()

        if self.quizName == "bq":
            stats = tuple(map(int, self.examText.split("-")))
            aDatas = [p for p in pokedex.records if p.stats == stats]
            aData = aDatas[0]
            answers = [p.name for p in aDatas]

        elif self.quizName == "acq":
            aData = ub.fetch_pokemon(self.examText)[0]
            if aData.atk == aData.spa:
                answers.append("同値")
            elif aData.atk > aData.spa:
                answers.append("こうげき")
            else:
                answers.append("とくこう")

        elif self.quizName == "etojq":
            aData = [p for p in pokedex.records if p.eng == self.examText][0]
            answers.append(aData.name)

        elif self.quizName == "jtoeq":
            aData = ub.fetch_pokemon(self.examText)[0]
            answers.append(aData.eng)

        elif self.quizName == "ctojq":
            aData = [p for p in pokedex.records if p.cht == self.examText][0]
            answers.append(aData.name)

        else:
            ub.output_warning(f"不明なクイズ識別子(answers): {self.quizName}")
            return answers, aData

        return answers, aData  # 正答のリストと0番目の正答をタプルで返す

    def __random_with(self, filter_dict, field):
        """条件に合うポケモンから、指定の項目を持つ1匹をランダムに選ぶ。"""
        candidates = [
            p for p in get_pokedex().filter(filter_dict) if getattr(p, field)
        ]
        if not candidates:
            ub.output_error(f"{self.quizName}: 出題条件に合うポケモンがいません")
            return None
        return random.choice(candidates)

    def __imageLink(self, searchWord=None):
        ub.output_log(f"{self.quizName}: 画像リンク生成を実行")
        link = f"{cfg.EX_SOURCE_LINK}Decamark.png"  # デフォルトは(?)マーク
        if searchWord is not None:
            if self.quizName in ["bq", "acq", "etojq", "jtoeq", "ctojq"]:
                displayImage = ub.fetch_pokemon(searchWord)
                if displayImage:  # 回答ポケモンが発見できた場合
                    link = f"{cfg.EX_SOURCE_LINK}art/{displayImage[0].image_number}.png"
            else:
                ub.output_warning(f"不明なクイズ識別子(imageLink): {self.quizName}")
        return link

    def __log(self, judge, exAns):
        logPath = f"log/{self.quizName}log.csv"
        ub.output_log(f"{self.quizName}: log生成を実行\n {logPath}")

        if os.path.exists(logPath):
            log_df = pd.read_csv(logPath)
        else:
            log_df = pd.DataFrame(columns=["正誤判定", "内容", "解答", "入力認識可否"])

        nRow = pd.DataFrame(
            {
                "正誤判定": judge,
                "内容": self.examText,
                "解答": self.ansText,
                "入力認識可否": judge is not None,
            },
            index=[0],
        )
        log_df = pd.concat([nRow, log_df]).reset_index(drop=True)
        log_df.to_csv(logPath, mode="w", header=True, index=False)


async def setup(bot):
    await bot.add_cog(Quiz(bot))