"""ChordProのコード名の解析と、転調（#442）。純粋な関数だけを置く（描画にも、パーサにも依存しない）。

コード名は、ルート音（`C`・`F#`・`Bb`）・種類（`m7`・`sus4`・`add9`など）・スラッシュの後ろの音（`C/E`）に分ける。
動かすのは、ルート音と、スラッシュの後ろの音だけである。種類は、そのまま残す。

`#`と`b`の使い分け:
1. `{key}`があれば、転調後のキーが、フラット系の調（F・Bb・Eb・Ab・Db、Dm・Gm・Cm・Fm・Bbm）ならフラット、それ以外はシャープ。
2. `{key}`がなければ、曲の中のコードが、フラットだけを使っていればフラット、そうでなければ、上げるときはシャープ、下げるときはフラット。
"""
import re
from typing import Optional

_SHARPS = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
_FLATS = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']
_NATURAL = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}

# 音名: 英字1文字と、任意の`#`・`b`。`Bb`は、Bのフラット（種類の`b`と読み違えない）。
_NOTE = r'[A-G][#b]?'
_CHORD_RE = re.compile(rf'^({_NOTE})([^/]*)(?:/({_NOTE}))?$')
_KEY_RE = re.compile(rf'^({_NOTE})(m|min|minor)?$')

# フラットで書く調（長調・短調）。ほかは、シャープで書く。臨時記号の数が同じ調（Gb/F#、Ebm/D#m）と、CとAmは、シャープ側に入れる。
_FLAT_MAJOR = {5, 10, 3, 8, 1}   # F・Bb・Eb・Ab・Db（Gbと F# は、臨時記号が同数なので、F#）
_FLAT_MINOR = {2, 7, 0, 5, 10}   # Dm・Gm・Cm・Fm・Bbm（Ebm と D#m は、同数なので、D#m）

# 転調の対象にしないコード名（ノーコード）
_PASSTHROUGH = {'N.C.', 'N.C', 'NC', 'N'}


def pitch_class(note: str) -> int:
    """音名（`C`・`F#`・`Bb`）を、0〜11の番号にする。"""
    value = _NATURAL[note[0]]
    if note.endswith('#'):
        value += 1
    elif note.endswith('b'):
        value -= 1
    return value % 12


def spell(pc: int, flats: bool) -> str:
    return (_FLATS if flats else _SHARPS)[pc % 12]


def parse_key(text: str) -> Optional[tuple]:
    """キー（`B`・`F#m`・`Bbm`）を、(ルート音の番号, 短調か)にする。読めなければ、None。"""
    m = _KEY_RE.match(text.strip())
    if not m:
        return None
    return pitch_class(m.group(1)), m.group(2) is not None


def key_prefers_flats(key: tuple) -> bool:
    root, minor = key
    return root in (_FLAT_MINOR if minor else _FLAT_MAJOR)


def transpose_key(text: str, semitones: int) -> Optional[str]:
    """キーの表記を、半音で動かす（`B`＋1→`C`、`F#m`＋1→`Gm`）。読めなければ、None。"""
    key = parse_key(text)
    if key is None:
        return None
    root, minor = key
    target = ((root + semitones) % 12, minor)
    return spell(target[0], key_prefers_flats(target)) + ('m' if minor else '')


def split_chord(name: str) -> Optional[tuple]:
    """コード名を、(ルート音, 種類, スラッシュの後ろの音)にする。読めなければ、None。
    `C/9`のように、スラッシュの後ろが音名でないときは、全体を種類として扱う（後ろの音は、None）。"""
    m = _CHORD_RE.match(name)
    if m:
        return m.group(1), m.group(2), m.group(3)
    m = re.match(rf'^({_NOTE})(.*)$', name)
    if m and '/' in m.group(2) and not re.search(rf'/{_NOTE}$', name):
        return m.group(1), m.group(2), None
    return None


def transpose_chord(name: str, semitones: int, flats: bool) -> Optional[str]:
    """コード名を、半音で動かす。ノーコード（`N.C.`）は、そのまま返す。読めなければ、None（呼び出し側が、警告にする）。"""
    if name in _PASSTHROUGH:
        return name
    parts = split_chord(name)
    if parts is None:
        return None
    root, quality, bass = parts
    out = spell(pitch_class(root) + semitones, flats) + quality
    if bass:
        out += '/' + spell(pitch_class(bass) + semitones, flats)
    return out


def chooses_flats(semitones: int, key: Optional[str], chords: list) -> bool:
    """転調後の表記に、フラットを使うか。上の「`#`と`b`の使い分け」の規則。
    chords: 曲の中の、転調前のコード名（`{key}`が無いときに、元の書き方を見るため）。"""
    if key is not None:
        parsed = parse_key(key)
        if parsed is not None:
            return key_prefers_flats(((parsed[0] + semitones) % 12, parsed[1]))
    accidentals = []
    for name in chords:
        parts = split_chord(name)
        if parts:
            accidentals.extend(n[1:] for n in (parts[0], parts[2]) if n and len(n) > 1)
    if accidentals and all(a == 'b' for a in accidentals):
        return True
    if accidentals and all(a == '#' for a in accidentals):
        return False
    return semitones < 0
