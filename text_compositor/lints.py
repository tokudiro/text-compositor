"""lint（原稿を調べて出す警告）の一覧と、ON/OFFの指定（#271）。

lintを増やすときは、`LINTS`に1件足し、検出する処理の入口で`renderer.lints[name]`を見る。名前・既定値・
設定画面の表示名・説明は、ここだけに書く（config.yamlの`lint:`・Python API・ワーカーの`params.lint`は、
この一覧から検証する）。
"""
import sys
from collections import namedtuple

from text_compositor.log import _error

Lint = namedtuple("Lint", ["name", "default", "label", "description"])

LINTS = {
    lint.name: lint for lint in [
        Lint("bold", True, "太字のチェック",
             "太字（`**...**`）が効かず、`**`がそのまま出た箇所を、警告する（#215）。"
             "`**`をそのまま見せたい原稿では、切るとよい。"),
    ]
}


def lint_defaults():
    """すべてのlintの既定値（{名前: 真偽値}）。"""
    return {name: lint.default for name, lint in LINTS.items()}


def check_lint_overrides(value):
    """lintの指定（{名前: 真偽値}）の誤りを、文字列で返す（誤りが無ければNone）。
    config.yamlの`lint:`・`Session`の引数・ワーカーの`params.lint`で、同じ検証を使う。"""
    if not isinstance(value, dict):
        return "must be a mapping of lint names to true/false."
    for name, enabled in value.items():
        if name not in LINTS:
            return f"unknown lint {name!r}. Available: {', '.join(sorted(LINTS))}."
        if not isinstance(enabled, bool):
            return f"{name}: must be true or false (got {enabled!r})."
    return None


def resolve_lints(value, where="lint"):
    """lintの指定を検証し、すべての名前を含む{名前: 真偽値}にして返す。省略（None）は、既定値（すべてON）。
    誤りは、設定のエラーとして、sys.exit(1)で止める（他の設定の検証と同じ）。"""
    resolved = lint_defaults()
    if value is None:
        return resolved
    problem = check_lint_overrides(value)
    if problem:
        _error(f"{where}: {problem}")
        sys.exit(1)
    resolved.update(value)
    return resolved
