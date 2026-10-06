# -*- coding: utf-8 -*-
# quiz_session.py
"""ポケモンクイズのセッション（出題・回答受付・判定・開示）。

cogs/quiz.py の Cog が作り、Discordへの送受信はこのクラスが行う。
実行時状態は QuizState にまとめ、Cogが持つものを渡す。
"""
import copy
import hashlib
import os
from pathlib import Path
import random
import re
import secrets

import discord
import jaconv
import pandas as pd

import bot_module.config as cfg
from bot_module import func as ub
from bot_module.pokedex import get_pokedex
from bot_module.save import SaveError

# 鳴き声クイズの音源。tools/fetch_cries.py が置き、クイズはローカル参照だけする。
# latest=あたらしい鳴き声（全種）、legacy=BWまでの古い鳴き声（1〜649）。
CRY_DIRECTORY = Path("resource/cry")
CRY_KINDS = ("latest", "legacy")
# 開示で「どちらの鳴き声だったか」に使う呼び名
CRY_LABELS = {"latest": "今", "legacy": "BW以前"}
# 出題条件（既定はデフォルト＝今の鳴き声。設定は /crydata で変更）
CRY_MODE_LABELS = {
    "latest": "デフォルト",
    "legacy": "BW以前",
    "mix": "両方",
}
# 添付ファイル名は cry-<nonce>-<ハッシュ>.ogg。
# nonceは出題ごとのランダム値（ファイル名に埋め込むので時刻にも状態にも依存しない）。
# ハッシュには答えの名前と鳴き声の種類を混ぜるので、種類はファイル名からは読めない。
# 同じポケモンでも毎回ファイル名が変わり、答えは投稿から逆算できる（状態を持たない）。
CRY_HASH_LENGTH = 12
CRY_NONCE_BYTES = 3
CRY_FILENAME_RE = re.compile(r"^cry-([0-9a-f]+)-([0-9a-f]+)\.ogg$")


def cry_hash(name: str, kind: str, nonce: str) -> str:
    """種類・nonce・答えの名前から、添付ファイル名に使う短いハッシュを作る。"""
    digest = hashlib.sha1(f"{kind}:{nonce}:{name}".encode("utf-8")).hexdigest()
    return digest[:CRY_HASH_LENGTH]


def cry_filename(name: str, kind: str, nonce: str) -> str:
    return f"cry-{nonce}-{cry_hash(name, kind, nonce)}.ogg"


def cry_from_message(message) -> tuple | None:
    """投稿の添付ファイル名から (ポケモン名, 鳴き声の種類) を逆算する。

    名前と種類の組み合わせをハッシュして一致を探す。見つからなければNone
    （添付が消された・形式が違うとき）。
    """
    for attachment in getattr(message, "attachments", None) or []:
        match = CRY_FILENAME_RE.match(getattr(attachment, "filename", "") or "")
        if match is None:
            continue
        nonce, digest = match.group(1), match.group(2)
        for pokemon in get_pokedex().records:
            if pokemon.form_id != "00":
                continue
            for kind in CRY_KINDS:
                if cry_hash(pokemon.name, kind, nonce) == digest:
                    return pokemon.name, kind
    return None


class QuizState:
    """クイズの実行時状態（Botの再起動でリセットされる）。"""

    def __init__(self):
        self.bq_filter_dict = copy.deepcopy(cfg.DEFAULT_FILTER_DICT)  # 現在の出題条件
        self.bakusoku_mode = True  # 連続出題モード
        self.processing = False  # 回答開示処理中フラグ
        self.cry_mode = "latest"  # 鳴き声クイズの出題条件: latest / legacy / mix
        self.cry_filter_dict = {}  # 鳴き声クイズの絞り込み（地方・世代など。空は全部）


class QuizSession:
    def __init__(self, bot, quizName, state=None):
        self.bot = bot
        self.quizName = quizName
        self.state = state or QuizState()

    async def post(self, sendChannel):
        ub.output_log(f"{self.quizName}: クイズを出題します")

        quizContent = None
        quizFile = None
        quizEmbed = discord.Embed(title="", color=0x9013FE, description="")
        quizEmbed.set_footer(text=f"No.26 ポケモンクイズ - {self.quizName}")
        quizView = None
        # 必要な要素をクイズごとに編集

        if self.quizName == "bq":
            qDatas = get_pokedex().random(self.state.bq_filter_dict)
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

        elif self.quizName == "cryq":
            picked = self.__random_cry()
            if picked is None:
                await sendChannel.send(
                    "出題条件に合う鳴き声がありません"
                    "（`/crydata` で条件を確認、リセットで既定に戻せます）")
                return
            qDatas, cryKind = picked
            quizEmbed.title = "鳴き声クイズ"
            quizEmbed.description = "鳴き声を聞いて ポケモン名を答えよう"
            quizEmbed.set_thumbnail(url=self.__imageLink())  # 正解までDecamark
            cryNonce = secrets.token_hex(CRY_NONCE_BYTES)
            quizFile = discord.File(
                str(CRY_DIRECTORY / cryKind / f"{qDatas.ndex_number}.ogg"),
                filename=cry_filename(qDatas.name, cryKind, cryNonce))

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
        if self.quizName in ["bq", "ctojq", "cryq"]:
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
        elif self.quizName == "cryq":
            entry = cry_from_message(self.qm)
            if entry is None:
                await self.rm.reply(
                    "この問題の答えが分からなくなりました。もう一度 /q で出題してください")
                return
            self.examText = entry[0]

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
        if self.quizName in ["bq", "etojq", "ctojq", "cryq"]:
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
            self.quizName in ["bq", "etojq", "ctojq", "cryq"] and repPokeData is None
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
            try:
                ub.report(
                    self.opener.id, f"{self.quizName}{judge}", 1, self.opener.name
                )  # 回答記録のレポート
            except SaveError:
                ub.output_error("クイズ戦績の保存に失敗しました")
                if isinstance(self.rm, discord.Message):
                    await self.rm.reply("戦績の保存に失敗しました")

        self.__log(judge, self.ansList[0])

    async def __hint(self):
        ub.output_log(f"{self.quizName}: ヒント表示を実行")

        pokemon = self.ansZero
        hintIndex = None

        if self.quizName in ["bq", "etojq", "ctojq", "cryq"]:
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
                # 添付（鳴き声・グラフ）は消さない。attachments を渡さないと保持される
                await self.qm.edit(embed=self.quizEmbed)
            except discord.errors.Forbidden:
                pass

        await self.rm.reply(f"{hintIndex}は{hintValue}です")

    async def __disclose(self, tf, answered=None):
        if self.state.processing:
            ub.output_log(f"{self.quizName}: 応答処理実行中につき処理を中断")
            return 1

        self.state.processing = True  # 回答開示処理を始める
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
        elif self.quizName == "cryq":
            entry = cry_from_message(self.qm) or ('', '')
            label = CRY_LABELS.get(entry[1], '')
            self.quizEmbed.description = (
                f"こたえ: {self.ansList[0]}"
                + (f"（{label}のなきごえ）" if label else ''))
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
                self.state.processing = False  # 回答開示処理を終わる
                return 1  # 処理中断（失敗）を示す値
        except Exception as e:
            ub.output_log(f"メッセージ取得中にエラー: {e}")
            # エラーがあっても処理継続

        if isinstance(self.rm, discord.Message):
            try:
                # 添付は消さない（鳴き声をもう一度聞けるように）
                await self.qm.edit(embed=self.quizEmbed)
            except discord.errors.Forbidden:
                await self.qm.channel.send(embed=self.quizEmbed)

        elif isinstance(self.rm, discord.Interaction):
            fixView = discord.ui.View()
            fixView.from_message(self.qm)
            for child in fixView.children:
                child.disabled = True
            try:
                # 添付は消さない（attachments を渡さないと保持される）
                await self.rm.response.edit_message(
                    embed=self.quizEmbed, view=fixView
                )
            except discord.errors.Forbidden:
                pass

        self.state.processing = False  # 回答開示処理を終わる
        await self.__continue()  # 連続出題を試みる

        return 0

    async def __continue(self):
        if self.state.bakusoku_mode:
            ub.output_log(f"{self.quizName}: 連続出題を実行")
            loadingEmbed = discord.Embed(
                title="**BAKUSOKU MODE ON**",
                color=0x0000FF,
                description="次のクイズを生成チュウ",
            )
            loadMessage = await self.qm.channel.send(embed=loadingEmbed)
            await QuizSession(self.bot, self.quizName, self.state).post(self.qm.channel)
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

        elif self.quizName == "cryq":
            aData = ub.fetch_pokemon(self.examText)[0]
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

    def __random_cry(self):
        """鳴き声ファイルがある基本形態から (ポケモン, 種類) をランダムに選ぶ。

        出題条件（self.state.cry_mode）に合う種類だけを使う。
        mix のときは、あるものをランダムに選ぶ。
        """
        if self.state.cry_mode == "mix":
            allowed = CRY_KINDS
        else:
            allowed = (self.state.cry_mode,)
        pokedex = get_pokedex()
        records = (pokedex.filter(self.state.cry_filter_dict)
                   if self.state.cry_filter_dict else pokedex.records)
        candidates = []
        for pokemon in records:
            if pokemon.form_id != "00":
                continue
            kinds = [kind for kind in allowed
                     if (CRY_DIRECTORY / kind / f"{pokemon.ndex_number}.ogg").exists()]
            if kinds:
                candidates.append((pokemon, kinds))
        if not candidates:
            ub.output_error(f"{self.quizName}: 鳴き声のあるポケモンがいません")
            return None
        pokemon, kinds = random.choice(candidates)
        return pokemon, random.choice(kinds)

    def __imageLink(self, searchWord=None):
        ub.output_log(f"{self.quizName}: 画像リンク生成を実行")
        link = f"{cfg.EX_SOURCE_LINK}Decamark.png"  # デフォルトは(?)マーク
        if searchWord is not None:
            if self.quizName in ["bq", "acq", "etojq", "jtoeq", "ctojq", "cryq"]:
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
