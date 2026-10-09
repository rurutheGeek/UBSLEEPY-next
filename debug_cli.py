#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Discordなしでコマンドを試すデバッグCLI。

本物のCogのコールバックを、偽のDiscordオブジェクト（Message/Interactionの
サブクラス）で呼び、送られる内容を標準出力へ出す。Discordへは接続しない。

    python debug_cli.py dex リザードン
    python debug_cli.py search みず 合計<400
    python debug_cli.py                # 対話モード（q → answer / hint / give も可）
    python debug_cli.py --stdin < commands.txt   # 複数コマンドを1プロセスで

既定ではセーブの増減を書き込まず、表示だけする（読み取りは本物の保存先を見る。
--save で増減も実際に保存先へ書く）。図鑑とセーブの接続先は環境変数（PKDB_PASSWORD・
UBSLEEPY_DB_PASSWORD）に従う。--debug で開発用ギルドの設定を使う。
"""
from __future__ import annotations

import asyncio
import os
import shlex
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import discord

JST = ZoneInfo("Asia/Tokyo")


class FakeUser:
    def __init__(self, user_id=1, name="debug", bot=False):
        self.id = user_id
        self.name = name
        self.bot = bot
        self.roles = []

    async def add_roles(self, role):
        self.roles.append(role)

    async def remove_roles(self, role):
        if role in self.roles:
            self.roles.remove(role)


class FakeFile:
    def __init__(self, filename):
        self.filename = filename


class FakeRole:
    def __init__(self, role_id=1, name="role"):
        self.id = role_id
        self.name = name


class FakeGuild:
    def __init__(self, guild_id=1, name="debug-guild"):
        self.id = guild_id
        self.name = name
        self.approximate_member_count = 100
        self._role = FakeRole()

    def get_role(self, role_id):
        return self._role

    def get_member(self, user_id):
        return None


class FakeReference:
    def __init__(self, message_id=0, resolved=None):
        self.message_id = message_id
        self.resolved = resolved


class FakeChannel:
    def __init__(self, recorder, channel_id=1):
        self.id = channel_id
        self.recorder = recorder
        self.sent = []

    async def send(self, content=None, **kwargs):
        message = FakeMessage(
            author=self.recorder.bot.user,
            content=content,
            channel=self,
            embeds=_embeds_from(kwargs),
            message_id=_next_id(),
        )
        files = kwargs.get("files") or ([kwargs["file"]] if kwargs.get("file") else [])
        message.attachments = [
            FakeFile(getattr(file, "filename", str(file))) for file in files]
        self.sent.append(message)
        self.recorder.action("channel.send", content=content, **kwargs)
        return message

    async def fetch_message(self, message_id):
        for message in self.sent:
            if message.id == message_id:
                return message
        return self.sent[-1]

    def history(self, limit=10):
        async def _history():
            for message in reversed(self.sent[-limit:]):
                yield message

        return _history()

    async def delete(self):
        pass


class FakeMessage(discord.Message):
    """discord.Message のサブクラス。isinstance判定を通すため。"""

    def __init__(self, **kwargs):
        pass

    def __new__(cls, author=None, content="", channel=None, embeds=None,
                reference=None, guild=None, message_id=None):
        self = super().__new__(cls)
        self.id = message_id or _next_id()
        self.content = content or ""
        self.author = author
        self.channel = channel
        self.embeds = list(embeds or [])
        self.reference = reference
        self.guild = guild or FakeGuild()
        self.attachments = []
        self.components = []
        self.reactions = []
        return self

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)
        self.channel.recorder.action("reaction", emoji=emoji, message=self)

    async def remove_reaction(self, emoji, user):
        if emoji in self.reactions:
            self.reactions.remove(emoji)

    async def reply(self, content=None, **kwargs):
        kwargs.setdefault("reference", FakeReference(resolved=self))
        return await self.channel.send(content, **kwargs)

    async def edit(self, **kwargs):
        if kwargs.get("embed") is not None:
            self.embeds = [kwargs["embed"]]
        self.channel.recorder.action("message.edit", **kwargs)
        return self

    async def delete(self):
        pass


class FakeResponse:
    def __init__(self, recorder):
        self.recorder = recorder
        self._done = False

    async def defer(self, **kwargs):
        self._done = True
        self.recorder.action("response.defer", **kwargs)

    async def send_message(self, content=None, **kwargs):
        self._done = True
        self.recorder.action("response.send_message", content=content, **kwargs)

    async def edit_message(self, **kwargs):
        self.recorder.action("response.edit_message", **kwargs)

    async def send_modal(self, modal):
        self._done = True
        self.recorder.action("response.send_modal", title=modal.title)

    def is_done(self):
        return self._done


class FakeFollowup:
    def __init__(self, recorder):
        self.recorder = recorder

    async def send(self, content=None, **kwargs):
        self.recorder.action("followup.send", content=content, **kwargs)

    async def edit_message(self, **kwargs):
        self.recorder.action("followup.edit_message", **kwargs)


class FakeInteraction(discord.Interaction):
    """discord.Interaction のサブクラス。isinstance判定を通すため。"""

    def __init__(self, *args, **kwargs):
        pass

    def __new__(cls, recorder, user=None, channel=None, message=None,
                guild=None, data=None):
        self = super().__new__(cls)
        self.id = _next_id()
        self.data = data or {}
        self.user = user or FakeUser()
        self.channel = channel
        self.message = message
        self._guild = guild or FakeGuild()
        self._response = FakeResponse(recorder)
        self._followup = FakeFollowup(recorder)
        return self

    @property
    def guild(self):
        return self._guild

    @property
    def response(self):
        return self._response

    @property
    def followup(self):
        return self._followup


class FakeBot:
    def __init__(self, recorder):
        self.recorder = recorder
        self.user = FakeUser(user_id=0, name="ubsleepy", bot=True)

    async def fetch_guild(self, guild_id, with_counts=False):
        return FakeGuild(guild_id)

    def get_channel(self, channel_id):
        return None


_ID_COUNTER = 1000000000000000000


def _next_id():
    global _ID_COUNTER
    _ID_COUNTER += 1000
    return _ID_COUNTER


def _embeds_from(kwargs):
    if kwargs.get("embed") is not None:
        return [kwargs["embed"]]
    return list(kwargs.get("embeds") or [])


def _print_embed(embed):
    print(f"  embed: {embed.title!r}")
    if embed.description:
        for line in str(embed.description).splitlines():
            print(f"    | {line}")
    for field in embed.fields:
        print(f"    [{field.name}] {field.value}")
    footer = embed.footer.text if embed.footer else None
    if footer:
        print(f"    footer: {footer}")


class Recorder:
    def __init__(self, bot):
        self.bot = bot
        self.actions = []

    def action(self, kind, **kwargs):
        self.actions.append((kind, kwargs))

    def report(self, user_id, index, modifi, user_name, saved_value):
        self.actions.append(("report", {
            "user": user_name, "index": index, "delta": modifi, "value": saved_value,
        }))

    def dump(self):
        for kind, kwargs in self.actions:
            if kind == "report":
                print(f"[report] {kwargs['user']} {kwargs['index']} "
                      f"{kwargs['delta']:+d} -> {kwargs['value']}")
                continue
            content = kwargs.get("content")
            ephemeral = kwargs.get("ephemeral")
            suffix = " (ephemeral)" if ephemeral else ""
            print(f"[{kind}]{suffix}" + (f" {content}" if content else ""))
            for embed in _embeds_from(kwargs):
                _print_embed(embed)
            files = kwargs.get("files") or ([kwargs["file"]] if kwargs.get("file") else [])
            for file in files:
                print(f"    file: {getattr(file, 'filename', file)}")
            if kwargs.get("view") is not None:
                labels = []
                for child in kwargs["view"].children:
                    label = getattr(child, "label", None) or getattr(child, "placeholder", None)
                    labels.append(f"{type(child).__name__}({label})")
                print(f"    view: {', '.join(labels)}")
            if kind == "reaction":
                print(f"    reaction: {kwargs['emoji']}")
            if kind == "attachment":
                print(f"    attachment: {kwargs['path']}")
        self.actions.clear()


class Harness:
    def __init__(self, save=False):
        # bot_module は sys.argv を見て debug を決めるため、ここで読み込む。
        import bot_module.config as cfg
        from bot_module import pokedex as pokedex_module
        from bot_module import save as save_module
        from cogs import daily, pokedex, quiz, search

        self.cfg = cfg
        self.pokedex_module = pokedex_module
        self.save_module = save_module
        self.quiz_module = quiz
        self.save = save
        self.bot = FakeBot(None)
        self.recorder = Recorder(self.bot)
        self.channel = FakeChannel(self.recorder)
        self.interaction = FakeInteraction(self.recorder, channel=self.channel)
        self.pokedex_cog = pokedex.Pokedex(self.bot)
        self.quiz_cog = quiz.Quiz(self.bot)
        self.daily_cog = daily.Daily(self.bot)
        self.search_cog = search.Search(self.bot)
        self.quiz_message = None
        self.quiz_name = None
        self._report_state = {}
        self.quiz_cog.state.bakusoku_mode = False
        if self.save_module.get_store() is None:
            self._ensure_csv_report()
        self._stub_attachments()
        if not save:
            self._intercept_reports()

    def _ensure_csv_report(self):
        """CSVのセーブファイルが無いとき、空のファイルを用意する。"""
        path = self.cfg.REPORT_PATH
        if os.path.exists(path):
            return
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            file.write("ユーザーID,ユーザー名,クジびきけん,おこづかい\n")

    def _stub_attachments(self):
        """画像ファイルが無い手元でも動くよう、添付は名前だけ記録する。"""
        import bot_module.func as ub

        self._original_attachment = ub.attachment_file

        def fake_attachment(file_path):
            filename = f"attachedImage{os.path.splitext(file_path)[1]}"
            self.recorder.action("attachment", path=file_path)
            return FakeFile(filename), f"attachment://{filename}"

        ub.attachment_file = fake_attachment

    def _intercept_reports(self):
        import bot_module.func as ub

        self._original_report = ub.report

        def fake_report(user_id, index, modifi, user_name):
            # 読み取り（modifi=0）は本物の保存先から。増減は表示だけにする。
            current = self._original_report(user_id, index, 0, user_name)
            if modifi == 0:
                return current
            value = current + modifi
            self.recorder.report(user_id, index, modifi, user_name, value)
            return value

        ub.report = fake_report

    def restore(self):
        import bot_module.func as ub

        if hasattr(self, "_original_report"):
            ub.report = self._original_report
        if hasattr(self, "_original_attachment"):
            ub.attachment_file = self._original_attachment

    def sources(self):
        pokedex = self.pokedex_module.get_pokedex()
        pokedex_source = "pkdb" if os.environ.get("PKDB_PASSWORD") else "CSV"
        store = self.save_module.get_store()
        if store is None:
            save_source = "CSV"
        else:
            save_source = f"DB ({store.config.get('dbname', '?')})"
        return pokedex_source, save_source, len(pokedex.records)

    async def dispatch(self, argv):
        if not argv:
            return
        command, *args = argv
        handler = getattr(self, f"cmd_{command}", None)
        if handler is None:
            print(f"不明なコマンド: {command}（help で一覧）")
            return
        try:
            await handler(args)
        except Exception as error:
            print(f"エラー: {type(error).__name__}: {error}")
        finally:
            self.recorder.dump()

    async def cmd_sources(self, args):
        pokedex_source, save_source, count = self.sources()
        print(f"図鑑: {pokedex_source} ({count}件)")
        print(f"セーブ: {save_source}{'（--saveで書き込み）' if self.save else '（表示のみ）'}")

    async def cmd_dex(self, args):
        if not args:
            print("使い方: dex <ポケモン名>")
            return
        await self.pokedex_cog.display_pokedex(self.interaction, " ".join(args))

    async def cmd_comp(self, args):
        if len(args) < 2:
            print("使い方: comp <ポケモン名> <ポケモン名> [...]")
            return
        await self.pokedex_cog.comp.callback(self.pokedex_cog, self.interaction, *args)

    async def cmd_simil(self, args):
        if not args:
            print("使い方: simil <ポケモン名> [auto|final|middle|all]")
            return
        name, *rest = args
        await self.pokedex_cog.simil.callback(
            self.pokedex_cog, self.interaction, name, rest[0] if rest else "auto"
        )

    async def cmd_q(self, args):
        quizname = args[0] if args else "種族値クイズ"
        if quizname in self.cfg.QUIZNAME_DICT.values():
            quizname = next(k for k, v in self.cfg.QUIZNAME_DICT.items() if v == quizname)
        if quizname not in self.cfg.QUIZNAME_DICT:
            print(f"使い方: q [{'|'.join(self.cfg.QUIZNAME_DICT)}]")
            return
        before = len(self.channel.sent)
        await self.quiz_cog.q.callback(self.quiz_cog, self.interaction, quizname)
        posted = [m for m in self.channel.sent[before:] if m.embeds]
        if posted:
            self.quiz_message = posted[-1]
            self.quiz_name = self.cfg.QUIZNAME_DICT[quizname]
            print(f"→ 出題: {quizname}（answer / hint / give / press で応答を試せる）")

    async def cmd_answer(self, args):
        await self._respond(" ".join(args), interaction=False)

    async def cmd_hint(self, args):
        await self._respond(" ".join(args) or "ヒント", interaction=False)

    async def cmd_give(self, args):
        await self._respond("ギブ", interaction=False)

    async def cmd_press(self, args):
        if not args:
            print("使い方: press <ボタンのラベル>（ACクイズ用）")
            return
        await self._respond(args[0], interaction=True)

    async def _respond(self, text, interaction):
        if self.quiz_message is None:
            print("先に q で出題してください")
            return
        worker = self.quiz_module.QuizSession(self.bot, self.quiz_name,
                                       self.quiz_cog.state)
        if interaction:
            press = FakeInteraction(
                self.recorder,
                user=self.interaction.user,
                channel=self.channel,
                message=self.quiz_message,
                data={"custom_id": f"acq_{text}"},
            )
            await worker.try_response(press)
            return
        reply = FakeMessage(
            author=self.interaction.user,
            content=text,
            channel=self.channel,
            reference=FakeReference(resolved=self.quiz_message),
        )
        await worker.try_response(reply)

    async def cmd_search(self, args):
        query = " ".join(args) if args else None
        await self.search_cog.search.callback(self.search_cog, self.interaction, query)

    async def cmd_quizrecord(self, args):
        quizname = args[0] if args else "種族値クイズ"
        if quizname in self.cfg.QUIZNAME_DICT.values():
            quizname = next(k for k, v in self.cfg.QUIZNAME_DICT.items() if v == quizname)
        await self.quiz_cog.quizrecord.callback(
            self.quiz_cog, self.interaction, None, quizname
        )

    async def cmd_pocketmoney(self, args):
        await self.daily_cog.pocketmoney.callback(self.daily_cog, self.interaction)

    async def cmd_bmode(self, args):
        await self.quiz_cog.bmode.callback(
            self.quiz_cog, self.interaction, args[0].upper() if args else None
        )

    async def cmd_bqdata(self, args):
        message = FakeMessage(
            author=FakeUser(),
            content="/bqdata " + " ".join(args),
            channel=self.channel,
        )
        await self.quiz_cog.on_message(message)

    async def cmd_crydata(self, args):
        message = FakeMessage(
            author=FakeUser(),
            content="/crydata " + " ".join(args),
            channel=self.channel,
        )
        await self.quiz_cog.on_message(message)

    async def cmd_introdata(self, args):
        message = FakeMessage(
            author=FakeUser(),
            content="/introdata " + " ".join(args),
            channel=self.channel,
        )
        await self.quiz_cog.on_message(message)

    async def cmd_help(self, args):
        print(HELP)

    async def run_lines(self, lines):
        for line in lines:
            argv = shlex.split(line)
            if not argv:
                continue
            if argv[0] in ("quit", "exit"):
                break
            await self.dispatch(argv)

    def banner(self):
        pokedex_source, save_source, count = self.sources()
        print(f"図鑑: {pokedex_source} ({count}件) / セーブ: {save_source}")

    async def repl(self):
        self.banner()
        print("help でコマンド一覧。quit で終了。")
        loop = asyncio.get_running_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, input, "ubsleepy-debug> ")
            except EOFError:
                break
            await self.run_lines([line])

    async def run_stdin(self):
        """標準入力からコマンドを順に実行する（ポータルなどから使う）。"""
        self.banner()
        await self.run_lines(sys.stdin.read().splitlines())


HELP = """コマンド一覧:
  sources                       図鑑とセーブの接続先を表示
  dex <名前>                    図鑑
  comp <名前> <名前> [...]      種族値比較
  simil <名前> [auto|final|middle|all]  類似ランキング
  q [クイズ名]                  出題（bq / 種族値クイズ など）
  answer <答え>                 出題への回答（正誤判定）
  hint <ヒント>                 ヒント（特性 / 地方 / ヒント など）
  give                          ギブアップ
  press <ラベル>                ACクイズのボタン（こうげき / とくこう / 同値）
  search [条件...]              検索（条件なしはGUIパネル）
  quizrecord [クイズ名]         戦績と苦手な問題
  pocketmoney                   おこづかい
  bmode [ON|OFF]                連続出題モード
  bqdata [条件...]              出題条件の表示・変更
  crydata [今|昔|両方]          鳴き声の出題条件の表示・変更
  introdata [区分] [作品名]     イントロの出題条件の表示・変更
  help / quit
"""


def main():
    argv = sys.argv[1:]
    debug = "--debug" in argv
    save = "--save" in argv
    stdin_mode = "--stdin" in argv
    argv = [a for a in argv if a not in ("--debug", "--save", "--stdin")]
    if debug:
        # bot_module.config は sys.argv を見て debug を決める
        sys.argv = [sys.argv[0], "debug"] + argv

    harness = Harness(save=save)
    if stdin_mode:
        asyncio.run(harness.run_stdin())
    elif argv:
        asyncio.run(harness.dispatch(argv))
    else:
        asyncio.run(harness.repl())


if __name__ == "__main__":
    main()
