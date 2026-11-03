"""画像のローカルパスの解決（PDF出力用。#586）。

Markdownの画像のパスには、スペースを`%20`と書く人がいる（`![](sub%20dir/a%20b.png)`）。HTML出力は、`%XX`を
ファイル名に直して探す（`html_output.py`の`_local_asset_path`）。PDF出力は、直さずに探して、見つからなかった。
そこで、探す名前を、次の順に試す。書かれたとおりの名前のファイル（`a%20b.png`という名前の実在のファイル）を、
壊さないために、書かれたとおりを先にする。
"""
import os
import urllib.parse
from typing import List


def _candidates(base_dir: str, src: str) -> List[str]:
    names = [src]
    decoded = urllib.parse.unquote(src)
    if decoded != src:
        names.append(decoded)
    # HTMLと同じ。`?`・`#`以降は、ファイル名に含めない（書かれたとおりを先に試すため、`#`を含む実在の名前は壊れない）
    stripped = urllib.parse.unquote(src.split('#', 1)[0].split('?', 1)[0])
    if stripped not in names:
        names.append(stripped)
    return [os.path.normpath(os.path.join(base_dir, name)) for name in names]


def resolve_local_asset(base_dir: str, src: str) -> str:
    """base_dirを基準にした、画像のファイルのパス。候補のうち、実在するものを返す。どれも無ければ、
    書かれたとおりの名前のパスを返す（呼び出し側が「見つからない」と報告するときに、そのまま使う）。"""
    candidates = _candidates(base_dir, src)
    return next((path for path in candidates if os.path.exists(path)), candidates[0])
