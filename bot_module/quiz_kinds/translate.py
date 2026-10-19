# -*- coding: utf-8 -*-
# quiz_kinds/translate.py
"""翻訳クイズ: 英和（etojq）・和英（jtoeq）・中日（ctojq）。

問題文は「<問題> -> [?]」の形で、開示で [?] に答えが入る。
"""
import jaconv

from bot_module import func as ub
from bot_module.pokedex import get_pokedex

from .base import (
    FINAL_STAGES, NO_POKEMON, POKEMON_HINT_WORDS, Draft, Judgement,
    NameAnswerKind, PokemonKind, arrow_question, arrow_reveal)


class ArrowQuiz:
    """「<問題> -> [?]」の形の問題文を使う種別（翻訳クイズ・図鑑番号クイズ）。"""

    async def read_question(self, s):
        s.examText = arrow_question(s.quizEmbed.description)
        return True

    def reveal(self, s):
        arrow_reveal(s)


class TranslateQuiz(ArrowQuiz):
    """出題する名前の項目（field）を持つポケモンから出す。"""
    title = ""
    field = ""

    async def build(self, s, embed, channel, voice_channel):
        qDatas = self.random_with(FINAL_STAGES, self.field)
        if qDatas is None:
            await channel.send(NO_POKEMON)
            return None
        embed.title = self.title
        embed.description = f"{self.question(qDatas)} -> [?]"
        self.decorate(embed, qDatas)
        return Draft(record=self.pokemon_record(
            qDatas, arrow_question(embed.description)))

    def question(self, pokemon):
        return getattr(pokemon, self.field)

    def decorate(self, embed, pokemon):
        """出題の embed に足すもの（サムネイルなど）。"""


class EnglishToJapaneseQuiz(TranslateQuiz, NameAnswerKind):
    title = "英和翻訳クイズ"
    field = "eng"

    def hint_words(self, s):
        return POKEMON_HINT_WORDS + ["語源", "ゴゲン"]

    def answers(self, s):
        aData = [p for p in get_pokedex().records if p.eng == s.examText][0]
        return [aData.name], aData

    def reveal(self, s):
        super().reveal(s)
        if s.ansZero.etymology:
            s.quizEmbed.description += f"\n{s.ansZero.etymology}"


class JapaneseToEnglishQuiz(TranslateQuiz, PokemonKind):
    title = "和英翻訳クイズ"
    field = "eng"

    def question(self, pokemon):
        return pokemon.name

    def decorate(self, embed, pokemon):
        embed.set_thumbnail(url=self.image_link(pokemon.name))

    def hint_words(self, s):
        return ["文字数", "モジスウ", "頭文字", "カシラモジ", "イニシャル"]

    def answers(self, s):
        aData = ub.fetch_pokemon(s.examText)[0]
        return [aData.eng], aData

    def interpret(self, s):
        answer = jaconv.z2h(
            jaconv.kata2alphabet(s.ansText), kana=False, ascii=False, digit=True
        ).lower()
        s.ansList[0] = s.ansList[0].lower()
        return Judgement(answer=answer)

    async def after_wrong(self, s, judgement):
        # ほかのポケモンの英名なら、どのポケモンかを教える
        pokes = [p for p in get_pokedex().records
                 if p.eng and p.eng.lower() == judgement.answer]
        if pokes:
            await s.rm.reply(f"{judgement.answer} は {pokes[0].name} の英名です")

    async def hint_index(self, s):
        if s.ansText in ["文字数", "モジスウ"]:
            return "文字数"
        if s.ansText in ["頭文字", "カシラモジ", "イニシャル"]:
            return "イニシャル"
        return None


class ChineseToJapaneseQuiz(TranslateQuiz, NameAnswerKind):
    title = "中日翻訳クイズ"
    field = "cht"

    def answers(self, s):
        aData = [p for p in get_pokedex().records if p.cht == s.examText][0]
        return [aData.name], aData

    def reveal(self, s):
        super().reveal(s)
        s.quizEmbed.description += f"\n拼音: {ub.pinyin_to_text(s.examText)}"
