# -*- coding: utf-8 -*-
# quiz_kinds/trq.py
"""トレーナークイズ（trq）: 手持ちのポケモンの名前とレベルから、トレーナーの名前を当てる。

答えは投稿の問題文（手持ちの並び）から引き直す。手持ちとレベルがまったく同じなら、
どのトレーナーで答えても正解。作品は問題文に出さず、開示で出す。
"""
import asyncio
import random

from bot_module import trainer_quiz
from bot_module.normalize import format_text

from .base import LOST_ANSWER, Draft, Judgement, QuizKind

HINT_WORDS = ["ヒント", "役割", "ヤクワリ", "作品", "サクヒン"]
HINT_INDEXES = ["役割", "作品"]


class TrainerQuiz(QuizKind):

    def shows_image(self):
        return False  # トレーナーの画像は無い

    async def build(self, s, embed, channel, voice_channel):
        catalog = await asyncio.to_thread(trainer_quiz.get_catalog)
        party = catalog.random()
        if party is None:
            await channel.send("トレーナーの手持ちを 読み込めて いないロ")
            return None
        embed.title = "トレーナークイズ"
        # 答えは問題文から引き直すので、手持ちのほかは書かない
        embed.description = party.question
        embed.set_thumbnail(url=self.image_link())
        names = party.names()
        return Draft(record=(party.question, names[0], self._answer_id(party)))

    async def read_question(self, s):
        catalog = await asyncio.to_thread(trainer_quiz.get_catalog)
        s.trainerParty = catalog.find(s.quizEmbed.description)
        if s.trainerParty is None:
            await s.rm.reply(LOST_ANSWER)
            return False
        s.examText = s.trainerParty.question
        return True

    def answers(self, s):
        return s.trainerParty.names(), s.trainerParty

    @staticmethod
    def _answer_id(party):
        """判定ログの正解のID（作品:名前。正解がいくつもあれば全部並べる）。"""
        return "|".join(dict.fromkeys(
            f"{battle.title_id}:{battle.name}" for battle in party.battles))

    def answer_id(self, s):
        return self._answer_id(s.trainerParty)

    def interpret(self, s):
        """名前は、ひらがな・カタカナ・全角半角のちがいを気にしない。"""
        wanted = format_text(s.ansText)
        for name in s.ansList:
            if format_text(name) == wanted:
                return Judgement(answer=name)
        return Judgement(answer=s.ansText)

    def hint_words(self, s):
        return HINT_WORDS

    async def hint_index(self, s):
        shown = [field.name for field in s.quizEmbed.fields]
        if s.ansText in ("役割", "ヤクワリ"):
            return "役割"
        if s.ansText in ("作品", "サクヒン"):
            return "作品"
        still = [index for index in HINT_INDEXES if index not in shown]
        return random.choice(still or HINT_INDEXES)

    def reveal(self, s):
        party = s.trainerParty
        s.quizEmbed.description = (
            f"{party.question}\nこたえ: {'・'.join(s.ansList)}"
            f"\n作品: {party.titles_label()}")
