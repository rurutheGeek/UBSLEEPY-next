
---

# UBSLEEPY

このプロジェクトは, 2023年から開発されている PythonベースのDiscord Botのリポジトリです. 以下の手順を参考にセットアップを行い, プロジェクトを実行してください. 

---

## 旧バージョン（UBSLEEPY）との違い

2026年の大改修で、構成・データ・運用が次のように変わりました。

### 構成
- **認証（学籍番号・ロール付与）と通話通知は認証Bot「CIRCLEAUTH」へ分離**。このBotは汎用のポケモン機能だけを持ちます
- Cog分割・型つき設定・テスト＋CI・ログの整理
- 配備はGitHub Actionsがビルドしたイメージ（GHCR）をdigest固定で使います

### 多サーバー対応
- コマンドは**グローバル登録**。クラブのサーバーにはギルドコマンドのコピーも配るので**再起動で即時反映**されます
- サーバーごとの設定は**DB**（`/channel`：クイズ・日替わり・ログ、`/role`：おかねもちロール）。`config.json` は既定値だけ
- 日替わり投稿はBotが居る**全サーバー**を回ります（設定済みのサーバーだけ）
- サーバーに追加されたときは案内を投稿します
- intentsを最小化（guilds / members / guild_messages / message_content）

### データ
- セーブデータ（おこづかい・クジびきけん・クイズ戦績）は**PostgreSQL（ubsleepy DB）**へ。旧CSVは `python -m bot_module.save save/report.csv` で取り込めます
- セーブデータは**全サーバー共通**（どのサーバーで使っても同じ残高・戦績）
- 図鑑データは**pkdb（PostgreSQL）**から取得（未設定ならCSV）
- ランキングはSQL（索引＋「自分より大きい値の数+1」で順位）

### コマンド
- `/help` を追加（引数なしで一覧、コマンド名で詳細。サジェスト付き）
- クイズは `/q`（種別を選択。旧 `/bq` 相当）・`/quizrate`・`/bmode`
- `/search` を追加（タイプ・種族値などの条件検索。未記入でGUI）
- `/channel` はDB保存に（旧: config.json 書き換え）。`/role` を追加
- 旧 `/wish`（フィードバック）は廃止。問い合わせは [GitHub Issues](https://github.com/rurutheGeek/UBSLEEPY-next/issues) へ
- ステージチャンネルなどクラブ固有の機能は削除/認証Bot側へ

### 運用
- 日次バックアップ（state の tar）とDBバックアップ（pg_dump）
- プライバシーポリシー・利用規約は GitHub Pages で公開: <https://ruruthegeek.github.io/UBSLEEPY-next/>

---

## セットアップ手順

このプログラムを実行するには, Pythonをインストールする必要があります. 

### Pythonインストール手順

#### 1. Pythonの公式サイトからダウンロード

1. [Python公式ダウンロードページ](https://www.python.org/downloads/)にアクセスします. 
2. 「Download Python 3.x.x」（最新バージョン）ボタンをクリックします. 
   * Python 3.9以上をインストールしてください. 

#### 2. インストーラーの実行

1. ダウンロードしたインストーラー（例：`python-3.11.0-amd64.exe`）をダブルクリックして実行します. 
2. インストール画面が表示されたら, 以下のオプションにチェックを入れてください：
   * ✅ **Add Python 3.x to PATH**
   * ✅ **Install launcher for all users (recommended)**
#### 3. インストールの確認

1. インストールが完了したら, 「**Close**」をクリックします. 
2. Windowsのスタートメニューから「**コマンドプロンプト**」または「**PowerShell**」を検索して起動します. 
3. 以下のコマンドを入力してPythonが正しくインストールされたか確認します：

```
python --version
```

または

```
py --version
```

バージョン情報（例：`Python 3.11.0`）が表示されればインストール成功です.  
**特定のバージョンのPythonからコマンドがpythonの代わりにpyしか使えないことがあるようです. pythonコマンドに問題がある場合, pyコマンドを試してください. **  
   
- 仮想環境（例: `venv`）の利用を推奨します. 

### 仮想環境`venv` 導入手順

```bash
# プロジェクトディレクトリに移動
cd UBSLEEPY

# 仮想環境の作成
python -m venv venv

# 仮想環境を有効化する方法
venv\Scripts\activate
```
### vscodeの場合
vscodeのターミナルを利用する場合, PowerShellで実行されます. このシェルは, デフォルトではスクリプトの実行が制限されています. そのため, `venv\Scripts\Activate.ps1`スクリプトを実行しようとすると, 以下のようなエラーが発生することがあります：

```
venv\Scripts\Activate.ps1 : このシステムではスクリプトの実行が無効になっているため, ファイル venv\Scripts\Activate.ps1 を読み込むことができません. 
```

#### VSCodeのsettings.jsonに設定を追加

VSCodeの設定ファイルに追記することで, PowerShellでスクリプト実行を許可できます：

1. VSCodeの設定ファイルを開きます：
   - `Ctrl+Shift+P`を押して, コマンドパレットを開きます
   - `Preferences: Open Settings (JSON)`と入力して選択します

2. 以下の設定を`settings.json`に追加します：

```json
{
    "terminal.integrated.profiles.windows": {
        "PowerShell": {
            "source": "PowerShell",
            "icon": "terminal-powershell",
            "args": ["-ExecutionPolicy", "Bypass"]
        }
    },
    "terminal.integrated.defaultProfile.windows": "PowerShell"
}
```

### 1. リポジトリをクローンする
以下のコマンドを使用してリポジトリをローカル環境にクローンします：
```bash
git clone https://github.com/rurutheGeek/UBSLEEPY.git
```
Gitをまだインストールしていない場合は, 以下の手順に従ってインストールしてください. 

#### Windows
1. [Git for Windows](https://gitforwindows.org/)の公式サイトにアクセスします. 
2. ダウンロードボタンをクリックして, インストーラーをダウンロードします. 
3. ダウンロードしたインストーラーを実行し, 画面の指示に従ってインストールを完了します. 
   - 基本的にはデフォルト設定のままで問題ありません. 
   - インストール完了後, 「Git Bash」または「コマンドプロンプト」から`git --version`コマンドを実行して, 正常にインストールされたか確認できます. 

#### macOS
1. **Homebrew**を使用する場合:
   ```bash
   brew install git
   ```
2. **インストーラー**を使用する場合:
   - [Git公式サイト](https://git-scm.com/download/mac)からインストーラーをダウンロードして実行します. 
3. インストール完了後, ターミナルで`git --version`コマンドを実行して確認します. 

#### Linux (Ubuntu/Debian)
```bash
sudo apt update
sudo apt install git
```

### 2. 必要なパッケージをインストールする

```bash
pip install --no-cache-dir -r ./setup/requirements.txt
```

### 3. リソースファイルの配置
- main.py 以上の階層に以下のファイルを作成してください：
  - 必須:  `.env`
```.env
DISCORD_TOKEN=ここにDiscordBotのトークン
# 任意: 設定すると図鑑をpkdb（PostgreSQL）から読む。未設定ならCSVを使う
PKDB_PASSWORD=図鑑DBの読み取り用パスワード
# 任意: 設定するとセーブデータをubsleepy DBへ書く。未設定ならsave/report.csvを使う
UBSLEEPY_DB_PASSWORD=セーブDBの書き込み用パスワード
```
- `config.json`（リポジトリ直下）: サーバー固有のID（ギルド・チャンネル・ロール）の設定。リポジトリには**プレースホルダ入り**で入っているので、自分のサーバーに合わせて書き換えてください。`config.json` が無い場合は `document/default_config.json` が使われます。
- resource ディレクトリに以下のファイルを配置してください：
  - `pokemon_database.csv`: `PKDB_PASSWORD` が未設定のときの図鑑データ（設定時はpkdbが優先）
  - オプション: `pokemon_senryu.csv` や `pokemon_calendar.csv`（データを使用する場合は配置）. 

### 4. Botを起動する
以下のコマンドで, Botを起動します：
```bash
python main.py
```

---

## ディレクトリ構成

以下はプロジェクト内の主なディレクトリの説明です：

- **`bot_module`**  
  `main.py` や Cog から呼び出す自作モジュール（設定・図鑑検索・Embedなど）を格納します. 
  クイズのセッション（出題・回答受付・判定・開示）は `quiz_session.py` にあります. 

- **`cogs`**  
  機能ごとの Cog を格納します（`pokedex` / `quiz` / `search` / `daily` / `settings` / `logs` / `help`）. `main.py` は起動と読み込みだけを行います. 
  認証・通話通知は別リポジトリの認証Bot（CIRCLEAUTH）にあります. 

- **`tests`**  
  pytest のテストを格納します. 

- **`resource`**  
  ポケモン図鑑（例: `pokemon_database.csv`）やBotで使用する画像ファイルを格納します. 

- **`document`**  
  Botが投稿する文章が記載されたテキストファイルを格納します. 

- **`save`**  
  ユーザーデータや一時保存ファイル（キャッシュ）を格納します（共有対象外）. 

- **`log`**  
  ログファイルを格納します（共有対象外）. 

- **`setup`**  
  使用パッケージの一覧である requirements.txt や Dockerを利用したセットアップ用ファイルなど 起動のためのファイル格納します. 

- **`temp`**  
  開発中に作成したが共有しないファイルを格納します（共有対象外）. 

---

## 動作環境

- **Python バージョン**: 3.9以上を推奨. 
- 必要なPythonパッケージは `requirements.txt` に記載されています. 

---

## 使用方法

Botの具体的なコマンドや使い方については, ドキュメントやコード内のコメントを参照してください. 

### Discordなしで試す（デバッグCLI）

Discordへ接続せず、本物のCogのコマンドを偽のDiscordオブジェクトで呼んで、送られる内容を標準出力へ出します.

```bash
python debug_cli.py dex リザードン
python debug_cli.py search みず 合計<400
python debug_cli.py               # 対話モード
```

対話モードでは出題してから回答まで試せます:

```
ubsleepy-debug> q bq
ubsleepy-debug> hint ヒント
ubsleepy-debug> answer リザードン
ubsleepy-debug> give
```

- 既定ではセーブの増減を書きません（表示だけ）。読み取りは本物の保存先を見ます。`--save` で増減も設定された保存先（CSVまたはDB）へ実際に書きます
- 図鑑とセーブの接続先は環境変数（`PKDB_PASSWORD`・`UBSLEEPY_DB_PASSWORD`）に従います。`sources` コマンドで確認できます
- `--stdin` で標準入力から複数コマンドを1プロセスで実行します（`q` → `answer` のように状態を保つ。ポータルのデバッグ欄が使います）
- `--debug` で開発用ギルドの設定を使います
- 画像ファイルが無い手元でも動くよう、添付画像はパス名の表示だけにしています

---

## 貢献

このプロジェクトへの貢献は歓迎されています.  
バグ報告や新機能の提案など, [Issues](https://github.com/rurutheGeek/UBSLEEPY/issues) や [Pull Requests](https://github.com/rurutheGeek/UBSLEEPY/pulls) を通じてご参加ください. 

---

## ライセンス

このプロジェクトのライセンスは, **GNU General Public License (GPL v3)** に準拠しています. リポジトリ内の `LICENSE` ファイルを参照してください. 

---

## 投稿先チャンネル・ロール（/channel /role）

サーバー管理権限を持つ人がDiscordから変更できます。設定はDBに保存され、再起動後も残ります。

- `/channel`（引数なし）: 現在の設定を表示
- `/channel setting:クイズ（回答の受付） channel:#クイズ` のように変更
- 設定できるもの: クイズ（回答の受付）・日替わり投稿・ログ（警告以上）
- `/role setting:おかねもちロール role:@ロール`: IDくじで1位になった人に付くロール
- `config.json` の `GUILD_DICT` は既定値（未設定は0）。手で書き換えなくてもDiscordから設定できます

## Dockerで動かす（ローカル）

```bash
echo 'DISCORD_TOKEN=...' > .env
docker compose up -d --build
docker compose logs -f
```

- `save/`・`log/`・`config.json`・`resource/pokemon_senryu.csv`・`resource/image/` はホストにマウントして永続化します
- イメージは `setup/Dockerfile` から作ります（`docker compose` が参照）

## サーバーで動かす（イメージ固定）

本番・テストは apps-01 で、GitHub Actions が main のマージ時にビルドした
イメージ（GHCR）を **digest固定** で動かします。ホスト上ではビルドしません。

- スタック: `compose.yaml` + `compose.lock.yaml`（digest固定）+ `manage.py`
- 状態: `STORAGE_ROOT/state` をマウント（`save` / `log` / `config.json` / `resource`）
- 秘密: `secrets/` に `discord_token`・`pkdb_password`・`ubsleepy_db_password`
- `.env`: `STORAGE_ROOT` と `UBSLEEPY_TEST`（テスト配備は `true` で debug モード + `ubsleepy_test` DB）

```bash
cd /opt/ubsleepy               # 本番（テスト配備は /opt/ubsleepy-next）
sudo python3 manage.py init    # 初回: .env と state ディレクトリの用意
sudo python3 manage.py up      # イメージを取得して起動
sudo python3 manage.py status
sudo python3 manage.py backup --destination /srv/ubsleepy/backups --keep 14
sudo python3 manage.py down
```

- 環境変数（コンテナへ渡す）: `DISCORD_TOKEN`・`PKDB_PASSWORD`・`UBSLEEPY_DB_PASSWORD`・`UBSLEEPY_DB_NAME`（既定 `ubsleepy`）
- **更新**: `compose.lock.yaml` の digest を新しいビルドへ書き換えて `manage.py up`
  - スタックの正本は shake-cloud の `stacks/ubsleepy`（本番）/ `stacks/ubsleepy-next`（テスト）
  - Ansible: `platform/ansible/ubsleepy.yml`（本番）/ `ubsleepy-next.yml`（テスト）
  - 手順の詳細: <https://github.com/rurutheGeek/shake-cloud/blob/main/docs/operations/ubsleepy.md>
