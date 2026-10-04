# UBSLEEPY（-next）の実行イメージ。
#
# このリポジトリの中身をそのまま入れる。セーブデータ（save/・log/・config.json・
# resource/pokemon_senryu.csv・resource/image）はイメージに入れず、配備側で
# state から重ねる（stacks/ubsleepy-next の compose を参照）。
FROM python:3.13

WORKDIR /app

COPY setup/requirements.txt setup/requirements.txt
RUN pip install --no-cache-dir -r setup/requirements.txt

COPY . .

CMD ["python", "main.py"]
