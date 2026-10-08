"""ChordPro（`.cho`・`.chordpro`・`.pro`、` ```chordpro `フェンス）の構文解析（#440）。

描画はここに置かない。解析結果（`Song`）を、HTML出力とTypst出力が、それぞれ描く。
他の図と違い、外部ツールもブラウザも使わない。文法が小さく、自前のパーサで足りるため。

対応する範囲は、最小に絞っている（#440）。
- 指令: `title`/`t`、`subtitle`/`st`、`artist`、`comment`/`c`、`comment_italic`/`ci`、`comment_box`/`cb`、
  `start_of_chorus`/`soc`、`start_of_verse`/`sov`、`start_of_bridge`/`sob`、`start_of_tab`/`sot`（と、それぞれの`end_of_*`）
- 行内のコード: `[Am7]`。`[*注記]`は、コードではなく注記（先頭の`*`は表示しない）
- 行頭が`#`の行は、コメントとして捨てる
- `key`（原曲のキー）・`capo`（カポ）・`transpose`（半音で転調。#442）。転調の規則は、chordpro_transpose.py
未対応の指令（`define`など）は、捨てて、`Song.warnings`に残す。黙って捨てると、書いたものが消えたことに気づけないため。
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from text_compositor import chordpro_transpose as transpose

LANGS = ('chordpro',)
FILE_EXTS = ('.cho', '.chordpro', '.pro')

# 区間の種類（別名を、正式名に直す）。`tab`の中身は、コードを探さず、等幅のまま保つ。
_SECTION_STARTS = {
    'start_of_chorus': 'chorus', 'soc': 'chorus',
    'start_of_verse': 'verse', 'sov': 'verse',
    'start_of_bridge': 'bridge', 'sob': 'bridge',
    'start_of_tab': 'tab', 'sot': 'tab',
}
_SECTION_ENDS = {
    'end_of_chorus': 'chorus', 'eoc': 'chorus',
    'end_of_verse': 'verse', 'eov': 'verse',
    'end_of_bridge': 'bridge', 'eob': 'bridge',
    'end_of_tab': 'tab', 'eot': 'tab',
}
_META = {'title': 'title', 't': 'title', 'subtitle': 'subtitle', 'st': 'subtitle', 'artist': 'artist'}
_COMMENTS = {'comment': 'comment', 'c': 'comment', 'comment_italic': 'italic', 'ci': 'italic',
             'comment_box': 'box', 'cb': 'box'}

_DIRECTIVE_RE = re.compile(r'^\s*\{\s*([A-Za-z_]+)\s*(?:[:\s]\s*(.*?))?\s*\}\s*$')
_CHORD_RE = re.compile(r'\[([^\]]*)\]')


@dataclass
class Segment:
    """コード1つと、その直後の歌詞の断片。先頭より前に歌詞があるときは、chordが空の断片になる。"""
    chord: str
    lyric: str
    annotation: bool = False   # `[*注記]`。コードではない


@dataclass
class Line:
    """歌詞1行。tab区間の行は、segmentsを持たず、textだけを持つ。"""
    segments: List[Segment] = field(default_factory=list)
    text: Optional[str] = None
    lineno: int = 0   # 入力での行番号（警告用）
    shift: int = 0    # この行に効いている`{transpose}`（半音）

    @property
    def has_chords(self) -> bool:
        return any(s.chord for s in self.segments)


@dataclass
class Comment:
    text: str
    style: str   # 'comment' | 'italic' | 'box'


@dataclass
class Blank:
    """空行（段落の区切り）。"""


@dataclass
class Section:
    kind: str                # 'chorus' | 'verse' | 'bridge' | 'tab'
    label: str = ''          # `{start_of_chorus: Chorus}`の、`Chorus`
    items: list = field(default_factory=list)   # Line・Comment・Blank


@dataclass
class Song:
    title: str = ''
    subtitle: str = ''
    artist: str = ''
    key: str = ''                # `{key}`。原曲のキー
    play_key: str = ''           # `{key}`を、`{transpose}`で動かしたキー。転調しないとき、または、キーが読めないときは、空
    capo: Optional[int] = None   # `{capo}`。表示するだけで、コードは変えない
    shift: int = 0               # 見出しに使う、転調の量（最初のコードの行に効いている`{transpose}`）
    items: list = field(default_factory=list)   # Line・Comment・Blank・Section
    warnings: List[Tuple[int, str]] = field(default_factory=list)   # (入力での行番号, 内容)


def parse_line(text: str) -> Line:
    """歌詞1行を、(コード, 直後の歌詞)の並びにする。`[C]Hello [G]world`→(C, "Hello ")・(G, "world")。"""
    segments: List[Segment] = []
    pos = 0
    chord, annotation = '', False
    for m in _CHORD_RE.finditer(text):
        lyric = text[pos:m.start()]
        if lyric or chord:
            segments.append(Segment(chord, lyric, annotation))
        raw = m.group(1).strip()
        annotation = raw.startswith('*')
        chord = raw[1:].strip() if annotation else raw
        pos = m.end()
    tail = text[pos:]
    if tail or chord or not segments:
        segments.append(Segment(chord, tail, annotation))
    return Line(segments)


def parse(source: str) -> Song:
    """ChordProの文字列を、Songにする。壊れた入力でも例外にしない（閉じていない区間は、末尾で閉じる。警告つき）。"""
    song = Song()
    section: Optional[Section] = None
    container = song.items
    shift = 0   # 今、効いている`{transpose}`（半音）。以降の行に、効く

    lines = source.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    if lines and lines[-1] == '':
        lines.pop()   # 最後の改行が作る、空の「行」は、空行ではない
    for lineno, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if stripped.startswith('#'):
            continue

        m = _DIRECTIVE_RE.match(raw)
        if m:
            name, value = m.group(1).lower(), (m.group(2) or '').strip()
            if name in _META:
                setattr(song, _META[name], value)
            elif name == 'key':
                song.key = value
                if transpose.parse_key(value) is None:
                    song.warnings.append((lineno, f"Unreadable key '{value}'; shown as written."))
            elif name == 'capo':
                if re.fullmatch(r'\d{1,2}', value):
                    song.capo = int(value)
                else:
                    song.warnings.append((lineno, f"Invalid capo '{value}'; ignored (write a fret number such as {{capo: 2}})."))
            elif name == 'transpose':
                if re.fullmatch(r'[+-]?\d{1,3}', value):
                    shift = int(value)
                else:
                    song.warnings.append((lineno, f"Invalid transpose '{value}'; ignored (write a number of semitones such as {{transpose: 2}})."))
            elif name in _COMMENTS:
                container.append(Comment(value, _COMMENTS[name]))
            elif name in _SECTION_STARTS:
                if section is not None:
                    song.warnings.append((lineno, f"'{name}' inside an open {section.kind} section; the previous section was closed."))
                section = Section(_SECTION_STARTS[name], value)
                song.items.append(section)
                container = section.items
            elif name in _SECTION_ENDS:
                if section is None or section.kind != _SECTION_ENDS[name]:
                    song.warnings.append((lineno, f"'{name}' without a matching start; ignored."))
                else:
                    section = None
                    container = song.items
            else:
                song.warnings.append((lineno, f"Unsupported directive '{name}'; ignored."))
            continue

        if section is not None and section.kind == 'tab':
            container.append(Line(text=raw.rstrip()))
        elif not stripped:
            container.append(Blank())
        else:
            line = parse_line(raw.rstrip())
            line.lineno, line.shift = lineno, shift
            container.append(line)

    if section is not None:
        song.warnings.append((0, f"The {section.kind} section is not closed; closed at the end of the input."))
    _apply_transpose(song, shift)
    return song


def header_meta(song: Song) -> str:
    """見出しに出す、キー・カポ・転調の1行（`Key: B (play in C) / Capo: 2`）。HTMLとPDFで共通。何も無ければ、空。
    転調しているのにキーが分からないとき（`{key}`が無い）は、`Transposed: +2`のように、転調の量を出す。"""
    parts = []
    if song.key and song.play_key:
        parts.append(f"Key: {song.key} (play in {song.play_key})")
    elif song.key:
        parts.append(f"Key: {song.key}")
    elif song.shift:
        parts.append(f"Transposed: {song.shift:+d}")
    if song.capo is not None:
        parts.append(f"Capo: {song.capo}")
    return " / ".join(parts)


def _lines(items):
    """区間の中も含めて、歌詞の行（Line）を、順に返す。"""
    for item in items:
        if isinstance(item, Section):
            yield from _lines(item.items)
        elif isinstance(item, Line):
            yield item


def _apply_transpose(song: Song, final_shift: int) -> None:
    """`{transpose}`の量に従って、コードを書き換える。転調しないときは、何もしない（コードを、書いたとおりに残す）。"""
    lines = [line for line in _lines(song.items) if line.text is None]
    first = next((line for line in lines if line.has_chords), None)
    song.shift = first.shift if first else final_shift
    if song.key and song.shift:
        song.play_key = transpose.transpose_key(song.key, song.shift) or ''
    if not any(line.shift for line in lines):
        return
    original = [s.chord for line in lines for s in line.segments if s.chord and not s.annotation]
    unreadable = set()
    for line in lines:
        if not line.shift:
            continue
        flats = transpose.chooses_flats(line.shift, song.key or None, original)
        for seg in line.segments:
            if not seg.chord or seg.annotation:
                continue
            moved = transpose.transpose_chord(seg.chord, line.shift, flats)
            if moved is None:
                if seg.chord not in unreadable:
                    unreadable.add(seg.chord)
                    song.warnings.append((line.lineno, f"Cannot transpose the chord '{seg.chord}'; shown as written."))
            else:
                seg.chord = moved
