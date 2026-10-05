# -*- coding: utf-8 -*-
# embed.py
import copy
import json
from datetime import datetime
from functools import lru_cache

import discord

from .config import BALL_ICON, EX_SOURCE_LINK

ERROR_EMBEDS_PATH = "document/error_embeds.json"


def balance(userName: str, pocketMoney: int,numOfPeople:int,userRank: int,rank_list: list = [], sendTime: datetime = None,authorPath: str="") -> discord.Embed:
    '''残高照会Embedを生成する
    Parameters:
    ----------
        name : str
            ユーザー名
        pocketMoney : int
            おこづかい残高
        numOfPeople : int
            ユーザー数
        rank : int
            ユーザーの順位
        rank_list : list
            ユーザーランキングリスト
        sendTime : datetime
            メッセージ送信時刻
        authorPath : str
            アイコン画像パス
    '''
    embed = discord.Embed(
        title="おこづかい銀行",
        color=0x00FF00,
        description=f"``` {userName} おかえりなさい! しっかり やってる みたいね ```\n"\
            f"{BALL_ICON}**あずけている きんがく    {pocketMoney}円**\n\n　"\
    )
    rankMsg=""
    if not rank_list:
        rankMsg="まだ ランキングは ないみたい\n"
    for entry in rank_list[:5]:
        id=entry[0]
        money=entry[1]
        rank=entry[2]
        rankMsg+=f"#{rank:.0f}  I <@!{id}> "
        rankMsg+='\N{Military Medal}' if rank == 1 else ''
        rankMsg+=f"`{money}円`\n"

    embed.add_field(name=f"おこづかいランキング ({sendTime.strftime('%Y/%m/%d %H:%M:%S')}現在)", value=rankMsg+f"\nあなたの順位: {numOfPeople}人中 {userRank}位\n", inline=False)
    embed.add_field(name="",value="``` たいせつに あずかっておくから あなたも しっかりね! ```", inline=False)
    if authorPath:
        embed.set_author(name="おかあさん",
            icon_url=authorPath
        )
    embed.set_footer(text="No.x おこづかい銀行")
    return embed


@lru_cache(maxsize=1)
def _error_template() -> dict:
    """エラーEmbedの雛形。ファイルは起動中に変わらない前提で一度だけ読む。"""
    with open(ERROR_EMBEDS_PATH, "r", encoding="utf-8") as template_file:
        return json.load(template_file)["error_404"]


def error_404(name: str) -> discord.Embed:
    # 雛形は書き換えないよう複製してから差し込む
    error_data = copy.deepcopy(_error_template())
    error_data["description"] = error_data["description"].format(name=name)
    error_data["thumbnail"]["url"] = error_data["thumbnail"]["url"].format(EX_SOURCE_LINK=EX_SOURCE_LINK)
    return discord.Embed.from_dict(error_data)
