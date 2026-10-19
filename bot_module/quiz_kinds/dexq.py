# -*- coding: utf-8 -*-
# quiz_kinds/dexq.py
"""図鑑説明クイズ（dexq）: ポケモンの名前を伏せた図鑑の説明文からポケモンを当てる。

答えは投稿の問題文（伏せ字にした文）から引き直す。同じ文になるポケモンはみな正解。
"""
import asyncio

from bot_module import dex_text
from bot_module.pokedex import get_pokedex

from .base import LOST_ANSWER, Draft, NameAnswerKind, pokemon_id


def dex_answers(entries) -> dict:
    """図鑑説明クイズの正解。(種族, フォーム) -> (Pokemon, 開示で見せる名前)。

    説明文の載っているフォームが正解。基本の姿が入っている種族は、種族名で見せる。
    """
    pokedex = get_pokedex()
    answers = {}
    for entry in entries:
        base = pokedex.base(entry.species)
        records = [record for record in pokedex.variants(entry.species)
                   if record.form_id in entry.forms] or [base]
        for record in records:
            shown = base.name if "00" in entry.forms else record.name
            answers[(record.species, record.form_id)] = (record, shown)
    return answers


class DexTextQuiz(NameAnswerKind):

    async def build(self, s, embed, channel, voice_channel):
        catalog = await asyncio.to_thread(dex_text.get_catalog)
        entry = catalog.random()
        if entry is None:
            await channel.send("図鑑説明を 読み込めて いないロ")
            return None
        # 伏せ字にした文が同じになる種族は、みな正解。記録は判定と同じ先頭の正解で残す
        qDatas = next(iter(dex_answers(catalog.find(entry.question)).values()))[0]
        embed.title = "図鑑説明クイズ"
        # 答えは問題文から引き直すので、説明のほかは書かない
        embed.description = entry.question
        embed.set_thumbnail(url=self.image_link())  # 正解までDecamark
        return Draft(record=self.pokemon_record(qDatas))

    async def read_question(self, s):
        catalog = await asyncio.to_thread(dex_text.get_catalog)
        s.dexEntries = catalog.find(s.quizEmbed.description)
        if not s.dexEntries:
            await s.rm.reply(LOST_ANSWER)
            return False
        s.dexCatalog = catalog
        s.dexAnswers = dex_answers(s.dexEntries)
        s.examText = next(iter(s.dexAnswers.values()))[1]
        return True

    def answers(self, s):
        aData = next(iter(s.dexAnswers.values()))[0]
        answers = list(dict.fromkeys(
            shown for _record, shown in s.dexAnswers.values()))
        return answers, aData

    def answer_id(self, s):
        """正解がいくつもあれば、全部並べる。"""
        return "|".join(
            pokemon_id(record) for record, _shown in s.dexAnswers.values())

    def refine(self, s, judgement, found):
        """種族名で答えたら基本の姿、フォームの名前ならそのフォームを答えたものとする。

        同じ種族の別のフォーム・進化の前後は「おしい」。
        """
        intended = [p for p in found if p.form_id == "00"] or found
        judgement.answer, judgement.near = self.judge_forms(s, intended)
        return judgement

    @staticmethod
    def judge_forms(s, intended):
        """(正解ならその名前・ちがえば答えた名前, おしいの返事)。"""
        for pokemon in intended:
            if (pokemon.species, pokemon.form_id) in s.dexAnswers:
                return s.dexAnswers[(pokemon.species, pokemon.form_id)][1], None
        answered = {pokemon.species for pokemon in intended}
        species = {key[0] for key in s.dexAnswers}
        if answered & species:
            return intended[0].name, "おしいロ！ すがた（フォーム）が ちがうロ"
        if any(s.dexCatalog.related(one, other)
               for one in species for other in answered):
            return intended[0].name, "おしいロ！ 進化の前か後の ポケモンだロ"
        return intended[0].name, None

    def reveal(self, s):
        entry = s.dexEntries[0]
        s.quizEmbed.description = (
            f'{entry.text}\nこたえ: {",".join(s.ansList)}'
            f"\n作品: {entry.titles_label()}")
