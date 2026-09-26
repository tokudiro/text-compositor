import os
import sys

import pytest

# text_compositor/ パッケージはリポジトリ直下にあるため、pipインストールしていない
# 開発環境でも tests/配下からimportできるよう、リポジトリ直下をsys.pathへ追加する（#111）。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _no_github_actions_env(monkeypatch):
    """このプロジェクト自身のCIもGitHub Actions上（GITHUB_ACTIONS=true）で動くため、これらの
    環境変数を明示的に未設定にしない限り、diagnostics.pyのGitHub Actionsアノテーション出力（#29）が
    テスト実行環境によって意図せず有効になり、標準出力を厳密比較する既存テストがローカルでは通り
    CI上だけ落ちる、という不安定な状態になる。個別のテストがmonkeypatch.setenvで上書きすればよい。"""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
