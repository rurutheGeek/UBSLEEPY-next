# -*- coding: utf-8 -*-
# quiz_session.py
"""ポケモンクイズのセッション（出題・回答受付・判定・開示）。

cogs/quiz.py の Cog が作り、Discordへの送受信はこのクラスが行う。
実行時状態は QuizState にまとめ、Cogが持つものを渡す。
種別ごとに違う所（出題の中身・問題文・正答・ヒント・判定のゆれ・開示の書き方）は
bot_module/quiz_kinds/ の種別のクラスにあり、ここは共通の流れだけを持つ。
"""
import asyncio
import copy

import discord

import bot_module.config as cfg
from bot_module import func as ub
from bot_module.quiz_kinds import kind_for
from bot_module.quiz_kinds.base import pokemon_id
import bot_module.save as save
from bot_module.save import SaveError

# 判定ログ（quiz_log）の judge に入れる、回答ではない操作
LOG_GIVEUP = "ギブアップ"
LOG_HINT = "ヒント"
# 判定ログに残す入力の原文の長さ（クイズへの返信なら何でも届くので、長文は切る）
LOG_RAW_LENGTH = 200

# 1つのチャンネルで覚えておく出題中のクイズの数
OPEN_QUIZ_LIMIT = 20


def _audio_source(path):
    """ボイス再生用の音源。テストから差し替えられるよう関数にしてある。"""
    return discord.FFmpegPCMAudio(str(path))


def play_cry(voice_client, path) -> bool:
    """接続済みのボイスクライアントで鳴き声を流す。"""
    try:
        # 前の音が鳴っている間は play が失敗するので、止めてから流す
        if voice_client.is_playing():
            voice_client.stop()
        voice_client.play(_audio_source(path))
        return True
    except (discord.ClientException, discord.HTTPException, OSError) as error:
        ub.output_error(f"ボイスで鳴き声を流せませんでした: {error}")
        return False



class QuizState:
    """クイズの実行時状態（Botの再起動でリセットされる）。"""

    def __init__(self):
        self.bq_filter_dict = copy.deepcopy(cfg.DEFAULT_FILTER_DICT)  # 現在の出題条件
        self.bakusoku_mode = True  # 連続出題モード
        self.disclosing = set()  # 回答開示処理中のクイズ投稿（メッセージID）
        self.cry_mode = "latest"  # 鳴き声クイズの出題条件: latest / legacy / mix
        self.cry_filter_dict = {}  # 鳴き声クイズの絞り込み（地方・世代など。空は全部）
        self.intro_works = []  # イントロクイズの絞り込み: 作品（空は全部）
        self.intro_categories = []  # イントロクイズの絞り込み: 区分（空は全部）
        self.intro_secret = False  # イントロクイズ: シークレットの曲（初期バージョンなど）も出す
        # 出題中（未回答）のクイズ: チャンネルID -> [(メッセージID, 種別)]（新しい順）。
        # 返信なしの回答をどのクイズへ入れるか探すのに使う。キーの無いチャンネルは
        # まだ調べていない（再起動のあとなど）ので、cogs/quiz.py が履歴から作る。
        self.open_quizzes = {}

    def remember_quiz(self, channel_id, message_id, quiz_name):
        """出題したクイズを覚える。まだ調べていないチャンネルは、履歴から作るときに入る。"""
        quizzes = self.open_quizzes.get(channel_id)
        if quizzes is None:
            return
        quizzes.insert(0, (message_id, quiz_name))
        del quizzes[OPEN_QUIZ_LIMIT:]  # 答えられないまま残ったものが増え続けないように

    def forget_quiz(self, channel_id, message_id):
        """開示が済んだ・消されたクイズを外す。"""
        quizzes = self.open_quizzes.get(channel_id)
        if quizzes:
            quizzes[:] = [quiz for quiz in quizzes if quiz[0] != message_id]



class QuizSession:
    def __init__(self, bot, quizName, state=None):
        self.bot = bot
        self.quizName = quizName
        self.kind = kind_for(quizName)  # 種別ごとの違いを受け持つ
        self.state = state or QuizState()
        self.voice_channel = None  # 出題時に鳴き声を流すボイスチャンネル
        # 図鑑番号クイズの出し方: 番号からポケモンを当てる（既定はポケモンから番号）
        self.fromNumber = False
        # 出題形式パネルで選んだ出し方（None は既定）と、穴埋めの穴の数
        self.mode = None
        self.holes = None

    @property
    def variant(self):
        """判定の分かれ目に使う種別。図鑑番号クイズ（noq）は出し方で2つに分ける。"""
        return self.kind.variant(self)

    async def post(self, sendChannel, voiceChannel=None):
        ub.output_log(f"{self.quizName}: クイズを出題します")
        self.voice_channel = voiceChannel

        quizEmbed = discord.Embed(title="", color=0x9013FE, description="")
        quizEmbed.set_footer(text=f"No.26 ポケモンクイズ - {self.quizName}")
        # 中身は種別ごとに作る。出題できないときは種別が返事をして None
        draft = await self.kind.build(self, quizEmbed, sendChannel, voiceChannel)
        if draft is None:
            return

        self.qm = await sendChannel.send(
            content=draft.content, file=draft.file, embed=quizEmbed, view=draft.view
        )

        self.state.remember_quiz(
            getattr(sendChannel, "id", None), getattr(self.qm, "id", None),
            self.quizName)

        await asyncio.to_thread(self.__log_post, draft)

        if draft.voice_path is not None and voiceChannel is not None:
            await self.__play_cry(voiceChannel, draft.voice_path)

    def __conditions(self, draft) -> dict:
        """出題ログに残す、そのときの出題条件。"""
        conditions = {"連続出題": self.state.bakusoku_mode}
        conditions.update(self.kind.conditions(self, draft))
        return conditions

    def __log_post(self, draft):
        """出題を記録する。question は判定ログ（__log）と同じ書き方にそろえる。"""
        if draft.record is None:
            return
        question, answer, answer_id = draft.record
        guild_id = getattr(getattr(self.qm, "guild", None), "id", 0) or 0
        save.add_quiz_post(
            guild_id, self.quizName, getattr(self.qm, "id", None),
            question, answer, answer_id, self.__conditions(draft))

    async def __play_cry(self, voice_channel, path):
        """ボイスチャンネルで鳴き声を流す（全員が同時に聞ける）。

        権限が無い・接続できないときはログに残して添付だけにする。
        """
        try:
            voice_client = voice_channel.guild.voice_client
            if voice_client is None:
                voice_client = await voice_channel.connect(self_deaf=True)
            elif voice_client.channel != voice_channel:
                await voice_client.move_to(voice_channel)
        except (discord.Forbidden, discord.ClientException,
                discord.HTTPException, OSError) as error:
            ub.output_error(f"{self.quizName}: ボイスに接続できませんでした: {error}")
            return
        if play_cry(voice_client, path):
            ub.output_log(f"{self.quizName}: 鳴き声を再生します: {voice_channel.name}")

    async def try_response(self, response):

        # インスタンスがメッセージ/インタラクションかどうかで代入データを変える
        if isinstance(response, discord.Message):
            self.rm = response
            self.qm = response.reference.resolved
            self.ansText = ub.format_text(response.content)
            self.rawText = response.content
            self.opener = self.rm.author
        elif isinstance(response, discord.Interaction):
            self.rm = response
            self.qm = response.message
            self.ansText = self.rm.data["custom_id"].split("_")[1]
            self.rawText = self.ansText
            self.opener = self.rm.user
            # customIDが"acq_こうげき/とくこう/同値"のようなかたちを想定

        self.quizEmbed = self.qm.embeds[0]
        self.kind.restore(self)  # 出し方（図鑑番号・種族値・穴埋め）・種族値クイズのグラフ
        # この時点で出ているヒント（判定ログに残す。ヒントを足す前に控える）
        self.hintsShown = [field.name for field in self.quizEmbed.fields]
        self.hintGiven = None

        gives = ["ギブ", "ギブアップ", "降参", "敗北"]
        hints = self.kind.hint_words(self)  # クイズごとのヒント項目

        # クイズの問題文を投稿から取得する
        if not await self.kind.read_question(self):
            return

        # ここでクイズの回答を取得する
        self.ansList, self.ansZero = self.__answers()

        if self.ansText in gives:
            await self.__giveup()
            await asyncio.to_thread(
                self.__log, LOG_GIVEUP, self.ansList[0], True)
        elif self.ansText in hints:
            await self.__hint()
            await asyncio.to_thread(
                self.__log, LOG_HINT, self.ansList[0], True, self.hintGiven)
        else:
            await self.__judge()

    async def __giveup(self):
        ub.output_log(f"{self.quizName}: ギブアップを実行")
        if isinstance(self.rm, discord.Message):
            await self.rm.add_reaction("😅")
            await self.rm.reply(f"答えは{self.kind.giveup_answer(self)}でした")
        await self.__disclose(False)

    async def __judge(self):
        ub.output_log(f"{self.quizName}: 正誤判定を実行")
        if await self.kind.judge(self):
            return  # 判定から記録・開示まで種別が自分で行った

        # 回答の読み取り（名前の引き当て・おしい・番号など）は種別ごと
        verdict = self.kind.interpret(self)
        isMessage = isinstance(self.rm, discord.Message)

        if verdict.answer in self.ansList:
            judge = "正答"
            if isMessage:
                await self.rm.add_reaction("⭕")
            result = await self.__disclose(True, verdict.answer)
            if result == 1:
                # ほかの回答で先に開示された。戦績にもログにも数えない
                if isMessage:
                    await self.rm.remove_reaction("⭕", self.bot.user)
                return
        else:
            judge = "誤答"
            reaction = "❌"
            if not isMessage:  # ボタンで回答しているときはギブアップになる
                await self.__disclose(False)

        if verdict.unrecognized:
            # 答えとして読めない（図鑑に無い名前・数字でない・聞き返し）
            judge = None  # 戦績には数えない
            if isMessage:
                reaction = "❓"
                await self.rm.reply(verdict.unrecognized)
        elif judge == "誤答" and verdict.near:
            judge = None  # 戦績には数えない
            if isMessage:
                reaction = "❓"
                await self.rm.reply(verdict.near)
        elif judge == "誤答" and isMessage:
            await self.kind.after_wrong(self, verdict)

        if judge != "正答" and isMessage:
            await self.rm.add_reaction(reaction)

        detail = verdict.detail
        if detail is None and judge is None and verdict.near:
            detail = "おしい"
        await self.record(
            judge, self.ansList[0], detail,
            pokemon_id(verdict.pokemon) if verdict.pokemon is not None else None)

    async def record(self, judge, exAns, detail=None, input_id=None, question=None):
        """戦績（正答・誤答のときだけ）と判定ログを残す。

        1つの回答で何度も判定する種別（穴埋め）は、判定ごとに呼ぶ。
        """
        if judge is not None:
            try:
                # DBが遅くてもBot全体を止めないよう、別スレッドで書く
                await asyncio.to_thread(
                    ub.report,
                    self.opener.id, f"{self.quizName}{judge}", 1, self.opener.name
                )  # 回答記録のレポート
            except SaveError:
                ub.output_error("クイズ戦績の保存に失敗しました")
                if isinstance(self.rm, discord.Message):
                    await self.rm.reply("戦績の保存に失敗しました")
        await asyncio.to_thread(
            self.__log, judge, exAns, None, detail, input_id, question)

    async def disclose(self, tf, answered=None):
        """答えを開示する（種別が自分で判定するとき用）。先に開示されていたら 1。"""
        return await self.__disclose(tf, answered)

    async def __hint(self):
        ub.output_log(f"{self.quizName}: ヒント表示を実行")

        # 出す項目は種別ごと。出さないときは種別が返事をして None
        hintIndex = await self.kind.hint_index(self)
        if hintIndex is None:
            return

        hintValue = self.ansZero.hint_value(hintIndex)
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

        self.hintGiven = hintIndex
        await self.rm.reply(f"{hintIndex}は{hintValue}です")

    async def __disclose(self, tf, answered=None):
        if self.qm.id in self.state.disclosing:
            ub.output_log(f"{self.quizName}: 応答処理実行中につき処理を中断")
            return 1

        self.state.disclosing.add(self.qm.id)  # 回答開示処理を始める
        try:
            result = await self.__reveal(tf, answered)
        finally:
            # 途中で例外が出ても、開示中のまま残さない
            self.state.disclosing.discard(self.qm.id)
        if result == 0:
            await self.__continue()  # 連続出題を試みる
        return result

    async def __reveal(self, tf, answered):
        ub.output_log(f"{self.quizName}: 回答開示を実行")

        # 処理前に最新のメッセージ状態を取得して確認
        try:
            # メッセージを再取得して最新の状態を確認
            updated_message = await self.qm.channel.fetch_message(self.qm.id)
            ub.output_log(f"クイズのフッター:{updated_message.embeds[0].footer.text}")
            if updated_message.embeds and "(done)" in updated_message.embeds[0].footer.text:
                ub.output_log("クイズの処理中にクイズが終了しています")
                return 1  # 処理中断（失敗）を示す値
        except Exception as e:
            ub.output_log(f"メッセージ取得中にエラー: {e}")
            # エラーがあっても処理継続

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
            link = self.kind.image_link(answered)

        else:  # 正解者が存在せず,ギブアップされた場合
            authorText = f"{self.opener.name} さんがギブアップ"
            link = self.kind.image_link(
                self.ansList[0]
            )  # self.ansZero['おなまえ']でもいいかも

        if self.state.bakusoku_mode:
            # 次の問題が出る予告。別の投稿にすると遅くなるので、この行に付ける
            authorText += " ⏩連続出題ON"
        self.quizEmbed.set_author(name=authorText)  # 回答者の情報を表示

        self.kind.reveal(self)  # 答えの書き方は種別ごと

        if not "Decamark" in link:
            self.quizEmbed.set_thumbnail(url=link)  # サムネイルを変更する

        self.quizEmbed.set_footer(text=self.quizEmbed.footer.text + "(done)")
        self.state.forget_quiz(
            getattr(getattr(self.qm, "channel", None), "id", None), self.qm.id)

        if isinstance(self.rm, discord.Message):
            try:
                # 添付は消さない（鳴き声をもう一度聞けるように）
                await self.qm.edit(embed=self.quizEmbed)
            except discord.errors.Forbidden:
                await self.qm.channel.send(embed=self.quizEmbed)

        elif isinstance(self.rm, discord.Interaction):
            fixView = discord.ui.View.from_message(self.qm)
            for child in fixView.children:
                child.disabled = True
            try:
                # 添付は消さない（attachments を渡さないと保持される）
                await self.rm.response.edit_message(
                    embed=self.quizEmbed, view=fixView
                )
            except discord.errors.Forbidden:
                pass

        return 0

    async def __continue(self):
        if self.state.bakusoku_mode:
            ub.output_log(f"{self.quizName}: 連続出題を実行")
            # 「生成チュウ」の表示は送信と削除で往復が増えるので出さない
            session = QuizSession(self.bot, self.quizName, self.state)
            session.fromNumber = self.fromNumber  # 同じ出し方で続ける
            session.mode = self.mode
            session.holes = self.holes
            await session.post(
                self.qm.channel, voiceChannel=self.voice_channel)

    def __answers(self):
        ub.output_log(f"{self.quizName}: 正答リスト生成を実行")
        return self.kind.answers(self)  # 正答のリストと0番目の正答をタプルで返す

    def __answer_id(self) -> str:
        """正解のID。種族値クイズ・図鑑説明クイズは正解がいくつもあれば、全部並べる。"""
        return self.kind.answer_id(self)

    def __log(self, judge, exAns, recognized=None, detail=None, input_id=None,
              question=None):
        # 判定ログはDB（ubsleepy.quiz_log）へ。DBが無い手元はCSV（開発用）
        # 分析（間違いやすい問題・書き間違い・本人の苦手）に使う
        logPath = f"log/{self.quizName}log.csv"
        ub.output_log(f"{self.quizName}: log生成を実行\n {logPath}")
        guild_id = getattr(getattr(self.qm, "guild", None), "id", 0) or 0
        if recognized is None:
            recognized = judge is not None
        logged, exAns = self.kind.log_question(self, exAns)
        question = logged if question is None else question
        save.add_quiz_log(
            guild_id, self.quizName, judge, question, self.ansText,
            recognized, csv_path=logPath, answer=exAns,
            quiz_message_id=getattr(self.qm, "id", None),
            user_id=getattr(self.opener, "id", None),
            answer_id=self.__answer_id(),
            input_raw=(self.rawText or "")[:LOG_RAW_LENGTH],
            input_id=input_id,
            hints="|".join(self.hintsShown),
            detail=detail)
