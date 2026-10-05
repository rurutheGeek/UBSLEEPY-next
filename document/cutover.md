# 本番切替手順（UBSLEEPY → UBSLEEPY-next）

## 現状
- 本番（ポーガクインドリームワールド）のセーブデータは、いまも `save/report.csv`（CSV）に保存されている
- `ubsleepy` DB には 2026/10/04 にCSVを取り込んだスナップショットがある（以降の更新はCSV側だけ）
- 新Bot（UBSLEEPY-next）は `ubsleepy` DB を使う。初回接続時にスキーマを guild_id 付きへ自動移行する

## 切替の流れ
1. 旧Botを停止する（CSVへの書き込みを止める）
   - `sudo bash -c 'cd /opt/ubsleepy && python3 manage.py down'`
2. バックアップを取る
   - CSV: `sudo cp /srv/ubsleepy/state/save/report.csv /srv/ubsleepy/state/save/report.csv.bak-YYYYMMDD`
   - DB: `sudo docker exec -e PGPASSWORD=... pkdb-db-1 pg_dump -U ubsleepy_writer -d ubsleepy -Fc > /srv/ubsleepy/state/save/ubsleepy-YYYYMMDD.dump`
3. 最新CSVをDBへ取り込む（新イメージを一回だけ実行。初回接続でスキーマ移行も走る）
   ```bash
   sudo docker run --rm \
     -e UBSLEEPY_DB_PASSWORD=... \
     -v /srv/ubsleepy/state/save:/app/save \
     -v /srv/ubsleepy/state/config.json:/app/config.json \
     ghcr.io/ruruthegeek/ubsleepy-next@sha256:... \
     python -m bot_module.save save/report.csv --guild-id 1067125843647791114
   ```
4. 新Bot（UBSLEEPY-next）を本番へ配備して起動する
5. 動作確認: `/pocketmoney`・IDくじ・クイズ戦績をCSVと突き合わせる
6. 旧Botは再起動しない（戻す場合は手順2のバックアップからリストア）

## 注意
- 新旧のBotを同時に動かさない。移行後は旧コードのSQL（guild_idなし）が失敗する
- 移行後はDBが正。CSVは更新されない（バックアップとして残す）
- テスト環境（ubsleepy_test）は別DBなので、本番データと混ざらない
