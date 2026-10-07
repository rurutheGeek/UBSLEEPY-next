# -*- coding: utf-8 -*-
# tests/test_intro.py
# イントロクイズ（曲リスト・出題・絞り込み・回答）と切り出しツール。
import asyncio
import datetime

import discord
import pytest

import bot_module.intro as intro
import bot_module.quiz_session as session_module
import cogs.quiz as quiz_module
from test_quiz import (
    FakeBot, FakeButtonInteraction, FakeChannel, FakeMessage, FakeQM, FakeRM,
    FakeUser, FakeVoiceChannel, FakeVoiceClient, FakeVoiceGuild)
import tools.build_intro_clips as build

ROWS = (
    ('a1', '戦闘！ジムリーダー', 'ソード・シールド', '戦闘', 'ジムチャレンジ'),
    ('a2', '1番道路', 'ソード・シールド', 'フィールド', ''),
    ('b1', '戦闘！ジムリーダー', 'スカーレット・バイオレット', '戦闘', ''),
    ('b2', 'テーブルシティ', 'スカーレット・バイオレット', 'フィールド', ''),
    ('b3', 'タイトル', 'スカーレット・バイオレット', 'その他', ''),
    ('b4', '戦闘！野生ポケモン（Ver. 1.0）', 'スカーレット・バイオレット', '戦闘', ''),
    ('b5', '戦闘！野生ポケモン', 'スカーレット・バイオレット', '戦闘', ''),
)


@pytest.fixture(autouse=True)
def answer_lists(monkeypatch):
    """対応リストはテスト用の固定のものを使う（本物は編集で変わるため）。"""
    for name in ('works', 'words', 'aliases', 'appearances'):
        monkeypatch.setattr(intro, f'{name.upper()}_PATH',
                            intro.Path(f'tests/data/intro_{name}.csv'))
    intro.reset_answer_lists()
    yield
    monkeypatch.undo()
    intro.reset_answer_lists()


@pytest.fixture
def library(monkeypatch, tmp_path):
    """曲リストと音源を一時フォルダに置く。"""
    directory = tmp_path / 'intro'
    (directory / 'clips').mkdir(parents=True)
    lines = ['id,title,work,category,aliases']
    for row in ROWS:
        lines.append(','.join(row))
        (directory / 'clips' / f'{row[0]}.ogg').write_bytes(b'ogg')
    (directory / 'manifest.csv').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    monkeypatch.setattr(intro, 'INTRO_DIRECTORY', directory)
    return directory


def _session(state=None):
    return quiz_module.QuizSession(
        FakeBot(), 'introq', state or quiz_module.QuizState())


def _intro_message(track_id='a1', **kwargs):
    attachment = type('A', (), {
        'filename': intro.intro_filename(track_id, 'abc123')})()
    return FakeMessage(author=None, attachments=[attachment], **kwargs)


def test_tracks_without_a_clip_are_left_out(library):
    (library / 'clips' / 'b3.ogg').unlink()

    assert [track.id for track in intro.load_tracks()] == [
        'a1', 'a2', 'b1', 'b2', 'b4', 'b5']


def test_no_manifest_means_no_tracks(monkeypatch, tmp_path):
    monkeypatch.setattr(intro, 'INTRO_DIRECTORY', tmp_path / 'none')

    assert intro.load_tracks() == []
    assert intro.random_track() is None


def test_tracks_are_filtered_by_work_and_category(library):
    ids = lambda tracks: [track.id for track in tracks]  # noqa: E731

    assert ids(intro.filter_tracks(categories=['戦闘'])) == ['a1', 'b1', 'b4', 'b5']
    assert ids(intro.filter_tracks(['ソード・シールド'])) == ['a1', 'a2']
    assert ids(intro.filter_tracks(['ソード・シールド'], ['フィールド'])) == ['a2']


def test_works_match_by_a_part_of_the_name(library):
    assert intro.match_works('そーど') == ['ソード・シールド']
    assert intro.match_works('スカーレットバイオレット') == ['スカーレット・バイオレット']
    assert intro.match_works('ダイヤモンド') == []
    assert intro.match_works('剣盾') == ['ソード・シールド']  # 略称
    assert intro.match_works('sv') == ['スカーレット・バイオレット']


def test_answers_are_read_ignoring_symbols_and_kana(library):
    ids = lambda text: [t.id for t in intro.find_tracks(text)]  # noqa: E731

    assert ids('戦闘!じむりーだー') == ['a1', 'b1']  # 曲名そのまま
    assert ids('せんとう ジムリーダー') == ['a1', 'b1']  # 漢字のよみ（言い換え）
    assert ids('ジム戦') == ['a1', 'b1']  # 相手＋戦、短い言い方
    assert ids('剣盾ジムリーダー') == ['a1']  # 略称＋相手
    assert ids('じむりーだーSV') == ['b1']  # 相手＋略称
    assert ids('ジムチャレンジ') == ['a1']  # 曲リストの別名
    assert ids('やせい') == ['b4', 'b5']  # 野生ポケモン -> 野生
    assert ids('！！') == []


def test_the_opponent_is_taken_from_the_title():
    cores = intro.answer_cores
    assert cores('戦闘！チャンピオン（Ver. 1.0）') == ['チャンピオン']
    assert cores('戦い(VS野生ポケモン)') == ['野生ポケモン', '野生']
    assert cores('ラストバトル(VSライバル)-ポケットモンスター ジ･オリジンver.-') == [
        'ライバル', 'ラストバトル']
    assert cores('戦闘！ゼクロム・レシラム') == [
        'ゼクロム・レシラム', 'ゼクロム', 'レシラム']
    assert cores('戦闘！ジムリーダー～ジムリーダーに勝利！') == ['ジムリーダー']
    assert cores('戦闘! チャンピオン(シンオウ)') == [
        'チャンピオン', 'シンオウチャンピオン', 'シンオウのチャンピオン',
        'チャンピオンシンオウ']
    assert cores('決戦！N') == ['N']
    # 「の」「のポケモン」は省いてもよい
    assert cores('戦闘! フラダリラボのオヤブン') == [
        'フラダリラボのオヤブン', 'フラダリラボオヤブン']
    assert cores('戦闘! フラダリラボのポケモン') == [
        'フラダリラボのポケモン', 'フラダリラボ', 'フラダリラボポケモン']
    assert cores('バトルタワー') == ['バトルタワー']


def test_the_answer_needs_the_work_when_it_is_in_several_works(library):
    gym_swsh, gym_sv, wild = (
        next(t for t in intro.load_tracks() if t.id == i) for i in ('a1', 'b1', 'b5'))

    assert intro.judge(gym_swsh, '剣盾ジムリーダー') == intro.CORRECT
    assert intro.judge(gym_swsh, 'swshのジム戦') == intro.CORRECT
    assert intro.judge(gym_swsh, 'ジムリーダー') == intro.AMBIGUOUS  # 2作品にある
    assert intro.judge(gym_swsh, 'SVジムリーダー') == intro.WRONG
    assert intro.judge(gym_sv, 'SVジムリーダー') == intro.CORRECT
    # 1作品にしか無い相手は略称なしでよい（同じ作品の別バージョンは数えない）
    assert intro.judge(wild, '野生') == intro.CORRECT
    assert intro.judge(wild, 'テーブルシティ') == intro.WRONG
    assert intro.judge(wild, 'しらないきょく') == intro.UNKNOWN


def test_the_alias_list_adds_names_that_are_not_in_the_title(monkeypatch, library):
    champion = intro.IntroTrack('c1', '戦闘！チャンピオン', 'ポケモン ダイヤモンド&パール', '戦闘')
    other = intro.IntroTrack('c2', '戦闘！チャンピオン', 'ポケットモンスター ブラック・ホワイト', '戦闘')
    cynthia = intro.IntroTrack('c3', '戦闘！シロナ', 'ポケットモンスター ブラック・ホワイト', '戦闘')
    monkeypatch.setattr(intro, 'load_tracks', lambda: [champion, other, cynthia])

    assert intro.judge(champion, 'dpシロナ') == intro.CORRECT
    assert intro.judge(cynthia, 'BWシロナ') == intro.CORRECT
    assert intro.judge(champion, 'シロナ') == intro.AMBIGUOUS  # DPにもBWにも居る
    assert intro.judge(other, 'bwチャンピオン') == intro.CORRECT
    assert intro.judge(other, 'アデク') == intro.CORRECT  # BWだけ


def test_one_trainer_with_several_songs_needs_the_full_name(monkeypatch):
    sv = 'ポケットモンスター スカーレット・バイオレット+ゼロの秘宝'
    bw = 'ポケットモンスター ブラック・ホワイト'
    hgss = 'ポケモン ハートゴールド&ソウルシルバー'
    nemona = intro.IntroTrack('e1', '戦闘！ネモ', sv, '戦闘')
    champion = intro.IntroTrack('e2', '戦闘！チャンピオンネモ', sv, '戦闘')
    battle_n = intro.IntroTrack('e3', '戦闘！N', bw, '戦闘')
    final_n = intro.IntroTrack('e4', '決戦！N', bw, '戦闘')
    kanto = intro.IntroTrack('e5', '戦闘！ジムリーダー（カントー）', hgss, '戦闘')
    johto = intro.IntroTrack('e6', '戦闘！ジムリーダー（ジョウト）', hgss, '戦闘')
    johto_copy = intro.IntroTrack('e7', '戦闘！ジムリーダー（ジョウト） (2)', hgss, '戦闘')
    monkeypatch.setattr(intro, 'load_tracks', lambda: [
        nemona, champion, battle_n, final_n, kanto, johto, johto_copy])

    assert intro.judge(nemona, 'ネモ') == intro.CORRECT
    assert intro.judge(champion, 'ネモ') == intro.AMBIGUOUS_SONG  # 決戦かチャンピオンまで言う
    assert intro.judge(champion, 'チャンピオンネモ') == intro.CORRECT
    assert intro.judge(champion, 'svちゃんぴおんねも') == intro.CORRECT
    # 最終戦は「決戦」まで言う。名前だけなら、ふだんの戦闘曲
    assert intro.judge(battle_n, 'N') == intro.CORRECT
    assert intro.judge(battle_n, 'bwN') == intro.CORRECT
    assert intro.judge(final_n, 'N') == intro.AMBIGUOUS_SONG  # 聞き返す
    assert intro.judge(final_n, 'bwN') == intro.AMBIGUOUS_SONG
    assert intro.judge(champion, '決戦ネモ') == intro.CORRECT
    assert intro.judge(champion, 'sv決戦ネモ') == intro.CORRECT
    assert intro.judge(nemona, '決戦ネモ') == intro.WRONG
    # ふだんの戦闘曲が無い相手は、名前だけで決まる
    only = intro.IntroTrack('e8', '決戦！ダイゴ', 'ポケモン ルビー&サファイア', '戦闘')
    monkeypatch.setattr(intro, 'load_tracks', lambda: [
        nemona, champion, battle_n, final_n, kanto, johto, johto_copy, only])
    assert intro.judge(only, 'ダイゴ') == intro.CORRECT
    assert intro.judge(only, '決戦ダイゴ') == intro.CORRECT
    assert intro.judge(final_n, '決戦N') == intro.CORRECT
    assert intro.judge(final_n, 'bwけっせんN') == intro.CORRECT
    assert intro.judge(final_n, '戦闘N') == intro.WRONG
    assert intro.judge(battle_n, 'BW戦闘N') == intro.CORRECT
    # 地方ちがいは別の曲、(2) などの別バージョンは同じ曲
    assert intro.judge(johto, 'ジムリーダー') == intro.AMBIGUOUS_SONG
    assert intro.judge(johto, 'ジョウトジムリーダー') == intro.CORRECT
    assert intro.judge(johto_copy, 'hgssジムリーダージョウト') == intro.CORRECT
    assert intro.judge(kanto, 'ジョウトジムリーダー') == intro.WRONG
    # 「決戦！スグリ」が別にあるなら、決戦スグリ はそちら。チャンピオンは曲名どおりに答える
    battle = intro.IntroTrack('e9', '戦闘！スグリ', sv, '戦闘')
    final = intro.IntroTrack('e10', '決戦！スグリ', sv, '戦闘')
    top = intro.IntroTrack('e11', '戦闘！チャンピオンスグリ', sv, '戦闘')
    monkeypatch.setattr(intro, 'load_tracks', lambda: [battle, final, top, only])
    assert intro.judge(battle, 'スグリ') == intro.CORRECT
    assert intro.judge(final, '決戦スグリ') == intro.CORRECT
    assert intro.judge(top, '決戦スグリ') == intro.AMBIGUOUS_SONG
    assert intro.judge(top, 'スグリ') == intro.AMBIGUOUS_SONG
    assert intro.judge(top, 'チャンピオンスグリ') == intro.CORRECT


def test_the_bare_name_means_the_song_without_a_region(monkeypatch):
    sv = 'ポケットモンスター スカーレット・バイオレット+ゼロの秘宝'
    wild = intro.IntroTrack('f1', '戦闘！野生ポケモン', sv, '戦闘')
    galar = intro.IntroTrack('f2', '戦闘！野生ポケモン（ガラル）', sv, '戦闘')
    legend = intro.IntroTrack('f3', '戦闘！伝説のポケモン（イッシュ）', sv, '戦闘')
    monkeypatch.setattr(intro, 'load_tracks', lambda: [wild, galar, legend])

    assert intro.judge(wild, 'やせい') == intro.CORRECT
    assert intro.judge(wild, 'sv野生ポケモン') == intro.CORRECT
    assert intro.judge(galar, '野生ポケモン') == intro.AMBIGUOUS_SONG
    assert intro.judge(galar, 'ガラルの野生ポケモン') == intro.CORRECT
    assert intro.judge(galar, 'svガラル野生') == intro.CORRECT
    # 地方つきの曲しか無ければ、地方を省いても決まる
    assert intro.judge(legend, 'sv伝説') == intro.CORRECT


def test_a_reused_song_can_be_answered_with_the_work_it_plays_in(monkeypatch):
    brain = intro.IntroTrack(
        'h1', '戦闘！フロンティアブレーン(シンオウ)', 'ポケットモンスター プラチナ', '戦闘')
    hoenn = intro.IntroTrack(
        'h2', '戦闘！フロンティアブレーン(ホウエン)', 'ポケットモンスター エメラルド', '戦闘')
    legend = intro.IntroTrack(
        'h3', '戦闘！ディアルガ・パルキア', 'ポケモン ダイヤモンド&パール', '戦闘')
    own = intro.IntroTrack(
        'h4', '戦闘！ライバル', 'ポケモン ハートゴールド&ソウルシルバー', '戦闘')
    tracks = [brain, hoenn, legend, own]
    monkeypatch.setattr(intro, 'load_tracks', lambda: tracks)

    # 音源はプラチナだけだが、HGSSでも流れるのでHGSSの略称でも正解
    assert intro.judge(brain, 'HGSSフロンティアブレーン') == intro.CORRECT
    assert intro.judge(brain, 'hgssネジキ') == intro.CORRECT
    assert intro.judge(brain, 'Ptフロンティアブレーン') == intro.CORRECT
    assert intro.judge(brain, 'ネジキ') == intro.CORRECT
    assert intro.judge(brain, 'フロンティアブレーン') == intro.AMBIGUOUS  # エメラルドにもある
    assert intro.judge(hoenn, 'HGSSフロンティアブレーン') == intro.WRONG
    # 別名は、それが付いた作品の略称とだけ組み合わせる
    steven = intro.IntroTrack('h5', '決戦！ダイゴ', 'ポケモン ルビー&サファイア', '戦闘')
    remake = intro.IntroTrack(
        'h6', '決戦! ダイゴ', 'ポケモン オメガルビー・アルファサファイア', '戦闘')
    tracks += [steven, remake]
    assert intro.judge(steven, 'エメラルドのミクリ') == intro.CORRECT
    assert intro.judge(steven, 'ミクリ') == intro.CORRECT
    assert intro.judge(steven, 'RSEダイゴ') == intro.CORRECT
    assert intro.judge(remake, 'ORASダイゴ') == intro.CORRECT
    assert intro.judge(remake, 'ORASミクリ') == intro.UNKNOWN  # ORASでは戦わない
    assert intro.judge(steven, 'ORASミクリ') == intro.UNKNOWN
    assert intro.judge(legend, 'ORASシンオウ伝説3') == intro.UNKNOWN  # USUMでの呼び名
    assert intro.judge(legend, 'USUMシンオウ伝説3') == intro.CORRECT
    assert intro.judge(legend, 'ORASディアルガ') == intro.CORRECT  # 曲はORASでも流れる
    # ゲーム内の曲名表記（USUMレーティングバトル）
    assert intro.judge(legend, 'シンオウ伝説3') == intro.CORRECT
    assert intro.judge(legend, 'USUMディアルガ') == intro.CORRECT
    # 作品での絞り込みには、流れる作品も入る
    ids = lambda names: [t.id for t in intro.filter_tracks(names)]  # noqa: E731
    assert ids(['ポケモン ハートゴールド&ソウルシルバー']) == ['h1', 'h4']
    assert ids(['ポケットモンスター プラチナ']) == ['h1']
    assert [work for work, _ in brain.appearances] == ['HGSS']


def test_people_can_be_answered_by_name(monkeypatch):
    boss = intro.IntroTrack('d1', '戦闘！ギンガ団ボス（Ver. 1.0）', 'ポケモン ダイヤモンド&パール', '戦闘')
    remake = intro.IntroTrack(
        'd2', '戦闘！ギンガ団ボス',
        'ポケットモンスター ブリリアントダイヤモンド・シャイニングパール', '戦闘')
    leader = intro.IntroTrack(
        'd3', '戦闘! アクア・マグマ団のリーダー', 'ポケモン ルビー&サファイア', '戦闘')
    pwt = intro.IntroTrack(
        'd4', '戦闘! チャンピオン(シンオウ)', 'ポケモンブラック2・ホワイト2', '戦闘')
    monkeypatch.setattr(intro, 'load_tracks', lambda: [boss, remake, leader, pwt])

    assert intro.judge(boss, 'dpアカギ') == intro.CORRECT
    assert intro.judge(boss, 'アカギ') == intro.AMBIGUOUS  # DPとBDSP
    assert intro.judge(boss, 'DPぎんがだんのぼす') == intro.CORRECT
    assert intro.judge(leader, 'マツブサ') == intro.CORRECT
    assert intro.judge(leader, 'rsアオギリ') == intro.CORRECT
    assert intro.judge(pwt, 'bw2シロナ') == intro.CORRECT


def test_the_filename_hides_the_track_and_resolves_back(library):
    first = intro.intro_filename('a1', 'abc123')
    second = intro.intro_filename('a1', 'def456')

    assert first != second and 'a1' not in first.split('-')
    assert intro.track_from_message(_intro_message('b2')).title == 'テーブルシティ'
    assert intro.track_from_message(FakeMessage(author=None)) is None


def test_intro_quiz_posts_a_clip(library):
    session = _session()
    channel = FakeChannel()

    asyncio.run(session.post(channel))

    _args, kwargs = channel.sent[0]
    assert intro.INTRO_FILENAME_RE.match(kwargs['file'].filename)
    assert kwargs['embed'].title == 'イントロクイズ'
    assert kwargs['embed'].footer.text == 'No.26 ポケモンクイズ - introq'
    description = kwargs['embed'].description
    assert '添付のイントロ' in description
    assert '`DP野生`' in description and '`SV四天王`' in description  # 人名以外の例
    assert '`ヒント`' in description and '`ギブ`' in description
    assert kwargs['view'] is None


def test_intro_quiz_respects_the_filters(library):
    state = quiz_module.QuizState()
    state.intro_works = ['スカーレット・バイオレット']
    state.intro_categories = ['フィールド']
    channel = FakeChannel()

    for _ in range(5):
        asyncio.run(_session(state).post(channel))

    for _args, kwargs in channel.sent:
        attachment = type('A', (), {'filename': kwargs['file'].filename})()
        message = FakeMessage(author=None, attachments=[attachment])
        assert intro.track_from_message(message).id == 'b2'


def test_intro_quiz_without_matching_tracks_explains(library):
    state = quiz_module.QuizState()
    state.intro_works = ['ソード・シールド']
    state.intro_categories = ['その他']
    channel = FakeChannel()

    asyncio.run(_session(state).post(channel))

    assert '出題条件に合う曲がありません' in channel.sent[0][0][0]


def test_intro_quiz_plays_in_the_voice_channel(monkeypatch, library):
    monkeypatch.setattr(session_module, '_audio_source', lambda path: str(path))
    channel = FakeChannel()
    guild = FakeVoiceGuild()

    asyncio.run(_session().post(channel, voiceChannel=FakeVoiceChannel(guild)))

    assert len(guild.voice_client.played) == 1
    assert guild.voice_client.played[0].endswith('.ogg')
    kwargs = channel.sent[0][1]
    assert 'ボイスチャンネルで流します' in kwargs['embed'].description
    assert any(getattr(child, 'custom_id', None) == session_module.CRY_REPLAY_BUTTON_ID
               for child in kwargs['view'].children)


def test_the_replay_button_plays_the_intro_again(monkeypatch, library):
    monkeypatch.setattr(session_module, '_audio_source', lambda path: str(path))
    guild = FakeVoiceGuild()
    guild.voice_client = FakeVoiceClient(FakeVoiceChannel(guild))
    interaction = FakeButtonInteraction(_intro_message('a2'), guild)

    asyncio.run(quiz_module.Quiz(FakeBot()).on_interaction(interaction))

    assert guild.voice_client.played == [str(library / 'clips' / 'a2.ogg')]
    assert interaction.response.messages[0][0] == '再生1回目'


class AnswerMessage(discord.Message):
    """isinstance を通しつつ、回答に必要なものだけ持つ。"""

    def __init__(self, content, question):
        self.content = content
        self.author = FakeUser()
        self.reference = type('R', (), {'resolved': question})()
        self.answered_at = question.created_at + datetime.timedelta(seconds=7)
        self.reactions_added = []
        self.replies = []

    @property
    def created_at(self):  # 本物はidから求めるので差し替える
        return self.answered_at

    async def add_reaction(self, emoji):
        self.reactions_added.append(emoji)

    async def remove_reaction(self, emoji, user):
        self.reactions_added.remove(emoji)

    async def reply(self, text):
        self.replies.append(text)


class QuestionMessage:
    def __init__(self, track_id='a1'):
        embed = discord.Embed(title='イントロクイズ')
        embed.set_footer(text='No.26 ポケモンクイズ - introq')
        self.embeds = [embed]
        self.attachments = [type('A', (), {
            'filename': intro.intro_filename(track_id, 'abc123')})()]
        self.created_at = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        self.id = 5
        self.guild = None
        # 取り直した投稿は別物（開示前のフッターのまま）として返す
        fetched = type('M', (), {'embeds': [embed.copy()]})()
        self.channel = FakeChannel(resolved=fetched)
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


def _answer(monkeypatch, content, track_id='a1'):
    reports, logs = [], []
    monkeypatch.setattr(session_module.ub, 'report',
                        lambda *args: reports.append(args) or 1)
    monkeypatch.setattr(session_module.save, 'add_quiz_log',
                        lambda *args, **kwargs: logs.append(args))
    state = quiz_module.QuizState()
    state.bakusoku_mode = False
    question = QuestionMessage(track_id)
    answer = AnswerMessage(content, question)
    asyncio.run(_session(state).try_response(answer))
    return question, answer, reports, logs


def test_the_right_title_is_correct(monkeypatch, library):
    question, answer, reports, logs = _answer(monkeypatch, '剣盾じむりーだー')

    assert answer.reactions_added == ['⭕']
    embed = question.edits[-1]['embed']
    assert embed.description == 'こたえ: 戦闘！ジムリーダー（ソード・シールド）'
    assert embed.footer.text.endswith('(done)')
    assert 'attachments' not in question.edits[-1]  # 添付（イントロ）は消さない
    assert reports[0][1] == 'introq正答'
    assert logs[0][2] == '正答'


def test_an_alias_is_correct(monkeypatch, library):
    _question, answer, reports, _logs = _answer(monkeypatch, 'ジムチャレンジ')

    assert answer.reactions_added == ['⭕']
    assert reports[0][1] == 'introq正答'


def test_an_answer_without_the_work_asks_for_it(monkeypatch, library):
    question, answer, reports, logs = _answer(monkeypatch, 'ジムリーダー')

    assert answer.reactions_added == ['❓']
    assert '作品の略称' in answer.replies[0]
    assert question.edits == [] and reports == []  # 開示も戦績もまだ
    assert logs[0][2] is None


def test_an_answer_that_fits_several_songs_lists_them(monkeypatch, library):
    # SVの「野生ポケモン」は Ver. 1.0 と同じ曲。別の曲を足して、決まらない状態にする
    extra = intro.IntroTrack('x1', '決戦！テーブルシティ', 'スカーレット・バイオレット', 'フィールド')
    tracks = intro.load_tracks() + [extra]
    monkeypatch.setattr(intro, 'load_tracks', lambda: tracks)
    assert intro.candidates(extra, 'SVテーブルシティ') == ['テーブルシティ', '決戦！テーブルシティ']

    monkeypatch.setattr(intro, 'track_from_message', lambda message: extra)
    _question, answer, reports, _logs = _answer(monkeypatch, 'SVテーブルシティ')

    assert answer.reactions_added == ['❓']
    assert '`テーブルシティ`／`決戦！テーブルシティ`' in answer.replies[0]
    assert reports == []


def test_another_title_is_wrong(monkeypatch, library):
    question, answer, reports, _logs = _answer(monkeypatch, '1番道路')

    assert answer.reactions_added == ['❌']
    assert question.edits == []  # まだ開示しない
    assert reports[0][1] == 'introq誤答'


def test_an_unknown_title_is_not_counted(monkeypatch, library):
    _question, answer, reports, logs = _answer(monkeypatch, 'しらないきょく')

    assert answer.reactions_added == ['❓']
    assert '曲リストにありません' in answer.replies[0]
    assert reports == []
    assert logs[0][2] is None


def test_giving_up_shows_the_answer(monkeypatch, library):
    question, answer, _reports, _logs = _answer(monkeypatch, 'ギブ', track_id='b2')

    assert answer.replies == ['答えはテーブルシティ（スカーレット・バイオレット）でした']
    assert 'テーブルシティ（スカーレット・バイオレット）' in question.edits[-1]['embed'].description


def test_the_hint_is_the_work(library):
    for word in ('ヒント', '作品'):
        q = _session()
        q.rm, q.qm, q.quizEmbed = FakeRM(), FakeQM(), discord.Embed()
        q.ansZero = intro.load_tracks()[0]
        q.ansText = word

        asyncio.run(q._QuizSession__hint())
        asyncio.run(q._QuizSession__hint())  # 2回目も同じ答え（欄は増やさない）

        assert q.rm.replies == ['作品はソード・シールドです'] * 2
        assert [field.name for field in q.quizEmbed.fields] == ['作品']
        assert 'attachments' not in q.qm.edits[-1]


def test_other_hint_words_are_answers(monkeypatch, library):
    # 頭文字・文字数・区分のヒントはやめた。ヒントの言葉ではないので、ふつうの回答として扱う
    _question, answer, _reports, _logs = _answer(monkeypatch, '頭文字')

    assert answer.reactions_added == ['❓']
    assert '曲リストにありません' in answer.replies[0]


def _introdata(cog, channel, words=''):
    message = FakeMessage(author=FakeUser(), content=f'/introdata {words}'.strip(),
                          channel=channel)
    asyncio.run(cog.on_message(message))
    return channel.sent[-1]


def test_introdata_sets_and_clears_the_filters(library):
    cog = quiz_module.Quiz(FakeBot())
    channel = FakeChannel()

    args, kwargs = _introdata(cog, channel, 'せんとう ソード')
    assert cog.state.intro_categories == ['戦闘']
    assert cog.state.intro_works == ['ソード・シールド']
    assert '変更されました' in args[0]
    assert '該当曲数: 1曲' in kwargs['embed'].description

    _introdata(cog, channel, 'フィールド')  # 区分だけ置き換える
    assert cog.state.intro_categories == ['フィールド']
    assert cog.state.intro_works == ['ソード・シールド']

    _introdata(cog, channel, '作品')
    assert cog.state.intro_works == []
    assert cog.state.intro_categories == ['フィールド']

    _introdata(cog, channel, 'リセット')
    assert cog.state.intro_categories == []


def test_introdata_lists_the_works_and_reports_unknown_words(library):
    cog = quiz_module.Quiz(FakeBot())
    channel = FakeChannel()

    args, kwargs = _introdata(cog, channel)
    assert '現在の' in args[0]
    assert 'ソード・シールド（2曲）' in kwargs['embed'].fields[0].value
    assert 'スカーレット・バイオレット（5曲）' in kwargs['embed'].fields[0].value

    args, _kwargs = _introdata(cog, channel, 'ダイヤモンド')
    assert args[0] == '作品が見つかりません: ダイヤモンド'
    assert cog.state.intro_works == []


class FakeResponse:
    def __init__(self):
        self.messages = []

    async def send_message(self, content=None, **kwargs):
        self.messages.append((content, kwargs))


class FakeInteraction:
    def __init__(self, channel):
        self.channel = channel
        self.response = FakeResponse()


def test_q_has_no_options_for_one_quiz_only():
    # /q は全クイズ共用。イントロクイズの絞り込みは /introdata だけで行う
    assert [parameter.name for parameter in quiz_module.Quiz.q.parameters] == ['quizname']


def test_q_posts_the_intro_quiz_with_the_filters_from_introdata(library):
    cog = quiz_module.Quiz(FakeBot())
    channel = FakeChannel()
    _introdata(cog, channel, 'SV フィールド')

    asyncio.run(cog.q.callback(cog, FakeInteraction(channel), 'イントロクイズ'))

    kwargs = channel.sent[-1][1]
    assert kwargs['embed'].title == 'イントロクイズ'
    attachment = type('A', (), {'filename': kwargs['file'].filename})()
    assert intro.track_from_message(
        FakeMessage(author=None, attachments=[attachment])).id == 'b2'


def _channel_answer(monkeypatch, content, footer='No.26 ポケモンクイズ - introq'):
    channel = FakeVoiceChannel()
    embed = discord.Embed()
    embed.set_footer(text=footer)
    channel.messages.append(
        FakeMessage(author=FakeUser(), embeds=[embed], channel=channel))
    message = FakeMessage(author=FakeUser(), content=content, channel=channel)
    names = []

    class FakeSession:
        def __init__(self, bot, name, state):
            names.append(name)

        async def try_response(self, response):
            pass

    monkeypatch.setattr(quiz_module, 'QuizSession', FakeSession)
    asyncio.run(quiz_module.Quiz(FakeBot()).on_message(message))
    return names


def test_a_title_in_the_voice_text_chat_answers_the_intro_quiz(monkeypatch, library):
    assert _channel_answer(monkeypatch, 'てーぶるしてぃ') == ['introq']


def test_chatter_and_pokemon_names_do_not_answer_the_intro_quiz(monkeypatch, library):
    assert _channel_answer(monkeypatch, 'なにこれ') == []
    assert _channel_answer(monkeypatch, 'リザードン') == []


def test_a_title_does_not_answer_the_cry_quiz(monkeypatch, library):
    assert _channel_answer(
        monkeypatch, 'テーブルシティ', footer='No.26 ポケモンクイズ - cryq') == []


def test_classify_guesses_the_category():
    assert build.classify('戦闘！チャンピオン') == '戦闘'
    assert build.classify('VS ライバル') == '戦闘'
    assert build.classify('頂への挑戦', 'vs チャンピオン') == '戦闘'  # コメントも見る
    assert build.classify('201番道路（昼）') == 'フィールド'
    assert build.classify('コトブキシティ') == 'フィールド'
    assert build.classify('エンディング') == 'その他'
    # 実際のアルバムの曲名
    assert build.classify('戦い(VSジムリーダー)') == '戦闘'
    assert build.classify('ラストバトル(VSライバル)') == '戦闘'
    assert build.classify('ほら穴での戦闘') == '戦闘'
    assert build.classify('戦闘！ジムリーダー～ジムリーダーに勝利！') == '戦闘'
    assert build.classify('勝利(VSトレーナー)') == 'その他'  # 勝利のジングル
    assert build.classify('チャンピオンに勝利！') == 'その他'
    assert build.classify('テラレイドバトルで勝利！') == 'その他'
    assert build.classify('201ばんどうろ(昼)') == 'フィールド'
    assert build.classify('トキワへの道－マサラより') == 'フィールド'
    assert build.classify('おつきみ山のどうくつ') == 'フィールド'
    assert build.classify('ポケモンセンター') == 'その他'
    assert build.classify('決戦！ポケモンリーグ') == 'フィールド'  # リーグの建物の曲
    # 戦闘施設のロビーやジングルは戦闘曲にしない
    for title in ('バトルタワー', 'バトルタワーうけつけ', 'バトルポイントをもらった！',
                  'バトルルーレットでBPゲット！', 'バトルサブウェイ', 'Battle Tower (Johto)',
                  'タイトルデモ2 〜ダブルバトル〜', 'バトルロイヤルで結果発表!',
                  '戦いの予兆：オヤブン', '戦闘プログラム起動'):
        assert build.classify(title) != '戦闘', title
    for title in ('戦闘！バトルタワー', '戦闘! バトルツリーボス', 'テラレイドバトル！',
                  'マックスレイドバトル！', 'LAST BATTLE -N^n mix-', 'Battle! Trainer S',
                  '頂上決戦!', '戦い：オヤブン', '戦闘！フロンティアブレーン(シンオウ)'):
        assert build.classify(title) == '戦闘', title


def test_the_work_name_drops_the_platform_and_the_collection_suffix():
    assert build.tidy_work(
        'ニンテンドーDS ポケモン ダイヤモンド&パール スーパーミュージックコレクション'
    ) == 'ポケモン ダイヤモンド&パール'
    assert build.tidy_work(
        'Nintendo Switch ポケモン ソード・シールド＋エキスパンションパス '
        'スーパーミュージック・コレクション') == 'ポケモン ソード・シールド＋エキスパンションパス'
    assert build.tidy_work(
        'GBA ポケモン ルビー&サファイア ミュージック・スーパーコンプリート'
    ) == 'ポケモン ルビー&サファイア'
    assert build.tidy_work('ポケモンコロシアム') == 'ポケモンコロシアム'


def _album(tmp_path):
    album = tmp_path / 'album' / 'ソード・シールド'
    album.mkdir(parents=True)
    (album / '01 戦闘！ジムリーダー.mp3').write_bytes(b'x')
    (album / '02 1番道路.mp3').write_bytes(b'x')
    (album / 'cover.jpg').write_bytes(b'x')
    other = tmp_path / 'album' / 'べつのアルバム'
    other.mkdir()
    (other / '01 うた.mp3').write_bytes(b'x')
    trash = tmp_path / 'album' / '.trash' / 'ソード・シールド'
    trash.mkdir(parents=True)
    (trash / '99 すてた曲.mp3').write_bytes(b'x')
    return tmp_path / 'album'


def test_build_cuts_clips_and_writes_the_manifest(monkeypatch, tmp_path):
    cuts = []
    # 「うた」は --match で外れ、ジングルは短いので外れる
    monkeypatch.setattr(build, 'read_tags', lambda path: {
        'duration': '3.2' if 'ジングル' in path.name else '95.0'})
    (_album(tmp_path) / 'ソード・シールド' / '03 ジングル.mp3').write_bytes(b'x')
    monkeypatch.setattr(
        build, 'cut',
        lambda source, target, seconds, bitrate: (
            cuts.append((source.name, seconds)), target.write_bytes(b'ogg')))
    output = tmp_path / 'intro'

    assert build.main([str(tmp_path / 'album'), '--match', 'ソード',
                       '--output', str(output)]) == 0

    rows = list(build.read_manifest(output / 'manifest.csv').values())
    assert [(row['title'], row['work'], row['category']) for row in rows] == [
        ('戦闘！ジムリーダー', 'ソード・シールド', '戦闘'),
        ('1番道路', 'ソード・シールド', 'フィールド'),
    ]
    assert cuts == [('01 戦闘！ジムリーダー.mp3', 10), ('02 1番道路.mp3', 10)]
    assert all((output / 'clips' / f"{row['id']}.ogg").exists() for row in rows)

    # 作り直しても、作成済みは切り出さず、手で直した行は保つ
    rows[1]['category'] = 'その他'
    rows[1]['aliases'] = 'いちばんどうろ'
    build.write_manifest(output / 'manifest.csv', rows)
    assert build.main([str(tmp_path / 'album'), '--match', 'ソード',
                       '--output', str(output)]) == 0
    assert len(cuts) == 2
    kept = list(build.read_manifest(output / 'manifest.csv').values())[1]
    assert (kept['category'], kept['aliases']) == ('その他', 'いちばんどうろ')


def test_the_sheet_round_trips_and_ignores_editor_decorations(monkeypatch, tmp_path, library):
    import tools.intro_sheet as sheet
    monkeypatch.setattr(intro, 'ALIASES_PATH', tmp_path / 'aliases.csv')
    monkeypatch.setattr(intro, 'APPEARANCES_PATH', tmp_path / 'appearances.csv')
    intro.reset_answer_lists()
    path = tmp_path / 'sheet.md'
    assert sheet.export(path) == 0
    text = path.read_text(encoding='utf-8')
    # Nextcloudのエディタは列をそろえ、コピーした区切りにコードの飾りを付けることがある
    text = text.replace('| テーブルシティ |  |  |  |  |',
                        '| テーブルシティ   |    | まち`、パルデアの都` | 剣盾（ガラルの都） | あとで確認 |')
    path.write_text(text, encoding='utf-8')

    assert sheet.import_(path) == 0
    city = next(t for t in intro.load_tracks() if t.id == 'b2')
    assert city.listed_aliases == ('まち', 'パルデアの都')
    assert city.appearances == (('剣盾', ('ガラルの都',)),)
    assert intro.judge(city, 'svぱるであの都') == intro.CORRECT
    assert intro.judge(city, '剣盾ガラルの都') == intro.CORRECT
    assert intro.judge(city, '剣盾パルデアの都') == intro.UNKNOWN

    again = tmp_path / 'again.md'
    assert sheet.export(again, path) == 0
    assert 'まち／パルデアの都 | 剣盾（ガラルの都） | あとで確認 |' in again.read_text(encoding='utf-8')


def test_build_moves_tracks_to_another_work(tmp_path):
    rules = tmp_path / 'works.csv'
    rules.write_text(
        '# アルバム,曲名,Disc,作品,曲名\n'
        'ブラック2・ホワイト2,戦闘！ギラティナ,,ポケットモンスター プラチナ,\n'
        'オメガルビー,,5,-,\n'
        'ウルトラサン,戦闘！アローラチャンピオン,,,頂上決戦！ハウ\n'
        'LEGENDS Z-A,,,Pokémon LEGENDS Z-A,\n', encoding='utf-8')
    overrides = build.work_overrides(rules)
    album = 'ニンテンドーDS ポケモンブラック2・ホワイト2 スーパーミュージックコンプリート'

    def work(album, title, disc=''):
        return build.describe(
            tmp_path / 'x.mp3', {'title': title, 'album': album, 'disc': disc},
            overrides)['work']

    assert work(album, '戦闘! ギラティナ') == 'ポケットモンスター プラチナ'  # 表記ゆれは無視
    assert work(album, '戦闘！N') == 'ポケモンブラック2・ホワイト2'
    assert work('Pokémon LEGENDS Z-A M次元ラッシュ', 'なんでも') == 'Pokémon LEGENDS Z-A'
    # Discで選んで出題から外す（他作品の再録）
    oras = 'ニンテンドー3DS ポケモン オメガルビー・アルファサファイア スーパーミュージックコンプリート'
    assert work(oras, '戦闘! ジムリーダー', '5/6') == build.EXCLUDE
    assert work(oras, '戦闘! ジムリーダー', '2/6') == 'ポケモン オメガルビー・アルファサファイア'
    # 改名しても区分は元の曲名で決める
    row = build.describe(tmp_path / 'x.mp3', {
        'title': '戦闘！アローラチャンピオン',
        'album': 'ポケットモンスター ウルトラサン・ウルトラムーン'}, overrides)
    assert (row['title'], row['category']) == ('頂上決戦！ハウ', '戦闘')


def test_a_listed_alias_may_cover_several_songs(monkeypatch):
    la = 'Pokémon LEGENDS アルセウス'
    first = intro.IntroTrack('g1', '戦い：アルセウス', la, '戦闘')
    second = intro.IntroTrack('g2', '戦い：アルセウス2', la, '戦闘', ('アルセウス',))
    people = intro.IntroTrack('g3', '戦い：ヒスイの人', la, '戦闘', ('トレーナー',))
    captains = intro.IntroTrack('g4', '戦い：ヒスイの人2', la, '戦闘', ('キャプテン', '団長'))
    monkeypatch.setattr(intro, 'load_tracks', lambda: [first, second, people, captains])

    assert intro.judge(second, 'LAアルセウス') == intro.CORRECT
    assert intro.judge(second, 'laあるせうす2') == intro.CORRECT  # 玄人向け
    assert intro.judge(first, 'LAアルセウス') == intro.CORRECT
    assert intro.judge(first, 'LAアルセウス2') == intro.WRONG
    assert intro.judge(people, 'LAトレーナー') == intro.CORRECT
    assert intro.judge(captains, '団長') == intro.CORRECT
    assert intro.judge(captains, 'LAトレーナー') == intro.WRONG


def test_build_can_add_albums_to_the_list(monkeypatch, tmp_path):
    monkeypatch.setattr(build, 'read_tags', lambda path: {'duration': '95.0'})
    monkeypatch.setattr(build, 'cut', lambda source, target, seconds, bitrate:
                        target.write_bytes(b'ogg'))
    output = tmp_path / 'intro'
    for name in ('ソード', 'べつの'):
        assert build.main([str(_album(tmp_path) if name == 'ソード' else tmp_path / 'album'),
                           '--match', name, '--append', '--output', str(output)]) == 0

    titles = [row['title'] for row in build.read_manifest(output / 'manifest.csv').values()]
    assert sorted(titles) == ['1番道路', 'うた', '戦闘！ジムリーダー']


def test_build_uses_the_tags_when_present(monkeypatch, tmp_path):
    album = _album(tmp_path)

    row = build.describe(next(album.rglob('*.mp3')), {
        'title': 'テーブルシティ',
        'album': 'ポケットモンスター スカーレット・バイオレット スーパーミュージック・コレクション'})

    assert (row['title'], row['work'], row['category']) == (
        'テーブルシティ', 'ポケットモンスター スカーレット・バイオレット', 'フィールド')
