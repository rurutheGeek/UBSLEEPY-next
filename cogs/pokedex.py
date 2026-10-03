# -*- coding: utf-8 -*-
# cogs/pokedex.py
"""ポケモン図鑑（/dex /comp /simil）と図鑑メッセージの操作。"""
import os

import discord
from discord.ext import commands
import jaconv
import numpy as np
from PIL import Image

import bot_module.config as cfg
import bot_module.embed as ub_embed
import bot_module.func as ub

GUILDS = [discord.Object(id=guild_id) for guild_id in cfg.GUILD_IDS]


class Pokedex(commands.Cog):
    """図鑑データの表示・比較・類似度ランキング。"""

    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="dex", description="ポケモンの図鑑データを表示します")
    @discord.app_commands.guilds(*GUILDS)
    @discord.app_commands.describe(name="表示したいポケモンのおなまえ")
    async def dex(self, interaction: discord.Interaction, name: str):
        ub.output_log("図鑑を実行します")
        await self.display_pokedex(interaction, name)

    async def display_pokedex(self, interaction, name, message=None):
        """ポケモンの図鑑データを表示する共通関数

        Parameters:
        ----------
        interaction : discord.Interaction
            インタラクションオブジェクト
        name : str
            表示するポケモン名
        message : discord.Message, optional
            更新する既存のメッセージ（ボタン操作時）
        """
        if (pokedata := ub.fetch_pokemon(name)) is not None:  # データが存在する場合は、図鑑データを返信
            pokedata = pokedata.fillna(" ")
            dexNumber = pokedata.iloc[0]['ぜんこくずかんナンバー']
            dexName = str(pokedata.iloc[0]['おなまえ'])
            dexIndexs = [pokedata.iloc[0]['インデックス1'], pokedata.iloc[0]['インデックス2'], pokedata.iloc[0]['インデックス3']]
            dexType1 = str(pokedata.iloc[0]['タイプ1'])
            dexType2 = str(pokedata.iloc[0]['タイプ2'])
            dexAbi1 = str(pokedata.iloc[0]['特性1'])
            dexAbi2 = str(pokedata.iloc[0]['特性2'])
            dexAbiH = str(pokedata.iloc[0]['隠れ特性'])
            dexH = int(pokedata.iloc[0]['HP'])
            dexA = int(pokedata.iloc[0]['こうげき'])
            dexB = int(pokedata.iloc[0]['ぼうぎょ'])
            dexC = int(pokedata.iloc[0]['とくこう'])
            dexD = int(pokedata.iloc[0]['とくぼう'])
            dexS = int(pokedata.iloc[0]['すばやさ'])
            dexSum = int(pokedata.iloc[0]['合計'])
            dexGen = str(pokedata.iloc[0]['初登場作品'])

            emoji = "🔴"

            # Embed作成
            dexEmbed = discord.Embed(
                title=f'{emoji}{dexName}の図鑑データ{emoji}',
                color=cfg.TYPE_COLOR_DICT.get(dexType1, 0xdcdcdc),
                description=f'''No.{dexNumber} {dexName} 出身: {dexGen}
タイプ: {dexType1}/{dexType2}
とくせい: {dexAbi1}/{dexAbi2}/{dexAbiH}
```
┌───┬───┬───┬───┬───┬───┰───┐
│ H │ A │ B │ C │ D │ S ┃Tot│
├───┼───┼───┼───┼───┼───╂───┤
│{dexH:3}-{dexA:3}-{dexB:3}-{dexC:3}-{dexD:3}-{dexS:3} {dexSum:3}│
└───┴───┴───┴───┴───┴───┸───┘
```
      ''',
                url=f'https://yakkun.com/sv/zukan/n{dexNumber}'
            )

            # サムネイル設定
            dexEmbed.set_thumbnail(url=f'{cfg.EX_SOURCE_LINK}art/{dexNumber}.png')

            # インデックス情報の追加
            aliases = []
            for dexIndex in dexIndexs:
                if not dexIndex == " ":
                    aliases.append(str(dexIndex))

            # 別名フィールドを追加
            if aliases:
                dexEmbed.add_field(name="登録済の別名", value=", ".join(aliases), inline=False)
            else:
                dexEmbed.add_field(name="登録済の別名", value="なし", inline=False)

            # 種族値グラフの生成と設定
            bss = [dexH, dexA, dexB, dexC, dexD, dexS]
            graph_path = ub.generate_graph(bss=bss, name=dexName)
            filename = f"basestats_{dexNumber}_{jaconv.kata2alphabet(jaconv.hira2kata(dexName)).lower()}.png"
            attach_graph = discord.File(graph_path, filename=filename)
            dexEmbed.set_image(url=f"attachment://{filename}")

            dexEmbed.set_footer(text=f'No.25 ポケモン図鑑 - {dexNumber}')

            current_dex_num = float(dexNumber)
            base_dex_num = int(current_dex_num)  # 小数点以下を切り捨てて基本図鑑番号を取得
            prev_dex_num = str(base_dex_num - 1)
            next_dex_num = str(base_dex_num + 1)

            # ナビゲーションボタンを持つViewの作成
            dex_view = discord.ui.View()

            # 同じ基本図鑑番号を持つポケモン（姿違い）を検索
            # 例: 58.0, 58.1 など同じ基本図鑑番号を持つポケモン
            form_pattern = f'^{base_dex_num}(\\.\\d+)?$'
            form_variants = cfg.GLOBAL_BRELOOM_DF[
                cfg.GLOBAL_BRELOOM_DF["ぜんこくずかんナンバー"].str.match(form_pattern)
            ]

            # 姿違いの選択肢がある場合はセレクトメニューを用意
            has_variants = len(form_variants) > 1

            # 姿違いセレクトメニューの追加（姿違いがある場合のみ）
            if has_variants:
                # 選択肢の作成
                form_select = discord.ui.Select(
                    placeholder="姿違いを選択",
                    custom_id=f"dex_form:{base_dex_num}",
                    options=[
                        discord.SelectOption(
                            label=row["おなまえ"],
                            value=row["ぜんこくずかんナンバー"],
                            default=row["ぜんこくずかんナンバー"] == dexNumber
                        ) for _, row in form_variants.iterrows()
                    ]
                )
                dex_view.add_item(form_select)

            # GLOBAL_BRELOOM_DFから一度のクエリで前後のポケモンを取得
            adjacent_pokemon = cfg.GLOBAL_BRELOOM_DF[
                cfg.GLOBAL_BRELOOM_DF["ぜんこくずかんナンバー"].isin([prev_dex_num, next_dex_num])
            ]

            # 前後のポケモンの存在確認と名前取得
            has_prev = False
            has_next = False
            prev_name = ""
            next_name = ""

            if not adjacent_pokemon.empty:
                for _, row in adjacent_pokemon.iterrows():
                    if row["ぜんこくずかんナンバー"] == prev_dex_num:
                        has_prev = True
                        prev_name = row["おなまえ"]
                    elif row["ぜんこくずかんナンバー"] == next_dex_num:
                        has_next = True
                        next_name = row["おなまえ"]

            # 前のポケモンへのボタン
            prev_button = discord.ui.Button(
                style=discord.ButtonStyle.primary,
                emoji="◀",
                label=prev_name,
                custom_id=f"dex_prev:{dexNumber}",
                disabled=not has_prev
            )
            dex_view.add_item(prev_button)

            # 次のポケモンへのボタン
            next_button = discord.ui.Button(
                style=discord.ButtonStyle.primary,
                emoji="▶",
                label=next_name,
                custom_id=f"dex_next:{dexNumber}",
                disabled=not has_next
            )
            dex_view.add_item(next_button)

            # 新規メッセージか既存メッセージの更新か
            if message is None:
                # 新規メッセージ
                await interaction.response.send_message(files=[attach_graph], embed=dexEmbed, view=dex_view)
            else:
                # 既存メッセージの更新
                try:
                    await message.edit(attachments=[attach_graph], embed=dexEmbed, view=dex_view)
                except discord.HTTPException:
                    # エラーが発生した場合は新規メッセージとして送信
                    channel = message.channel
                    await channel.send(files=[attach_graph], embed=dexEmbed, view=dex_view)

        else:  # データが存在しない場合は、エラーメッセージを返信
            ub.output_log("404 NotFound")
            if message is None:
                await interaction.response.send_message(embed=ub_embed.error_404(name))
            else:
                await message.edit(embed=ub_embed.error_404(name), attachments=[], view=None)

    @discord.app_commands.command(name="comp", description="2~6匹のポケモンの種族値を比較します")
    @discord.app_commands.guilds(*GUILDS)
    @discord.app_commands.describe(
        pokemon1="1匹目のポケモン",
        pokemon2="2匹目のポケモン",
        pokemon3="3匹目のポケモン (任意)",
        pokemon4="4匹目のポケモン (任意)",
        pokemon5="5匹目のポケモン (任意)",
        pokemon6="6匹目のポケモン (任意)"
    )
    async def comp(
        self,
        interaction: discord.Interaction,
        pokemon1: str,
        pokemon2: str,
        pokemon3: str = None,
        pokemon4: str = None,
        pokemon5: str = None,
        pokemon6: str = None
    ):
        # まず応答を遅延させる - これによりタイムアウトを防ぐ
        await interaction.response.defer()
        # 入力された全ポケモン名を配列にまとめる
        pokemon_names = [name for name in [pokemon1, pokemon2, pokemon3, pokemon4, pokemon5, pokemon6] if name]

        # ログメッセージの作成
        log_message = "ポケモンの種族値を比較します: " + " / ".join(pokemon_names)
        ub.output_log(log_message)

        # 各ポケモンのデータとBSSを格納する辞書
        pokemon_data = {}
        dexnum_list = []
        # 全ポケモンのデータ取得
        for name in pokemon_names:
            poke_data = ub.fetch_pokemon(name)
            if poke_data is None:
                ub.output_log(f"404 NotFound: {name}")
                await interaction.followup.send(embed=ub_embed.error_404(name))
                return

            poke_name = poke_data.iloc[0]['おなまえ']
            bss = [
                int(poke_data.iloc[0]['HP']),
                int(poke_data.iloc[0]['こうげき']),
                int(poke_data.iloc[0]['ぼうぎょ']),
                int(poke_data.iloc[0]['とくこう']),
                int(poke_data.iloc[0]['とくぼう']),
                int(poke_data.iloc[0]['すばやさ'])
            ]

            dexnum = poke_data.iloc[0]['ぜんこくずかんナンバー']
            dexnum_list.append(dexnum)

            pokemon_data[poke_name] = {
                'bss': bss,
                'data': poke_data
            }

        # 一時ファイルのパスを用意
        temp_paths = [f"save/temp{i}.png" for i in range(len(pokemon_data))]
        combined_img_path = "save/compared_graph.png"

        # 各ポケモンのグラフを生成
        images = []
        for i, (name, data) in enumerate(pokemon_data.items()):
            graph_path = ub.generate_graph(bss=data['bss'], name=name)
            img = Image.open(graph_path)
            img.save(temp_paths[i])
            img.close()
            img = Image.open(temp_paths[i])
            images.append(img)

        # 画像の合成方法を決定
        if len(images) <= 3:
            # 3枚以下なら横に並べる
            width = sum(img.width for img in images)
            height = max(img.height for img in images)
            combined_img = Image.new('RGB', (width, height), color=(255, 250, 227))
            x_offset = 0
            for img in images:
                combined_img.paste(img, (x_offset, 0))
                x_offset += img.width
        else:
            # 4-6枚の場合はグリッドレイアウトを使用
            rows = 2
            cols = (len(images) + 1) // 2  # 切り上げの除算で列数を計算

            # 1つの画像のサイズを取得
            img_width = images[0].width
            img_height = images[0].height

            # 合成画像のサイズを計算
            combined_width = img_width * cols
            combined_height = img_height * rows

            # 新しい画像を作成（背景色を設定）
            combined_img = Image.new('RGB', (combined_width, combined_height), color=(255, 250, 227))  # cornsilk色に近い背景色

            # 画像を配置
            for i, img in enumerate(images):
                row = i // cols
                col = i % cols
                x_offset = col * img_width
                y_offset = row * img_height
                combined_img.paste(img, (x_offset, y_offset))

        # 画像を閉じる
        for img in images:
            img.close()

        # 一時ファイルを削除
        for path in temp_paths:
            os.remove(path)

        # 合成画像を保存
        combined_img.save(combined_img_path)
        combined_img.close()

        # グラフ画像をdiscordに添付する
        #dexnumでファイル名を指定
        filename=f"compared_{'_'.join(dexnum_list)}.png"
        attach_image = discord.File(combined_img_path, filename=filename)

        # Embedの作成
        title_text = " と ".join([f"**{name}**" for name in pokemon_data.keys()])
        embed = discord.Embed(
            title=f"{title_text} の種族値を比較",
            color=0x00BFFF
        )

        # 各ポケモンの種族値情報をフィールドとして追加
        for name, data in pokemon_data.items():
            bss = data['bss']
            embed.add_field(
                name=f"{name}",
                value=f"{bss[0]}-{bss[1]}-{bss[2]}-{bss[3]}-{bss[4]}-{bss[5]} 合計{sum(bss)}",
                inline=True
            )

        # 合成画像をEmbedに設定
        embed.set_image(url=f"attachment://{filename}")
        embed.set_footer(text=f"{len(pokemon_data)}匹のポケモンを比較")

        # メッセージ送信（defer()を使用しているため、followup.sendを使用）
        await interaction.followup.send(
            files=[attach_image],
            embed=embed
        )

    @discord.app_commands.command(name="simil", description="指定したポケモンと似ている種族値のポケモンを表示します")
    @discord.app_commands.guilds(*GUILDS)
    @discord.app_commands.describe(
        name="基準となるポケモンのおなまえ",
        evolution="進化段階フィルター (auto:入力ポケモンと同じ, final:最終進化/進化しない, middle:中間進化/進化前, all:すべて)"
    )
    @discord.app_commands.choices(
        evolution=[
            discord.app_commands.Choice(name="入力ポケモンと同じ", value="auto"),
            discord.app_commands.Choice(name="最終進化/進化しない", value="final"),
            discord.app_commands.Choice(name="中間進化/進化前", value="middle"),
            discord.app_commands.Choice(name="すべて", value="all"),
        ]
    )
    async def simil(self, interaction: discord.Interaction, name: str, evolution: str = "auto"):
        # まず応答を遅延させる - これによりタイムアウトを防ぐ
        await interaction.response.defer()

        # 入力ポケモンのデータ取得
        base_pokemon = ub.fetch_pokemon(name)
        if base_pokemon is None:
            ub.output_log(f"404 NotFound: {name}")
            await interaction.followup.send(embed=ub_embed.error_404(name))
            return

        # 基準ポケモンの情報を取得
        base_name = base_pokemon.iloc[0]['おなまえ']
        base_dexnum = base_pokemon.iloc[0]['ぜんこくずかんナンバー']
        base_evolution = base_pokemon.iloc[0]['進化段階']
        base_bss = np.array([
            int(base_pokemon.iloc[0]['HP']),
            int(base_pokemon.iloc[0]['こうげき']),
            int(base_pokemon.iloc[0]['ぼうぎょ']),
            int(base_pokemon.iloc[0]['とくこう']),
            int(base_pokemon.iloc[0]['とくぼう']),
            int(base_pokemon.iloc[0]['すばやさ'])
        ])

        # 固定表示数
        limit = 20

        # 進化段階でフィルタリング
        if evolution == "auto":
            # 入力されたポケモンの進化段階に基づいてフィルタリング
            if base_evolution in ['最終進化', '進化しない']:
                filtered_df = cfg.GLOBAL_BRELOOM_DF[cfg.GLOBAL_BRELOOM_DF['進化段階'].isin(['最終進化', '進化しない'])]
                evolution_text = "最終進化または進化しない"
            else:  # 中間進化や進化前
                filtered_df = cfg.GLOBAL_BRELOOM_DF[cfg.GLOBAL_BRELOOM_DF['進化段階'].isin(['第一進化', '進化前'])]
                evolution_text = "中間進化または進化前"
        elif evolution == "final":
            filtered_df = cfg.GLOBAL_BRELOOM_DF[cfg.GLOBAL_BRELOOM_DF['進化段階'].isin(['最終進化', '進化しない'])]
            evolution_text = "最終進化または進化しない"
        elif evolution == "middle":
            filtered_df = cfg.GLOBAL_BRELOOM_DF[cfg.GLOBAL_BRELOOM_DF['進化段階'].isin(['第一進化', '進化前'])]
            evolution_text = "中間進化または進化前"
        else:  # "all"
            filtered_df = cfg.GLOBAL_BRELOOM_DF
            evolution_text = "すべての"

        ub.output_log(f"種族値類似度ランキングを実行します: {base_name} ({evolution_text}ポケモン上位{limit}匹)")

        # 全ポケモンとの類似度を計算
        similarity_data = []
        for _, row in filtered_df.iterrows():
            # 同じポケモンはスキップ
            if row['おなまえ'] == base_name:
                continue

            # 種族値を取得
            comp_bss = np.array([
                int(row['HP']),
                int(row['こうげき']),
                int(row['ぼうぎょ']),
                int(row['とくこう']),
                int(row['とくぼう']),
                int(row['すばやさ'])
            ])

            # ユークリッド距離で類似度を計算 (値が小さいほど似ている)
            distance = np.sqrt(np.sum((base_bss - comp_bss) ** 2))

            similarity_data.append({
                'name': row['おなまえ'],
                'dexnum': row['ぜんこくずかんナンバー'],
                'distance': distance,
                'bss': comp_bss,
                'evolution': row['進化段階']
            })

        # 距離でソート (小さい順 = 類似度が高い順)
        similarity_data.sort(key=lambda x: x['distance'])

        # 上位のポケモンを取得 (limitで指定された数まで)
        top_similar = similarity_data[:limit]

        # 画像表示用のポケモン (入力ポケモン + 上位5匹)
        display_pokemon = [{'name': base_name, 'dexnum': base_dexnum, 'bss': base_bss}]
        display_pokemon.extend(top_similar[:5])  # 上位5匹だけを画像表示対象に

        # 各ポケモンのグラフを生成
        temp_paths = [f"save/temp_simil_{i}.png" for i in range(len(display_pokemon))]
        combined_img_path = "save/compared_simil_graph.png"

        images = []
        for i, pokemon in enumerate(display_pokemon):
            if i == 0:
                graph_path = ub.generate_graph(bss=pokemon['bss'], name=pokemon['name'])
            else:
                graph_path = ub.generate_graph(bss=pokemon['bss'], name=f"{i}"+'位：'+pokemon['name'])
            img = Image.open(graph_path)
            img.save(temp_paths[i])
            img.close()
            img = Image.open(temp_paths[i])
            images.append(img)

        # 画像の合成（3×2のグリッドレイアウト）
        # すべての画像が同じサイズであると仮定
        img_width = images[0].width
        img_height = images[0].height

        # グリッドレイアウトの設定
        rows = 2
        cols = 3

        # 合成画像のサイズを計算
        combined_width = img_width * cols
        combined_height = img_height * rows

        # 新しい画像を作成（背景色を設定）
        combined_img = Image.new('RGB', (combined_width, combined_height), color=(255, 250, 227))

        # 画像を配置
        for i, img in enumerate(images):
            if i >= rows * cols:  # 最大6枚まで
                break
            row = i // cols
            col = i % cols
            x_offset = col * img_width
            y_offset = row * img_height
            combined_img.paste(img, (x_offset, y_offset))

        # 合成画像を保存
        combined_img.save(combined_img_path)
        combined_img.close()

        # 画像を閉じる
        for img in images:
            img.close()

        # 一時ファイルを削除
        for path in temp_paths:
            os.remove(path)

        # ファイル名の作成 (基準ポケモンの図鑑番号を含める)
        filename = f"similarity_{base_dexnum}_{jaconv.kata2alphabet(jaconv.hira2kata(base_name)).lower()}.png"
        attach_image = discord.File(combined_img_path, filename=filename)

        # Embedの作成
        embed = discord.Embed(
            title=f"**{base_name}** と似ている種族値のポケモン",
            description=f"{base_name}の種族値: {base_bss[0]}-{base_bss[1]}-{base_bss[2]}-{base_bss[3]}-{base_bss[4]}-{base_bss[5]} (合計: {sum(base_bss)})\n進化段階: {base_evolution}",
            color=0x9013FE
        )

        # 最大距離を用いて類似度を計算（パーセンテージ表示）
        max_possible_distance = np.sqrt(6 * (255 ** 2))  # 各ステータスが0と255の場合の理論上の最大距離

        # 類似ポケモンをリストアップ
        similarity_text = ""
        for i, pokemon in enumerate(top_similar):
            bss = pokemon['bss']
            total = sum(bss)
            distance = pokemon['distance']
            evo_stage = pokemon['evolution']

            # 距離から類似度を計算（100%に近いほど似ている）
            similarity_percentage = max(0, min(100, 100 * (1 - distance / max_possible_distance)))
            similarity_percentage = round(similarity_percentage, 2)

            # 上位5匹は太字で表示
            similarity_text += f"{i+1}. {pokemon['name']}  類似度:{similarity_percentage}% \n"

        embed.add_field(
            name=f"類似ランキング 1-20",
            value=similarity_text,
            inline=False
        )
        similarity_text = ""

        # 合成画像をEmbedに設定
        embed.set_image(url=f"attachment://{filename}")

        # フッターに検索条件を表示
        if evolution == "auto":
            evolution_desc = f"{base_name}と同じ進化段階({evolution_text})の"
        else:
            evolution_desc = f"{evolution_text}"

        embed.set_footer(text=f"{base_name}との種族値類似度ランキング)")

        # 結果を送信
        await interaction.followup.send(
            files=[attach_image],
            embed=embed
        )

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """図鑑の姿違いセレクトと、前後のポケモンボタンを処理する。"""
        data = interaction.data or {}
        custom_id = data.get("custom_id")
        if not custom_id:
            return

        if data.get("component_type") == 3 and custom_id.startswith("dex_form:"):
            base_dex_num = custom_id.split(":")[1]
            selected_form = data["values"][0]  # 選択された姿違いの図鑑番号

            # 選択された姿違いのポケモンデータを取得
            form_data = cfg.GLOBAL_BRELOOM_DF[cfg.GLOBAL_BRELOOM_DF["ぜんこくずかんナンバー"] == selected_form]

            if not form_data.empty:
                selected_name = form_data.iloc[0]["おなまえ"]

                # 応答を延期
                await interaction.response.defer()

                # 共通関数を使用して表示
                await self.display_pokedex(interaction, selected_name, interaction.message)
            else:
                await interaction.response.send_message("該当するポケモンが見つかりませんでした", ephemeral=True)

        elif data.get("component_type") == 2 and (
            custom_id.startswith("dex_prev:") or custom_id.startswith("dex_next:")
        ):
            ub.output_log(
                f'buttonが押されました\n {interaction.user.name}: {custom_id}'
            )
            current_number = custom_id.split(":")[1]

            if custom_id.startswith("dex_prev:"):
                # 前のポケモンを表示
                target_number = str(int(float(current_number)) - 1)
            else:
                # 次のポケモンを表示
                target_number = str(int(float(current_number)) + 1)

            # 目的のポケモンデータを取得
            target_data = cfg.GLOBAL_BRELOOM_DF[cfg.GLOBAL_BRELOOM_DF["ぜんこくずかんナンバー"] == target_number]

            if len(target_data) > 0:
                target_name = target_data.iloc[0]["おなまえ"]

                # 応答を延期
                await interaction.response.defer()

                # 共通関数を使用して表示
                await self.display_pokedex(interaction, target_name, interaction.message)
            else:
                await interaction.response.send_message("該当するポケモンが見つかりませんでした", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Pokedex(bot))