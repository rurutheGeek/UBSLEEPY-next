# -*- coding: utf-8 -*-
# quiz_kinds/noq.py
"""図鑑番号クイズ（noq）。出し方（variant）が2つある。

- ptonq: ポケモン → 番号（既定）。問題文は「レパルダス -> [?]」、数字で答える。
- ntopq: 番号 → ポケモン。問題文は「No.510 -> [?]」、ポケモンの名前で答える。

出し方は問題文から見分け（restore）、セッションの fromNumber に持つ。
"""
import random
import re
import unicodedata

from bot_module import func as ub
from bot_module.pokedex import get_pokedex

from .base import NO_POKEMON, Draft, Judgement, NameAnswerKind, arrow_question
from .translate import ArrowQuiz

# 正解からこの数まで離れた番号（のポケモン）は「おしい」
NUMBER_NEAR = 3
NUMBER_RE = re.compile(r"^(?:no\.?|№)?\s*(\d{1,4})\s*番?$", re.IGNORECASE)
# 番号 → ポケモンの問題文
FROM_NUMBER_RE = re.compile(r"No\.\d+ ->")

# ポケモン → 番号のヒント（番号の見当がつくものだけ）
NUMBER_HINT_WORDS = ["ヒント", "地方", "チホウ", "作品", "サクヒン"]


def parse_number(text) -> int | None:
    """「510」「No.510」「５１０番」のような回答を図鑑番号に。数字でなければ None。"""
    match = NUMBER_RE.match(unicodedata.normalize("NFKC", str(text or "")).strip())
    return int(match.group(1)) if match else None


class NumberQuiz(ArrowQuiz, NameAnswerKind):

    def variant(self, s):
        return "ntopq" if s.fromNumber else "ptonq"

    async def build(self, s, embed, channel, voice_channel):
        candidates = [p for p in get_pokedex().records if p.form_id == "00"]
        if not candidates:
            await channel.send(NO_POKEMON)
            return None
        qDatas = random.choice(candidates)
        embed.title = "図鑑番号クイズ"
        if self.variant(s) == "ntopq":
            embed.description = f"No.{qDatas.species} -> [?]"
            embed.set_thumbnail(url=self.image_link())  # 正解までDecamark
        else:
            embed.description = f"{qDatas.name} -> [?]"
            embed.set_thumbnail(url=self.image_link(qDatas.name))
        return Draft(record=self.pokemon_record(
            qDatas, arrow_question(embed.description)))

    def restore(self, s):
        # 出し方は、問題文（No.510 -> / レパルダス ->）から見分ける
        s.fromNumber = bool(FROM_NUMBER_RE.match(s.quizEmbed.description or ""))

    def hint_words(self, s):
        if self.variant(s) == "ntopq":
            return super().hint_words(s)
        return NUMBER_HINT_WORDS

    def answers(self, s):
        if self.variant(s) == "ntopq":
            aData = get_pokedex().base(s.examText.removeprefix("No."))
            return [aData.name], aData
        aData = ub.fetch_pokemon(s.examText)[0]
        return [aData.species], aData

    def interpret(self, s):
        if self.variant(s) == "ntopq":
            return super().interpret(s)
        number = parse_number(s.rawText)
        if number is None:
            return Judgement(answer=s.ansText,
                             unrecognized="図鑑番号を 数字で 答えてね（例: `510`）")
        near = None
        if 0 < abs(number - int(s.ansList[0])) <= NUMBER_NEAR:
            near = "おしいロ！ 番号が 近いロ"
        return Judgement(answer=str(number), near=near)

    def refine(self, s, judgement, found):
        # 当てるのは種族。フォームの名前で答えても正解
        gap = abs(int(judgement.pokemon.species) - int(s.ansZero.species))
        if gap == 0:
            judgement.answer = s.ansList[0]
        elif gap <= NUMBER_NEAR:
            judgement.near = "おしいロ！ 図鑑番号が 近い ポケモンだロ"
        return judgement

    async def hint_index(self, s):
        if self.variant(s) == "ntopq":
            return await super().hint_index(s)
        # 番号の見当がつくもの（地方・初登場作品）だけ出す
        if s.ansText in ["作品", "サクヒン"]:
            return "初登場作品"
        if s.ansText in ["地方", "チホウ"] or not any(
                field.name == "出身地" for field in s.quizEmbed.fields):
            return "出身地"
        return "初登場作品"
