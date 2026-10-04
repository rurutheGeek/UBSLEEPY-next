# -*- coding: utf-8 -*-
# func.py
from . import save
from .config import *
from .logging_setup import logger
from .normalize import format_text
from .pokedex import EVOLUTION_STAGES, Pokemon, get_pokedex

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pypinyin
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import japanize_matplotlib
import discord
import json

def output_log(logStr):
    """Botの動作ログを標準loggingへ出す
    Parameters:
    ----------
    logStr : str
      出力するログの文字列
    """
    logger.info(logStr)

def output_warning(logStr):
    """警告。Discordのログチャンネルへ送られる。"""
    logger.warning(logStr)

def output_error(logStr):
    """エラー。Discordのログチャンネルへ送られる。"""
    logger.error(logStr)

def fetch_pokemon(input: str) -> list[Pokemon]:
  '''ポケモン名から図鑑データを検索する
  Parameters:
  ----------
  input : str
    検索するポケモン名

  Returns:
  ----------
  list[Pokemon]
    見つかったポケモン。見つからなければ空のリスト。
  '''
  output_log(str(input)+"の図鑑データを検索します")
  found = get_pokedex().find(input)
  if not found:
    output_log(format_text(input)+"の図鑑データは見つかりませんでした")
  return found


def bss_to_text(values) -> str:
  '''ポケモンの図鑑データから種族値文字列を生成する
  Parameters:
  ----------
  values : Pokemon or list or pd.Series or pd.DataFrame
    種族値のリスト or Pokemon or 種族値のSeries or 種族値のDataFrame
  '''
  if isinstance(values, Pokemon):
    bss = list(values.stats)
  elif isinstance(values, list):
    bss = values
  elif isinstance(values, pd.Series):
    bss = [int(values['HP']), int(values['こうげき']), int(values['ぼうぎょ']), int(values['とくこう']), int(values['とくぼう']), int(values['すばやさ'])]
  elif isinstance(values, pd.DataFrame):
    bss = [int(values.iloc[0]['HP']), int(values.iloc[0]['こうげき']), int(values.iloc[0]['ぼうぎょ']), int(values.iloc[0]['とくこう']), int(values.iloc[0]['とくぼう']), int(values.iloc[0]['すばやさ'])]
  
  return f'{"-".join(map(str,bss))} 合計{sum(bss)}'


def pinyin_to_text(cw: str) -> str:
  '''中国語の文字からピンイン文字列を生成する
  Parameters:
  ----------
  cw : str
  中国語の文字
  
  Returns:
  ----------
  pinyin : str
  ピンイン文字列
  '''
  pinyins = []
  for pinyin in pypinyin.pinyin(cw, heteronym=True):
    if len(pinyin) == 1:
      pinyins.append(pinyin[0])
    else:
      heteronyms = "("
      for heteronym in pinyin:
        heteronyms += f'{heteronym},'
      pinyins.append(heteronyms[:-1] + ")")

  return " ".join(pinyins)
 

def generate_graph(bss: list[int], name=None) -> str:
    '''種族値グラフを生成する
    
    Parameters:
    ----------
    bss : list[int]
        種族値のリスト
    name : str, optional
        グラフに表示する名前
        
    Returns:
    ----------
    BSS_GRAPH_PATH : str
        生成したグラフのパス
    '''
    output_log(f"{'-'.join(map(str, bss))}の種族値グラフを生成します")
    
    # 値の準備
    values = [bss[0], bss[1], bss[2], bss[5], bss[4], bss[3]]  # HP, A, B, S, D, C の順
    labels = [f'HP{values[0]}', f'A{values[1]}', f'B{values[2]}', 
              f'S{values[3]}', f'D{values[4]}', f'C{values[5]}']
    
    # レーダーチャートのデータ準備
    radar_values = np.concatenate([values, [values[0]]])  # 多角形を閉じるため
    angles = np.linspace(0, 2 * np.pi, len(labels) + 1, endpoint=True)
    
    # メモリ軸の設定
    if max(values) < 150:
        rgrids = [0, 50, 100, 150]
    else:
        a = max(values) / 2
        rgrids = [0, a, 2 * a]
    
    # プロット領域の設定
    fig = plt.figure(facecolor="cornsilk")
    ax = fig.add_subplot(1, 1, 1, polar=True, facecolor="cornsilk")
    
    # レーダーチャートの描画
    ax.plot(angles, radar_values, color="midnightblue", alpha=0.4, linewidth=0.5)
    ax.fill(angles, radar_values, alpha=0.9, color="midnightblue")
    
    # チャートの装飾設定
    ax.set_thetagrids(angles[:-1] * 180 / np.pi, labels, fontweight="roman")
    ax.set_rgrids([])  # 円形の目盛線を消す
    ax.spines['polar'].set_visible(False)  # 一番外側の円を消す
    ax.set_theta_zero_location("N")  # 始点を上(北)に変更
    ax.set_theta_direction(-1)  # 時計回りに変更
    
    # グリッドラインの描画
    for grid_value in rgrids:
        grid_values = [grid_value] * (len(labels) + 1)
        ax.plot(angles, grid_values, color="gray", linewidth=0.5, alpha=0.3)
    
    # メモリ値の表示
    for t in rgrids:
        ax.text(x=0, y=t, s=t, fontweight="ultralight", alpha=0.1)
    
    # グラフの範囲とグリッド設定
    ax.set_rlim([min(rgrids), max(rgrids)])
    ax.grid(True, alpha=0.1)
    
    # タイトルの設定
    total_stats = sum(values)
    if name is not None:
        ax.set_title(f"{name}\n合計{total_stats}", pad=20, fontsize=15)
    else:
        ax.set_title(f"合計{total_stats}", pad=20, fontsize=15)
    
    # グラフの保存
    plt.tight_layout()
    fig.savefig(BSS_GRAPH_PATH, bbox_inches='tight')
    plt.close('all')
    
    output_log(f"種族値グラフ生成完了: {BSS_GRAPH_PATH}")
    return BSS_GRAPH_PATH


#レポートしたり参照する関数 ユーザーIDとレポのインデックスを渡す modifiは増減値
def report(userId, repoIndex: str, modifi: int, userName: str) -> int:
  '''レポートを行う
  Parameters:
  ----------
  userId : int
  ユーザーID
  repoIndex : str
  レポートのインデックス
  modifi : int
  増減値
  userName : str
  新規行を作るときに記録するユーザー名

  Returns:
  ----------
  int
  レポート後の値
  '''
  output_log(f"レポートを確認します: {userId} {repoIndex}")
  return save.report(userId, repoIndex, modifi, userName, REPORT_PATH)


#除外検索できるようにしたい 語頭のマイナスを検知,フラグを立てる
def make_filter_dict(values: list[str]) -> dict[str,str]:
  output_log("以下の項目でフィルタ辞書を生成します\n "+str(values))

  pokedex = get_pokedex()
  new_dict={}
  #valueがどのインデックスに該当するか検索
  for i in range(len(values)):
    if values[i] in EVOLUTION_STAGES:
      dictIndex='進化段階'
    elif values[i] in ['1','2','3','4','5','6','7','8','9']:
      dictIndex='初登場世代'
    elif values[i] in pokedex.regions():
      dictIndex='出身地'
    elif values[i] in pokedex.types():
      dictIndex='タイプ'
    elif values[i].upper().startswith(tuple(BASE_STATS_DICT.keys())):
      for key in BASE_STATS_DICT.keys():
        if values[i].upper().startswith(key):
          dictIndex = BASE_STATS_DICT[key]
          values[i] = values[i][len(key):]  # 数字の部分だけを抜き出す
          break
    elif values[i] in pokedex.abilities():
      dictIndex='特性'
    else:
      continue
      
    if dictIndex not in new_dict:
      new_dict[dictIndex] = []
      
    new_dict[dictIndex].append(values[i])
    
  output_log("以下のフィルタ辞書を生成しました\n "+str(new_dict))
  return new_dict

def attachment_file(file_path: str) -> discord.File:
  '''discordのファイルオブジェクトを生成する
  Parameters:
  ----------
  file_path : str
  元ファイルのパス

  Returns:
  ----------
  file : discord.File
  生成したファイルオブジェクト
  attachment_path : str
  添付ファイルのパス
  '''
  filename = f"attachedImage{os.path.splitext(file_path)[1]}"
  if not os.path.exists(file_path):
      file_path = NOTFOUND_IMAGE_PATH
  file = discord.File(file_path, filename=filename)
  attachment_path=f"attachment://{filename}"
  output_log(f"次のファイルを添付します: {file_path}")
  return file,attachment_path

def show_calendar(day: datetime = datetime.now(ZoneInfo("Asia/Tokyo"))) -> discord.Embed:
  calendarTitle = BALL_ICON
  
  if day.date() == datetime.now(ZoneInfo("Asia/Tokyo")).date():
    calendarTitle += f'{day.strftime("%Y/%m/%d")} ({WEAK_DICT[str(day.weekday())]}) 今日のできごと'
  else:
    calendarTitle += f'{day.strftime("%m/%d")}のできごと'

  history_df = pd.read_csv(POKECALENDAR_PATH, encoding="utf-8")
  history_df['日付'] = pd.to_datetime(history_df['日付'], format='%Y/%m/%d')
  matched_rows = history_df[history_df['日付'].dt.strftime('%m/%d') == day.strftime('%m/%d')].fillna('')

  thumbnailLink = ""
  if len(matched_rows) > 0 :
    calendarDescription = ""
    for index, row in matched_rows.iterrows():
      if row['プロパティ'] == '記念日':
        calendarDescription += f"> **{row['できごと']}**\n"
      else:
        calendarDescription += f"> **{row['日付'].year}年 {row['できごと']}**\nあれから{day.year - row['日付'].year}年\n"
      calendarDescription += f"関連リンク\n{row['関連リンク']}\n"
    if not (eventPokemon := matched_rows.iloc[0]["関連ポケモン"])=="":
      eventPokeData = fetch_pokemon(eventPokemon)
      if eventPokeData:
        thumbnailLink = f"{EX_SOURCE_LINK}art/{eventPokeData[0].image_number}.png"
  else:
    calendarDescription = "なんにもない すばらしい 一日"
    
  createdEmbed = discord.Embed(
    title=calendarTitle,
    color=0x7ED321,
    description=calendarDescription
  )
  createdEmbed.set_thumbnail(url=thumbnailLink)
  createdEmbed.set_footer(text="No.17 カレンダー")

  return createdEmbed



def show_senryu(unique: bool = False) -> discord.Embed:
  senryu_df = pd.read_csv(POKESENRYU_PATH)
  
  if unique:
    if (senryu_df['チェック'] == True).all():
      senryu_df['チェック'] = ''
    selectedSenryu = senryu_df[~(senryu_df['チェック']==True)].sample().fillna('')
    senryu_df.loc[selectedSenryu.index, 'チェック'] = True
    senryu_df.to_csv(POKESENRYU_PATH, index=False)
  else:
    selectedSenryu = senryu_df.sample().fillna('')

  createdEmbed = discord.Embed(
    title=f'{"今日の" if unique else ""}ポケモン川柳',
    color=0xF5A623,
    description=f'''```md
{selectedSenryu.iloc[0]['ポケモン川柳']}
*{selectedSenryu.iloc[0]['出典']} {selectedSenryu.iloc[0]['登場作品']}*```
{BALL_ICON}`みんなもポケモン ゲットじゃぞ!`'''
  )

  if not selectedSenryu.iloc[0]['登場ポケモン'] == '':
    senryuPokeData = fetch_pokemon(selectedSenryu.iloc[0]['登場ポケモン'])
    if senryuPokeData:
      createdEmbed.set_thumbnail(url=f"{EX_SOURCE_LINK}art/{senryuPokeData[0].image_number}.png")
    
  return createdEmbed

