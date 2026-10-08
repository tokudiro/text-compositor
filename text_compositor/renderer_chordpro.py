"""ChordPro（` ```chordpro `フェンス、`.cho`・`.chordpro`・`.pro`）のTypst化（#440）。

`TypstRenderer`（renderer.py）に、ミックスインとして取り込まれる。構文解析は`chordpro_render`にあり、HTML出力と共有する。
等幅フォントの桁揃えには頼らない。「コード＋直後の歌詞の断片」を1つの`box`にして、縦に積む。
歌詞のフォントが何でも（日本語でも）、コードは歌詞の真上に揃う。
"""
from text_compositor import chordpro_render
from text_compositor.typst_literal import escape_string_literal

_CHORD_COLOR = '#0b5cad'


def _s(text):
    """Typstの文字列リテラル。原稿の文字は、すべてこれで埋め込む（`#`や`*`が、記法として解釈されないように）。"""
    return '"' + escape_string_literal(text) + '"'


class ChordproMixin:
    """ChordProのTypst化。"""

    def _render_chordpro_typst(self, code, code_line=None):
        """ChordProの本文を、Typstのコードにする。警告の行は、code_line（本文1行目の、原稿での行）から数える。"""
        song = chordpro_render.parse(code)
        for lineno, message in song.warnings:
            at = code_line + lineno - 1 if code_line and lineno else code_line
            self._warn_here(f"ChordPro: {message}", line=at)

        out = []
        if song.title:
            out.append(f'#block(above: 1.2em, below: 0.5em, text(size: 1.5em, weight: "bold", {_s(song.title)}))\n')
        for value in (song.subtitle, song.artist):
            if value:
                out.append(f'#block(spacing: 0.3em, text(fill: luma(100), {_s(value)}))\n')
        out.extend(self._chordpro_item_typst(i) for i in song.items)
        return ''.join(out) + '\n'

    def _chordpro_item_typst(self, item):
        if isinstance(item, chordpro_render.Blank):
            return '#v(0.6em)\n'
        if isinstance(item, chordpro_render.Comment):
            if item.style == 'box':
                return f'#block(stroke: 0.5pt + luma(150), inset: (x: 0.5em, y: 0.3em), spacing: 0.5em, text({_s(item.text)}))\n'
            style = '"italic"' if item.style == 'italic' else '"normal"'
            return f'#block(spacing: 0.5em, text(style: {style}, {_s(item.text)}))\n'
        if isinstance(item, chordpro_render.Section):
            return self._chordpro_section_typst(item)
        return self._chordpro_line_typst(item)

    def _chordpro_section_typst(self, section):
        parts = []
        if section.label:
            parts.append(f'#block(spacing: 0.3em, text(size: 0.8em, weight: "bold", fill: luma(110), {_s(section.label)}))\n')
        if section.kind == 'tab':
            tab = "\n".join(i.text for i in section.items if isinstance(i, chordpro_render.Line))
            parts.append(self._render_raw_text(tab))
        else:
            parts.extend(self._chordpro_item_typst(i) for i in section.items)
        body = ''.join(parts)
        if section.kind == 'chorus':
            # 左の線で、コーラスを示す（HTMLと同じ）
            return f'#block(stroke: (left: 1.2pt + luma(160)), inset: (left: 0.8em, y: 2pt), spacing: 0.8em)[\n{body}]\n'
        return f'#block(spacing: 0.8em)[\n{body}]\n'

    def _chordpro_line_typst(self, line):
        if not line.has_chords:
            text = ''.join(s.lyric for s in line.segments)
            return f'#block(spacing: 0.45em, text({_s(text)}))\n'
        boxes = []
        for seg in line.segments:
            if seg.chord:
                color = 'luma(100)' if seg.annotation else f'rgb("{_CHORD_COLOR}")'
                style = '"italic"' if seg.annotation else '"normal"'
                weight = '"regular"' if seg.annotation else '"bold"'
                chord = f'box(inset: (right: 0.45em), text(weight: {weight}, style: {style}, fill: {color}, {_s(seg.chord)}))'
            else:
                chord = 'box(height: 1em)'
            lyric = f'text({_s(seg.lyric)})' if seg.lyric else 'box(height: 1em)'
            boxes.append(f'#box(stack(dir: ttb, spacing: 0.2em, {chord}, {lyric}))')
        # 空白を挟まずに並べる。箱と箱の間で、折り返す
        return f'#block(breakable: false, spacing: 0.8em)[#set par(leading: 0.9em);{"".join(boxes)}]\n'
