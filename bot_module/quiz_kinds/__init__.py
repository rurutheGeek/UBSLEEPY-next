# -*- coding: utf-8 -*-
# quiz_kinds/__init__.py
"""クイズの種別のクラスと、クイズ識別子（quizName）からの表。

識別子は投稿のフッター（No.26 ポケモンクイズ - <識別子>）・判定ログの種別に
そのまま使うので変えない。種別を足すときはクラスを作ってここへ登録する。
"""
from .acq import AttackQuiz
from .base import QuizKind
from .bq import StatsQuiz
from .cryq import CryQuiz
from .dexq import DexTextQuiz
from .introq import IntroQuiz
from .noq import NumberQuiz
from .translate import (
    ChineseToJapaneseQuiz, EnglishToJapaneseQuiz, JapaneseToEnglishQuiz)

KINDS = {
    "bq": StatsQuiz,
    "acq": AttackQuiz,
    "etojq": EnglishToJapaneseQuiz,
    "jtoeq": JapaneseToEnglishQuiz,
    "ctojq": ChineseToJapaneseQuiz,
    "cryq": CryQuiz,
    "dexq": DexTextQuiz,
    "noq": NumberQuiz,
    "introq": IntroQuiz,
}


def kind_for(quiz_name) -> QuizKind:
    """識別子の種別。知らない識別子は、警告を出して何もしない種別。"""
    return KINDS.get(quiz_name, QuizKind)(quiz_name)
