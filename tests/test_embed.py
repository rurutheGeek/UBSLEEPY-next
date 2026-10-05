# -*- coding: utf-8 -*-
# tests/test_embed.py
from datetime import datetime

import bot_module.config  # noqa: F401  設定を読み込むため
from bot_module import embed as ub_embed


def test_balance_with_no_ranking():
    embed = ub_embed.balance(
        userName="debug",
        pocketMoney=0,
        numOfPeople=100,
        userRank=0,
        rank_list=[],
        sendTime=datetime(2026, 1, 1),
        authorPath="",
    )

    assert embed.title == "おこづかい銀行"
    ranking = next(field for field in embed.fields if "ランキング" in field.name)
    assert "まだ ランキングは ないみたい" in ranking.value


def test_balance_lists_fewer_than_five():
    embed = ub_embed.balance(
        userName="debug",
        pocketMoney=100,
        numOfPeople=100,
        userRank=1,
        rank_list=[["1", 100, 1], ["2", 50, 2]],
        sendTime=datetime(2026, 1, 1),
        authorPath="",
    )

    ranking = next(field for field in embed.fields if "ランキング" in field.name)
    assert "<@!1>" in ranking.value
    assert "<@!2>" in ranking.value
