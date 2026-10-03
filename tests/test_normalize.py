# -*- coding: utf-8 -*-
# tests/test_normalize.py
import pytest

from bot_module.normalize import format_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ぴかちゅう", "ピカチュウ"),
        ("ピカチュウ", "ピカチュウ"),
        ("ﾋﾟｶﾁｭｳ", "ピカチュウ"),
        ("pikachu", "PIKACHU"),
        ("Pikachu", "PIKACHU"),
        ("Ｐｉｋａｃｈｕ", "PIKACHU"),
        ("１２３", "123"),
        ("ﾋﾟｶﾁｭｳだよ", "ピカチュウダヨ"),
        ("がぶりあす", "ガブリアス"),
        ("メガリザードンX", "メガリザードンX"),
        ("", ""),
    ],
)
def test_format_text(raw, expected):
    assert format_text(raw) == expected