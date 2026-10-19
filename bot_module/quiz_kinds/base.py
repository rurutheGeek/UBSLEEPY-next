# -*- coding: utf-8 -*-
# quiz_kinds/base.py
"""クイズの種別の土台。

種別ごとに違う所（出題の中身・問題文の取り出し・正答リスト・ヒント・判定のゆれ・
開示の書き方・出題ログ）を、種別のクラスが受け持つ。共通の流れ（出題 → 回答受付 →
判定 → 開示 → ログ → 連続出題）は bot_module.quiz_session.QuizSession にある。

種別のクラスは状態を持たず、メソッドはセッション（QuizSession）を受け取って、
その属性（examText・ansList・ansZero など）を読み書きする。
"""
from dataclasses import dataclass, field
import random
import re

import bot_module.config as cfg
from bot_module import func as ub
from bot_module.pokedex import get_pokedex

# 条件に合うポケモンがいないときの返事
NO_POKEMON = "現在の出題条件に合うポケモンがいません"
# 投稿から答えを復元できないときの返事
LOST_ANSWER = "この問題の答えが分からなくなりました。もう一度 /q で出題してください"
# 最終進化と進化しないポケモン（ACクイズ・翻訳クイズの出題範囲）
FINAL_STAGES = {"進化段階": ["最終進化", "進化しない"]}


def pokemon_id(pokemon) -> str:
    """判定ログ用のポケモンのID（図鑑番号-フォーム）。"""
    return f"{pokemon.ndex_number}-{pokemon.form_id}"


@dataclass
class Draft:
    """出題する投稿の中身と、出題ログに残すもの。"""
    content: str | None = None
    file: object = None
    view: object = None
    voice_path: object = None  # ボイスチャンネルで流す音源（鳴き声・イントロ）
    record: tuple | None = None  # 出題ログの (question, answer, answer_id)。None は残さない
    extra: dict = field(default_factory=dict)  # 種別が出題ログの条件に使う値


@dataclass
class Judgement:
    """回答の読み取り結果（正誤の前）。"""
    answer: str  # 正答リストと照らし合わせる答え
    pokemon: object = None  # 回答のポケモン（判定ログの input_id）
    near: str | None = None  # 「おしい」の返事（誤答でも戦績に数えない）
    unrecognized: str | None = None  # 答えとして読めないときの返事（戦績に数えない）
    detail: str | None = None  # 判定ログの detail（None なら「おしい」かどうかで決める）


class QuizKind:
    """クイズの種別。既定は知らない種別のふるまい（警告を出して何もしない）。"""

    def __init__(self, name):
        self.name = name  # クイズ識別子（投稿のフッター・判定ログの種別）

    def variant(self, s) -> str:
        """判定の分かれ目に使う種別。出し方で分かれる種別は上書きする。"""
        return self.name

    # --- 出題 ---

    async def build(self, s, embed, channel, voice_channel) -> Draft | None:
        """出題の中身を作り、embed を書く。出題できないときは返事をして None。"""
        ub.output_warning(f"不明なクイズ識別子(post): {self.name}")
        return None

    def conditions(self, s, draft) -> dict:
        """出題ログに残す、種別ごとの出題条件（連続出題のほか）。"""
        return {}

    # --- 回答受付 ---

    def restore(self, s):
        """取得し直した投稿から、回答を受ける前に戻しておくもの。"""

    def hint_words(self, s) -> list:
        """ヒントとして受ける言葉。"""
        return []

    async def read_question(self, s) -> bool:
        """投稿から問題文（s.examText）を取り出す。復元できなければ返事をして False。"""
        return True

    def answers(self, s):
        """(正答のリスト, 0番目の正答のデータ)。"""
        ub.output_warning(f"不明なクイズ識別子(answers): {self.name}")
        return [], None

    def answer_id(self, s) -> str:
        """判定ログの正解のID。"""
        return pokemon_id(s.ansZero)

    # --- 判定 ---

    async def judge(self, s) -> bool:
        """判定から記録・開示までを種別が自分で行うなら、行って True。

        既定は False（interpret で読み取り、QuizSession が判定する）。
        """
        return False

    def interpret(self, s) -> Judgement:
        """回答を読み取る。"""
        return Judgement(answer=s.ansText)

    async def after_wrong(self, s, judgement):
        """誤答（おしい・読めないを除く）に添える返事。"""

    def giveup_answer(self, s) -> str:
        """ギブアップの返事で見せる答え。"""
        return s.ansList[0]

    # --- ヒント ---

    async def hint_index(self, s):
        """出すヒントの項目。出さないときは None（返事が要るならここで返す）。"""
        ub.output_warning(f"不明なクイズ識別子(hint): {self.name}")
        return None

    # --- 開示 ---

    def reveal(self, s):
        """開示で s.quizEmbed の本文を書き換える。"""

    def image_link(self, search_word=None) -> str:
        """サムネイルの画像。名前が無ければ (?) マーク。"""
        ub.output_log(f"{self.name}: 画像リンク生成を実行")
        link = f"{cfg.EX_SOURCE_LINK}Decamark.png"  # デフォルトは(?)マーク
        if search_word is not None:
            if self.shows_image():
                displayImage = ub.fetch_pokemon(search_word)
                if displayImage:  # 回答ポケモンが発見できた場合
                    link = f"{cfg.EX_SOURCE_LINK}art/{displayImage[0].image_number}.png"
            elif self.shows_image() is None:
                ub.output_warning(f"不明なクイズ識別子(imageLink): {self.name}")
        return link

    def shows_image(self):
        """答えのポケモンの画像を出すか。None は知らない種別。"""
        return None

    # --- ログ ---

    def log_question(self, s, exAns):
        """判定ログの (question, answer)。"""
        return s.examText, exAns


class PokemonKind(QuizKind):
    """答えにポケモンの画像を出す種別。"""

    def shows_image(self):
        return True

    def random_with(self, filter_dict, field):
        """条件に合うポケモンから、指定の項目を持つ1匹をランダムに選ぶ。"""
        candidates = [
            p for p in get_pokedex().filter(filter_dict) if getattr(p, field)
        ]
        if not candidates:
            ub.output_error(f"{self.name}: 出題条件に合うポケモンがいません")
            return None
        return random.choice(candidates)

    @staticmethod
    def pokemon_record(pokemon, question=None):
        """出題ログの (question, answer, answer_id)。question の既定はポケモンの名前。"""
        return (pokemon.name if question is None else question,
                pokemon.name, pokemon_id(pokemon))


# ポケモンの名前で答える種別のヒント（基本の言葉）
POKEMON_HINT_WORDS = [
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
# 「ヒント」で出す項目
POKEMON_HINT_INDEXES = [
    "タイプ1",
    "タイプ2",
    "特性1",
    "特性2",
    "隠れ特性",
    "出身地",
    "分類",
    "初登場作品",
]


class NameAnswerKind(PokemonKind):
    """ポケモンの名前で答え、ポケモンのデータからヒントを出す種別。"""

    def hint_words(self, s):
        return POKEMON_HINT_WORDS

    def interpret(self, s):
        found = ub.fetch_pokemon(s.ansText)
        if not found:
            return Judgement(
                answer=s.ansText,
                unrecognized=f"{s.ansText} は図鑑に登録されていません")
        # 同じ名前で何匹も当たるとき（「くさきのミノ」はミノムッチにも
        # ミノマダムにもある）は、正解に入っているほうで判定する
        pokemon = next((p for p in found if p.name in s.ansList), found[0])
        return self.refine(s, Judgement(answer=pokemon.name, pokemon=pokemon), found)

    def refine(self, s, judgement, found):
        """名前で引けた回答の判定を、種別ごとに直す。"""
        return judgement

    async def hint_index(self, s):
        pokemon = s.ansZero
        fields = s.quizEmbed.fields
        if s.ansText == "ヒント":  # まだ出ていないヒントからランダムにヒントを出す
            alreadyHints = [field.name for field in fields]  # 既出のヒントの一覧
            stillHints = [
                x
                for x in POKEMON_HINT_INDEXES
                if x not in alreadyHints
                and pokemon.hint_value(x) is not None
            ]  # 未出のヒントの一覧（値が無いものは出さない）
            if stillHints:
                return random.choice(stillHints)
            shownHints = [
                x
                for x in alreadyHints
                if pokemon.hint_value(x) is not None
            ]
            if not shownHints:
                await s.rm.reply("これ以上 出せるヒントが ないロ")
                return None
            return random.choice(shownHints)

        if s.ansText in ["タイプ"]:
            if pokemon.type_1 and not any(field.name == "タイプ1" for field in fields):
                return "タイプ1"
            if pokemon.type_2 and not any(field.name == "タイプ2" for field in fields):
                return "タイプ2"
            await s.rm.reply(
                f"タイプは{pokemon.type_1 or 'なし'}/{pokemon.type_2 or 'なし'}です"
            )
            return None

        if s.ansText in ["特性", "トクセイ"]:
            if pokemon.ability_1 and not any(field.name == "特性1" for field in fields):
                return "特性1"
            if pokemon.ability_2 and not any(field.name == "特性2" for field in fields):
                return "特性2"
            if pokemon.ability_h and not any(field.name == "隠れ特性" for field in fields):
                return "隠れ特性"
            await s.rm.reply(
                f"とくせいは{pokemon.ability_1 or 'なし'}/{pokemon.ability_2 or 'なし'}/{pokemon.ability_h or 'なし'}です"
            )
            return None

        if s.ansText in ["地方", "チホウ"]:
            return "出身地"
        if s.ansText in ["分類", "ブンルイ"]:
            return "分類"
        if s.ansText in ["作品", "サクヒン"]:
            return "初登場作品"
        if s.ansText in ["語源", "ゴゲン"]:
            return "英語名由来"
        return None


def arrow_question(description) -> str:
    """「<問題> -> [?]」の形の問題文から <問題> を取り出す。"""
    return re.findall(r"^(.+)\s->", description)[0]


def arrow_reveal(s):
    """「<問題> -> [<答え>]」の形で開示する。"""
    s.quizEmbed.description = f"{s.examText} -> [{s.ansList[0]}]"
