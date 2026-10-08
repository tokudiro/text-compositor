"""ChordPro（`.cho`・`.chordpro`・`.pro`、` ```chordpro `フェンス）の構文解析（#440）。

描画はここに置かない。解析結果（`Song`）を、HTML出力とTypst出力が、それぞれ描く。
他の図と違い、外部ツールもブラウザも使わない。文法が小さく、自前のパーサで足りるため。

対応する範囲は、最小に絞っている（#440）。
- 指令: `title`/`t`、`subtitle`/`st`、`artist`、`comment`/`c`、`comment_italic`/`ci`、`comment_box`/`cb`、
  `start_of_chorus`/`soc`、`start_of_verse`/`sov`、`start_of_bridge`/`sob`、`start_of_tab`/`sot`（と、それぞれの`end_of_*`）
- 行内のコード: `[Am7]`。`[*注記]`は、コードではなく注記（先頭の`*`は表示しない）
- 行頭が`#`の行は、コメントとして捨てる
未対応の指令（`transpose`・`define`など）は、捨てて、`Song.warnings`に残す。黙って捨てると、書いたものが消えたことに気づけないため。
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

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
            container.append(parse_line(raw.rstrip()))

    if section is not None:
        song.warnings.append((0, f"The {section.kind} section is not closed; closed at the end of the input."))
    return song
