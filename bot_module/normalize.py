# -*- coding: utf-8 -*-
# normalize.py
# 表記ゆれの正規化をここに集める。Discord・設定・データベースに依存しない。
import jaconv


def format_text(input: str) -> str:
    """テキストの整形(あｱＡa>アアAA)を行う

    Parameters:
    ----------
    input : str
      変換元テキスト

    Returns:
    ----------
    fixed : str
      変換後テキスト
    """
    fixed = input
    # ひらがなをカタカナに変換
    fixed = jaconv.hira2kata(fixed)
    # 半角カタカナを全角カタカナに変換
    fixed = jaconv.h2z(fixed)
    # 全角英数字を半角英数字に変換
    fixed = jaconv.z2h(fixed, kana=False, ascii=True, digit=True)
    # 英字を大文字に変換
    fixed = fixed.upper()

    return fixed