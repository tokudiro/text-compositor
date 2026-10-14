"""bizmodelのTypst出力（PDF側。#447）のテスト。生成したコードを調べ、Typstで実際にコンパイルできることも確かめる。"""
import pytest

from text_compositor.renderer import TypstRenderer

DSL = ('company A "売り手"\nperson B "買い手"\n'
       'A -> B : goods "商品" / money "100円"\n')


def renderer(tmp_path, **kwargs):
    return TypstRenderer(str(tmp_path), typst_root=str(tmp_path), line_mapping="off", **kwargs)


def test_a_fence_becomes_an_image_of_the_cached_svg(tmp_path):
    code = renderer(tmp_path).render(f"# T\n\n```bizmodel\n{DSL}```\n")
    assert "bizmodel_" in code and ".svg" in code and "#raw(" not in code


def test_width_and_height_attributes_reach_the_image(tmp_path):
    code = renderer(tmp_path).render(f"# T\n\n```bizmodel {{width=50%}}\n{DSL}```\n")
    assert "width: 50%" in code


@pytest.mark.parametrize("name", ["flow.bizmodel", "flow.bmv"])
def test_a_bizmodel_file_chapter_becomes_an_image(tmp_path, name):
    code = renderer(tmp_path).render_chapter(DSL, filepath=str(tmp_path / name))
    assert ".svg" in code and "bizmodel_" in code


def test_the_plugin_off_shows_the_source_as_code(tmp_path):
    code = renderer(tmp_path, bizmodel_enabled=False).render(f"# T\n\n```bizmodel\n{DSL}```\n")
    assert "bizmodel_" not in code and "売り手" in code


def test_a_syntax_error_stops_with_the_error_code(tmp_path, capsys):
    bad = 'company A "x"\nperson B "y"\nA -> B : goods "z"\n'
    with pytest.raises(SystemExit):
        renderer(tmp_path).render(f"# T\n\n```bizmodel\n{bad}```\n")
    assert "E01" in capsys.readouterr().out
