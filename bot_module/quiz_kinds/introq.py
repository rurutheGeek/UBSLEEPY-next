# -*- coding: utf-8 -*-
# quiz_kinds/introq.py
"""イントロクイズ（introq）: 曲のイントロから「作品の略称＋戦う相手」を当てる。

判定は bot_module.intro にある。答え（曲）は添付ファイル名から引き直す。
"""
import secrets

import discord

from bot_module import intro

from .base import LOST_ANSWER, Draft, Judgement, QuizKind
from .cryq import CRY_NONCE_BYTES, replay_button_view

# 聞き返し（戦績に数えない）になる判定
ASK_AGAIN = (intro.AMBIGUOUS, intro.AMBIGUOUS_SONG, intro.PARTIAL, intro.UNKNOWN)


def with_work(track) -> str:
    """曲名だけでは作品が分からないので、作品まで書く。"""
    return track.title + (f"（{track.work}）" if track.work else "")


class IntroQuiz(QuizKind):

    def shows_image(self):
        return False  # イントロクイズは画像を出さない

    async def build(self, s, embed, channel, voice_channel):
        track = intro.random_track(
            s.state.intro_works, s.state.intro_categories, s.state.intro_secret)
        if track is None:
            await channel.send(
                "出題条件に合う曲がありません"
                "（`/introdata` で条件を確認、リセットで既定に戻せます）")
            return None
        embed.title = "イントロクイズ"
        view = None
        # 戦闘曲に限らない言い方にする（フィールド曲なども同じ文で出す）
        if voice_channel is not None:
            embed.description = "イントロをボイスチャンネルで流します。"
            view = replay_button_view()
        else:
            embed.description = "添付のイントロを聞いて、"
        embed.description += (
            "何の曲か当てよう\n"
            "答え方: 作品の略称＋曲の中身（戦う相手・場所など）\n"
            "例: `BWシロナ` `DP野生` `SV四天王` `剣盾ジムリーダー`\n"
            "`ヒント` で作品が分かる　あきらめる: `ギブ`")
        file = discord.File(
            str(track.path),
            filename=intro.intro_filename(
                track.id, secrets.token_hex(CRY_NONCE_BYTES)))
        answer = with_work(track)
        return Draft(file=file, view=view, voice_path=track.path,
                     record=(answer, answer, track.id))

    def conditions(self, s, draft):
        return {
            "作品": list(s.state.intro_works),
            "区分": list(s.state.intro_categories),
            "シークレット": s.state.intro_secret,
        }

    def hint_words(self, s):
        return ["ヒント", "作品", "サクヒン"]

    async def read_question(self, s):
        s.track = intro.track_from_message(s.qm)
        if s.track is None:
            await s.rm.reply(LOST_ANSWER)
            return False
        s.examText = s.track.title
        return True

    def answers(self, s):
        return [s.track.title], s.track

    def answer_id(self, s):
        return s.ansZero.id

    def interpret(self, s):
        # 「略称＋戦う相手」か、1作品にしか無い言い方なら正解（対応リストで照合）
        verdict = intro.judge(s.track, s.ansText)
        judgement = Judgement(
            answer=s.ansList[0] if verdict == intro.CORRECT else s.ansText,
            detail=verdict)
        if verdict in ASK_AGAIN:
            judgement.unrecognized = self.ask_again(s, verdict)
        return judgement

    @staticmethod
    def ask_again(s, verdict) -> str:
        if verdict == intro.AMBIGUOUS:
            return ("ほかの作品にも ある曲だロ。作品の略称もつけて答えてね"
                    "（`略称＋相手` のかたち。例: `BWシロナ`）")
        if verdict == intro.PARTIAL:
            return "おしいロ！ もう少し くわしく答えてね"
        if verdict == intro.AMBIGUOUS_SONG:
            axes = intro.distinguishers(s.track, s.ansText)
            if axes:
                return ("その相手の曲は いくつかあるロ。"
                        f"{'も、'.join(axes)}も つけて答えてね")
            titles = "／".join(
                f"`{title}`" for title in intro.candidates(s.track, s.ansText))
            return (f"その相手の曲は いくつかあるロ（{titles}）。"
                    "どれか分かるように答えてね（`決戦`・地方名などをつける）")
        return f"{s.ansText} は曲リストにありません"

    def giveup_answer(self, s):
        answer = s.ansList[0]
        if s.ansZero.work:
            answer += f"（{s.ansZero.work}）"  # 曲名だけでは作品が分からない
        return answer

    async def hint_index(self, s):
        return "作品"  # ヒントは作品だけ

    def reveal(self, s):
        s.quizEmbed.description = (
            f"こたえ: {s.ansList[0]}"
            + (f"（{s.ansZero.work}）" if s.ansZero.work else ''))
        appears = "、".join(work for work, _ in s.ansZero.appearances)
        if appears:  # 再録・流用で流れるほかの作品
            s.quizEmbed.description += f"\nほかに流れる作品: {appears}"

    def log_question(self, s, exAns):
        if s.ansZero.work:
            # 同じ曲名がいくつもの作品にあるので、作品まで書いて区別する
            question = f"{s.examText}（{s.ansZero.work}）"
            return question, question
        return s.examText, exAns
