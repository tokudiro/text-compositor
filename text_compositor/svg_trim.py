"""生成済みSVGの余白を、実際に描かれている範囲へ合わせて縮める（トリミング、#315）。

resvg（Rust製のSVGレンダラー）をPythonから呼ぶ`resvg_py`でラスタライズし、背景と異なる画素の
外接矩形を、実際の描画範囲として求める。resvg内部の`usvg`が、テキストを実際にフォントで
シェイピングしてから幾何情報に変換するため、ヘッドレスブラウザ無しでも、文字を含めた正確な
範囲が求まる（Node.js・Puppeteer等は不要）。

透明度（アルファ）ではなく、コーナー（左上の1px）の色との差分で内容を判定する。理由:
Mermaidは背景が透明（アルファ0）だが、D2は`--pad`の外周まで、自身で不透明な背景矩形を
描くため、透明度だけでは内容の範囲を判定できない（#315で実測して判明）。
"""
import io
import re

_ROOT_SVG_RE = re.compile(r'<svg\b[^>]*>')
_VIEWBOX_RE = re.compile(r'viewBox\s*=\s*"([^"]+)"')
# 数値＋任意の単位（px/%等）。%は「コンテナ幅いっぱい」等の相対値であり、トリミング後の
# 絶対サイズに置き換えると意味が変わってしまうため、対象外にする（Mermaidのwidth="100%"等）。
_SIZE_ATTR_RE_TMPL = r'(\b{name}\s*=\s*")([\d.]+)(px)?("|%")'
# (?:^|;)で区切ることで、"width"指定時に"max-width"（Mermaidが使う、非拘束の上限値。
# 更新しなくても、トリミング後は必ずそれ以下になるため、正しさには影響しない）を誤って
# 書き換えないようにする。
_STYLE_SIZE_RE_TMPL = r'((?:^|;)\s*{name}\s*:\s*)[\d.]+(px)'

# ラスタライズの基準解像度（長辺のピクセル数）。実測（#315）では、1000pxもあれば、
# 典型的な図（数百ユーザー単位角）で十分な精度が出た。resvg自体は高速なため、
# 1000x1000程度のRGBAラスタ化は軽い処理で済む。
_TARGET_LONG_SIDE = 1000
# トリミング後に残す、小さな安全マージン（元のSVGのユーザー単位）。ラスタ化・境界判定の
# 誤差や、アンチエイリアシングでラベルの一部が見切れることを防ぐ。
DEFAULT_MARGIN = 4


class TrimError(Exception):
    """トリミングできなかった。呼び出し側は、これを捕まえて元のSVGをそのまま使うこと
    （トリミングは見た目の改善であり、失敗しても元の図自体は正しく描画済みのため、
    ビルド全体を失敗させる理由にはならない）。"""


def _replace_size_attr(tag, name, new_value):
    m = re.search(_SIZE_ATTR_RE_TMPL.format(name=name), tag)
    if not m or m.group(4) == '%"':
        return tag
    unit = m.group(3) or ""
    return re.sub(_SIZE_ATTR_RE_TMPL.format(name=name), rf'\g<1>{new_value:g}{unit}\g<4>', tag, count=1)


def _replace_style_size(tag, name, new_value):
    style_m = re.search(r'style\s*=\s*"([^"]*)"', tag)
    if not style_m:
        return tag
    new_style = re.sub(_STYLE_SIZE_RE_TMPL.format(name=name), rf'\g<1>{new_value:g}\g<2>', style_m.group(1))
    if new_style == style_m.group(1):
        return tag
    return tag[:style_m.start(1)] + new_style + tag[style_m.end(1):]


def trim_svg(svg_text, margin=DEFAULT_MARGIN):
    """SVGのルート要素のviewBox・width・height（属性・style両方）を、実際に描かれている範囲＋
    安全マージンへ縮めて返す。判定できない場合（ルート要素にviewBoxが無い、内容が背景と
    見分けられない等）はTrimErrorを送出する。"""
    import resvg_py
    from PIL import Image, ImageChops

    m = _ROOT_SVG_RE.search(svg_text)
    if not m:
        raise TrimError("no root <svg> tag found")
    root_tag = m.group(0)
    vb_m = _VIEWBOX_RE.search(root_tag)
    if not vb_m:
        raise TrimError("no viewBox on the root <svg> tag")
    try:
        minx, miny, vw, vh = (float(x) for x in vb_m.group(1).split())
    except ValueError:
        raise TrimError(f"unparsable viewBox: {vb_m.group(1)!r}")
    if vw <= 0 or vh <= 0:
        raise TrimError(f"empty viewBox: {vb_m.group(1)!r}")

    scale = _TARGET_LONG_SIDE / max(vw, vh)
    raster_w = max(1, round(vw * scale))
    raster_h = max(1, round(vh * scale))

    try:
        png_bytes = resvg_py.svg_to_bytes(svg_string=svg_text, width=raster_w, height=raster_h)
    except ValueError as e:
        raise TrimError(f"resvg failed to rasterize: {e}")

    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    background = Image.new("RGBA", img.size, img.getpixel((0, 0)))
    # alpha_only=False: 差分画像のアルファ成分は、元が不透明どうし（D2等）だと常に0になり、
    # 既定のgetbbox()だとRGBの差を無視して「境界なし」と誤判定するため（実機確認、#315）。
    bbox = ImageChops.difference(img, background).getbbox(alpha_only=False)
    if bbox is None:
        raise TrimError("no content found (the rendered image is a solid color)")

    px0, py0, px1, py1 = bbox
    new_minx = max(minx + px0 / scale - margin, minx)
    new_miny = max(miny + py0 / scale - margin, miny)
    new_maxx = min(minx + px1 / scale + margin, minx + vw)
    new_maxy = min(miny + py1 / scale + margin, miny + vh)
    new_w = new_maxx - new_minx
    new_h = new_maxy - new_miny
    if new_w <= 0 or new_h <= 0:
        raise TrimError("computed an empty crop box")

    new_tag = _VIEWBOX_RE.sub(f'viewBox="{new_minx:g} {new_miny:g} {new_w:g} {new_h:g}"', root_tag, count=1)
    new_tag = _replace_size_attr(new_tag, "width", new_w)
    new_tag = _replace_size_attr(new_tag, "height", new_h)
    # PlantUML/Structurizrは、style属性にもwidth/height（px）を重複して持つ。<img>で埋め込む際、
    # ブラウザはこちらをviewBox/属性より優先するため、更新しないと、縮めたつもりが拡大表示になる。
    new_tag = _replace_style_size(new_tag, "width", new_w)
    new_tag = _replace_style_size(new_tag, "height", new_h)

    return svg_text[:m.start()] + new_tag + svg_text[m.end():]
