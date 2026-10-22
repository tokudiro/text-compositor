"""綴じ代の設定`binding_margin`・`binding_side`（#321）のテスト。"""
import os
import re
import shutil

import pytest
import typst

import text_compositor.build as build
from text_compositor.document import _binding_typst_args

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(build.__file__)), "templates")
CM = 72 / 2.54   # 1cmは、何ptか


class TestSetting:
    def test_omitted_passes_nothing(self):
        """未指定なら引数を渡さない（binding_marginを知らない既存のテンプレートを壊さない）。"""
        assert _binding_typst_args({}) == ""

    def test_margin_defaults_to_the_left_side(self):
        assert _binding_typst_args({"binding_margin": "1cm"}) == "  binding_margin: 1cm,\n  binding_side: left,\n"

    def test_side_and_units(self):
        assert "binding_side: right" in _binding_typst_args({"binding_margin": "8.5mm", "binding_side": "Right"})
        for value in ("10pt", "0.5in", "12mm"):
            assert f"binding_margin: {value}," in _binding_typst_args({"binding_margin": value})

    @pytest.mark.parametrize("config", [
        {"binding_margin": "1"},            # 単位が無い
        {"binding_margin": 1},              # 数値
        {"binding_margin": "1cm; x"},       # Typstの式を紛れ込ませない
        {"binding_margin": "1cm", "binding_side": "top"},
        {"binding_side": "left"},           # 幅が無いと効果が無い
    ])
    def test_wrong_values_are_errors(self, config, capsys):
        with pytest.raises(SystemExit):
            _binding_typst_args(config)
        captured = capsys.readouterr()
        assert "binding_" in captured.out + captured.err

    def test_keys_are_known_to_the_config_check(self):
        from text_compositor.config import _ALLOWED_DOCUMENT_KEYS
        assert {"binding_margin", "binding_side"} <= _ALLOWED_DOCUMENT_KEYS


def left_margins(tmp_path, template, args, pages=3):
    """テンプレートで、ページの高さいっぱいの帯を並べ、ページごとのヘッダーの罫線（本文の左端と同じ位置）の左端（pt）を返す。
    paper.typは2段組みで、改ページも無効なため、1ページに帯が2本（段ごとに1本）入る。"""
    for name in (template, "_common.typ"):
        shutil.copy(os.path.join(TEMPLATES, name), tmp_path / name)
    per_page = 2 if template == "paper.typ" else 1
    main = tmp_path / "main.typ"
    main.write_text(
        "\n".join([
            f'#import "{template}": conf',
            f'#show: doc => conf(title: "T", cover: false, {args}doc)',
            f'#for i in range({pages * per_page}) [#rect(width: 1cm, height: 100%, fill: red)]',
            "",
        ]),
        encoding="utf-8")
    svgs = typst.compile(str(main), format="svg")
    assert isinstance(svgs, list) and len(svgs) >= pages
    result = []
    for svg in svgs[:pages]:
        # スライドには、ヘッダーの罫線が無い。その場合は、帯（赤）の位置を使う（スライドは1段組みで、帯はグループに入らない）
        m = (re.search(r'<path fill="none" stroke="#c8c8c8"[^>]*translate\(([\d.]+) ', svg.decode())
             or re.search(r'<path fill="#ff4136"[^>]*translate\(([\d.]+) ', svg.decode()))
        result.append(float(m.group(1)))
    return result


@pytest.mark.parametrize("template, x_cm", [("template.typ", 2.5), ("paper.typ", 1.8)])
class TestTemplates:
    def test_inside_margin_is_wider_by_the_binding_width(self, tmp_path, template, x_cm):
        """左綴じ: 奇数ページ（右ページ）は左側が内側、偶数ページ（左ページ）は右側が内側。"""
        odd, even, odd2 = left_margins(tmp_path, template, 'binding_margin: 1cm, binding_side: left, ')
        assert odd == pytest.approx((x_cm + 1) * CM, abs=0.5)
        assert even == pytest.approx(x_cm * CM, abs=0.5)
        assert odd2 == pytest.approx(odd, abs=0.5)

    def test_right_binding_swaps_the_pages(self, tmp_path, template, x_cm):
        odd, even, _ = left_margins(tmp_path, template, 'binding_margin: 1cm, binding_side: right, ')
        assert odd == pytest.approx(x_cm * CM, abs=0.5)
        assert even == pytest.approx((x_cm + 1) * CM, abs=0.5)

    def test_without_binding_every_page_has_the_same_margin(self, tmp_path, template, x_cm):
        odd, even, _ = left_margins(tmp_path, template, '')
        assert odd == pytest.approx(even, abs=0.5)


def test_slide_accepts_and_ignores_the_arguments(tmp_path):
    """スライドは綴じないが、config.yamlに書いてもエラーにしない（conf()契約）。"""
    odd, even, _ = left_margins(tmp_path, "slide.typ", 'binding_margin: 1cm, binding_side: left, ')
    assert odd == pytest.approx(even, abs=0.5)
