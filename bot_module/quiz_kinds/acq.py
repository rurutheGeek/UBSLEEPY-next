# -*- coding: utf-8 -*-
# quiz_kinds/acq.py
"""ACクイズ（acq）: こうげきととくこうのどちらが高いかをボタンで答える。"""
import discord

from bot_module import func as ub
from bot_module.pokedex import get_pokedex

from .base import FINAL_STAGES, NO_POKEMON, Draft, PokemonKind

# ボタンの custom_id は acq_<答え>（cogs/quiz.py が接頭辞で受ける）
BUTTONS = (
    ("こうげき", discord.ButtonStyle.primary),
    ("とくこう", discord.ButtonStyle.primary),
    ("同値", discord.ButtonStyle.secondary),
)


class AttackQuiz(PokemonKind):

    async def build(self, s, embed, channel, voice_channel):
        qDatas = get_pokedex().random(FINAL_STAGES)
        if qDatas is None:
            await channel.send(NO_POKEMON)
            return None
        embed.title = "ACクイズ"
        embed.description = f"{qDatas.name} はこうげきととくこうどちらが高い?"
        embed.set_thumbnail(url=self.image_link(qDatas.name))

        view = discord.ui.View()
        for label, style in BUTTONS:
            view.add_item(
                discord.ui.Button(label=label, style=style, custom_id=f"acq_{label}"))
        return Draft(view=view, record=self.pokemon_record(qDatas))

    async def read_question(self, s):
        s.examText = s.quizEmbed.description.split(" ")[0]
        return True

    def answers(self, s):
        aData = ub.fetch_pokemon(s.examText)[0]
        if aData.atk == aData.spa:
            answer = "同値"
        elif aData.atk > aData.spa:
            answer = "こうげき"
        else:
            answer = "とくこう"
        return [answer], aData

    def reveal(self, s):
        s.quizEmbed.description = f"{ub.bss_to_text(s.ansZero)}\n"
        if s.ansList[0] == "同値":
            s.quizEmbed.description += f"{s.examText}はこうげきととくこうが同じ"
        else:
            s.quizEmbed.description += f"{s.examText}は{s.ansList[0]}の方が高い"
