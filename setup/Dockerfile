# UBSLEEPY（-next）の実行イメージ。
#
# このリポジトリの中身をそのまま入れる。セーブデータ（save/・log/・config.json・
# resource/pokemon_senryu.csv・resource/image）はイメージに入れず、配備側で
# state から重ねる（stacks/ubsleepy-next の compose を参照）。
FROM python:3.13

# ボイスチャンネルでの音声再生にffmpegを使う（鳴き声クイズ）。
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY setup/requirements.txt setup/requirements.txt
RUN pip install --no-cache-dir -r setup/requirements.txt

COPY . .

CMD ["python", "main.py"]
