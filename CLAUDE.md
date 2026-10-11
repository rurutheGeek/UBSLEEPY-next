# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

ポケモン機能（図鑑・クイズ・検索・日替わり投稿）を持つ Discord Bot。Python 3.13 / discord.py 2.7。コード内のコメント・コミットメッセージ・ユーザー向け文言はすべて日本語。

## コマンド

```bash
pip install -r setup/requirements.txt -r setup/requirements-dev.txt

ruff check .                                   # lint（CIと同じ。構文エラーと未定義名だけを見る設定）
python -m pytest                               # 全テスト
python -m pytest tests/test_intro.py           # 1ファイル
python -m pytest tests/test_intro.py -k judge  # 名前で絞る

python main.py          # 起動（.env の DISCORD_TOKEN が必要）
python main.py debug    # debugモード: 開発用ギルドの設定を使い、コマンドもそのギルドにだけ登録

python debug_cli.py dex リザードン   # Discordへ接続せず、本物のCogを偽のDiscordオブジェクトで呼ぶ
python debug_cli.py                  # 対話モード（q bq → answer / hint / give）
```

`python` が無い環境では `python3` を使う。

- CI（`.github/workflows/ci.yml`）は `ruff check .` と `python -m pytest` を走らせる。PRの前に両方通す。
- main へマージされると `image.yml` が `setup/Dockerfile` からイメージを作り、`ghcr.io/ruruthegeek/ubsleepy-next:<コミットID>` へ出す。配備（apps-01）は別リポジトリ shake-cloud の `stacks/ubsleepy-next` が digest 固定で行い、このリポジトリではビルド済みイメージを取るだけ。
- `debug_cli.py` は既定でセーブの増減を書かない（`--save` で書く）。読み取りは本物の保存先を見る。

## 構成

`main.py` は起動と Cog の読み込みだけ。機能は `cogs/`（Discord とのやり取り）と `bot_module/`（ロジック・データ）に分かれる。

### 設定は3層

1. `bot_module/settings.py` — `config.json`（無ければ `document/default_config.json`）を型つきの `Settings` に読む。Discord・pandas に依存しない。
2. `bot_module/config.py` — 旧コード向けの互換レイヤー。`Settings` の値を従来のグローバル名（`QUIZ_CHANNEL_ID` など）で出す。`DEBUG_MODE` は `sys.argv[1] == "debug"` で決まる。`func.py` は `from .config import *` している。
3. `bot_module/guild_settings.py` — サーバーごとの値（チャンネルID・ロールID）。**DB（`/channel`・`/role` で保存）→ config.json の既定値 → 0** の順で解決し、プロセス内でキャッシュする。サーバーごとに変わる値は `cfg.XXX_CHANNEL_ID` ではなく `guild_settings.setting(guild_id, key)` で取る。

### データの出どころ（どちらも環境変数が無ければCSVへ落ちる）

- **図鑑**（`bot_module/pokedex.py`）: `PKDB_PASSWORD` があれば pkdb（PostgreSQL、読み取り専用）から起動時に一度だけ読み、`Pokemon` レコードとしてメモリに置く。無いとき・接続失敗時は `resource/pokemon_database.csv`。`get_pokedex()` で取り、コマンドごとのDBアクセスはしない。
- **セーブ**（`bot_module/save.py`）: `UBSLEEPY_DB_PASSWORD` があれば `ubsleepy` DB へ1件ずつ upsert。無いときは `save/report.csv`（ローカル開発・テスト専用）。セーブは**全サーバー共通**で、DBの `guild_id` 列は固定値 `SAVE_SCOPE = 0`。ギルドごとの設定（`guild_setting` テーブル）だけが本当のギルドIDを持つ。スキーマは初回接続時に自動で作成・移行する。

### コマンドの登録

- スラッシュコマンドには `@discord.app_commands.command` の下に `@scoped`（`bot_module/command_scope.py`）を付ける。debug のときは開発用ギルドにだけ登録される。
- 通常起動では、Bot が居るサーバーそれぞれへ**ギルドコマンドとして**登録する（再起動ですぐ反映。あとから追加されたサーバーへは `on_guild_join` で登録）。グローバルには登録せず、起動のたびに空にする（両方あると同じコマンドが2つずつ並ぶ）。DM ではコマンドは出ない。
- コマンドを足したら `tests/test_cogs.py` の `EXPECTED_COMMANDS` と `cogs/help.py` の説明も更新する。Cog を足したら `main.py` と `tests/test_cogs.py` の `COGS` の両方へ。
- `/bqdata`・`/crydata`・`/introdata` はスラッシュコマンドではなく、`cogs/quiz.py` の `on_message` が拾うテキストコマンド（`cogs/help.py` の `TEXT_COMMANDS` に説明がある）。

### ボタン・セレクトは `on_interaction` で受ける

`discord.ui.View` のコールバックではなく、各 Cog の `on_interaction` リスナーが `custom_id` の接頭辞（`dex_`・`search_`・`acq_`・`lotoIdButton:` など）で振り分ける。必要な値は `custom_id` に埋め込むので、Bot を再起動しても古い投稿のボタンが動く。新しいボタンもこの形に合わせる。

### クイズ

- `cogs/quiz.py` の Cog が `QuizState`（出題条件・連続出題モードなど。再起動でリセット）を持ち、`bot_module/quiz_session.py` の `QuizSession` が出題・回答受付・判定・開示を行う。
- 出題中のクイズはメモリに持たず、**クイズの投稿そのものから復元する**。Embed のフッター `No.26 ポケモンクイズ - <種別>` でクイズの投稿と種別を見分け、開示が済むと末尾に `(done)` が付く。回答はクイズへの返信か、チャンネルにそのまま書かれた名前（直近10件から未回答のクイズを探す）で受ける。鳴き声・イントロは添付ファイル名が `cry-<nonce>-<ハッシュ>.ogg` で、ハッシュに答えを混ぜてある（ファイル名から答えは読めないが、候補と照合すれば逆算できる）。
- 図鑑説明クイズ（`dexq`、`bot_module/dex_text.py`）は、pkdb の `pokemon_pokedex_text`（説明文）と `pokemon_evolution`（進化のつながり）を初回に一度だけ読む（pkdb が無い手元は `tools/fetch_dex_texts.py` で `resource/pokedex_text.csv`・`resource/pokedex_evolution.csv` を書き出す。Git に入れない）。同じ種族で読みがなが同じ文（漢字かひらがなかが違うだけ）は1問にまとめて漢字の書き方で出し、パラドックスポケモン（`EXCLUDED_SPECIES`。伏せると1匹に決まらない）は出題しない。説明文に出てくるポケモンの名前は、答えに限らずみな `****` に伏せる（進化前の名前でも答えが分かるため）。答えは投稿の問題文（伏せ字にした文）から引き直し、同じ文になるポケモンはみな正解。フォームの説明はそのフォームの名前で答える（種族名で答えたら基本の姿）。別のフォーム・進化の前後は「おしい」と返し、戦績に数えない（判定ログは `judge` が空、`detail` が `おしい`）。
- 図鑑番号クイズ（`noq`）は `/q` の `mode` で出し方を選ぶ（既定はポケモン→番号、`番号→ポケモン` も選べる）。種別は1つで、出し方は問題文（`No.510 -> [?]` / `レパルダス -> [?]`）から見分ける（`QuizSession.variant`）。正解から `NUMBER_NEAR`（3）以内の番号は「おしい」。ポケモン→番号は数字で答え、チャンネルにそのまま書いた数字も回答として拾う。
- 回答・ギブアップ・ヒントのたびに判定ログ（`quiz_log` テーブル。DBが無ければ `log/<種別>log.csv`）へ1行残す（DBには回答者のユーザーIDも入る）。出題のたびに `quiz_post` テーブルへも1行残す（出題条件・Botの版つき。回答の付かなかった出題を数えるため。`quiz_message_id` で `quiz_log` とつながる）。列の意味は `bot_module/save.py` の `CREATE_SQL` のコメントにある。`/quizrecord` はここから苦手な問題を出す（戦績の数はセーブデータから）。全体の集計は shake-cloud の Botポータル（`stacks/bot-portal/app/quizlog.py`、「クイズ分析」タブ）が読むので、列や `judge` の値を変えるときはそちらも合わせる。保存する内容を変えたら `docs/privacy.md` も直す。
- 音源（`resource/cry/`・`resource/intro/`）と画像（`resource/image/`）は Git に入れない。`tools/fetch_cries.py`・`tools/build_intro_clips.py`（ffmpeg が必要）で用意する。

### イントロクイズの回答リスト

`bot_module/intro.py` が判定する。回答は曲名ではなく「作品の略称＋戦う相手」（例: `BWシロナ`）。

**別名・ほかに流れる作品・シークレットは pkdb（`sleepy_pkdb` の `app_intro_alias`・`app_intro_appearance`・`app_intro_secret`）が正**。Bot は1分ごとに読み直すので、**直すのに PR も配備も要らない**。本番とテスト用Botは同じ表を見る。

「この答えが通らない」「この曲はシークレットに」と言われたら、`tools/intro_db.py` で直す:

```bash
python tools/intro_db.py list ゼロラボ                      # 曲を探して、いまの登録を見る
python tools/intro_db.py judge SV ゼロラボ sv博士            # その曲が出題されたときの判定
python tools/intro_db.py alias add SV ゼロラボ オーリム フトゥー   # 別名を足す（remove で消す）
python tools/intro_db.py alias add Pt フロンティアブレーン ネジキ --in HGSS  # HGSSで流れるときだけの呼び名
python tools/intro_db.py appear add DP ディアルガ・パルキア ORAS   # ORASでも流れる（remove で消す）
python tools/intro_db.py secret add SM "トレーナー 〜ポケモン Zリングシンクロバージョン〜" 理由  # remove で戻す
python tools/intro_db.py pull                               # pkdb → CSV（控え）。たまにコミットする
```

- 作品は略称でも作品名でもよく、曲名は一部でよい（その作品で1曲に決まること）。apps-01 へのSSH鍵（`~/.ssh/id_ed25519_pve`）と、手元の曲リスト（`resource/intro/manifest.csv`）が要る。
- 直す前に `judge` で今の判定を見て、直したあと出てくる判定が `correct` になったことを確かめる。**`ambiguous`・`ambiguous_song`・`partial` は「聞き返し」で、多くは仕様**（略称が要る、決戦か戦闘か決まらない、地方を省いた、など）。別名で無理に通さず、仕様かどうかを先に考える。
- 別名は、その作品でその曲だけを指す呼び方にする。同じ作品のほかの曲にも当てはまる呼び方（例: エリアゼロの戦闘曲2つに「パラドックスポケモン」）は足さない。居ない作品の略称では通さない（`ORASミクリ` は不正解）。
- シークレットは、未使用曲・古いバージョン・連動用の別音源など、ふつうに遊んで聞く機会がほぼ無い音源だけ。
- `push`（CSVでpkdbを丸ごと置き換える）は、pkdbでの直しを消すので、頼まれたときだけ使う。
- `canon`・`judge` など**判定の仕組み**を変えるのはコードの変更で、PRと配備が要る。データで直せるかを先に確かめる。

pkdb が使えないとき（`PKDB_PASSWORD` が無い・つながらない・表が空）は `resource/` のCSVを使う:

| ファイル | 中身 | 直し方 |
|---|---|---|
| `intro_works.csv` | 作品名 → 略称 | 手で編集（PRと配備が要る） |
| `intro_words.csv` | 言葉 → 言い換え（よみなど） | 手で編集（PRと配備が要る） |
| `intro_aliases.csv`・`intro_appearances.csv`・`intro_secret.csv` | 別名／再録・流用／シークレットの控え | **手で直さない**。`tools/intro_db.py pull` で pkdb から書き出す |

表の定義は shake-cloud の `stacks/pkdb/sql/app_intro.sql`。`tools/intro_sheet.py` は、人がまとめて見直すための表（Markdown）の出し入れ（`import` のあと `intro_db.py push` で pkdb へ入る）。`python tools/export_intro_answers.py` で、曲ごとにどの答えが正解になるかを書き出せる。テストは本物のCSVではなく `tests/data/` の写しを使う。

### ログ

`ub.output_log` / `output_warning` / `output_error`（`bot_module/func.py`）が標準 logging（`ubsleepy` ロガー）へ出す。警告以上は `cogs/logs.py` が30秒ごとにまとめて、`ACTIVE_GUILD_ID`（通常は既定のサーバー、debug では開発用ギルド）のログチャンネルへ流す。全サーバーへは流れない。

## そのほか

- `save/`・`log/`・`temp/`・`resource/image`・`resource/intro`・`resource/pokemon_senryu.csv`・`resource/pokedex_text.csv`・`resource/pokedex_evolution.csv` は Git の対象外。共有したくない作業ファイルは `temp/` へ置く。
- `config.json` はプレースホルダ入りでリポジトリにある既定値。サーバー固有の値は DB 側に入るので、ここへ実IDを書き足さない。
- 認証（学籍番号・ロール付与）と通話通知は別リポジトリの認証Bot（CIRCLEAUTH）にある。`settings.py` に残る `stage_channel_id` などはその名残。
- コミットは `fix(quiz): …` のような接頭辞つきの日本語。main へは PR（squash）で入れる。
