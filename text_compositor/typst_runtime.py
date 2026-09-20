"""`typst`モジュールの遅延読み込みと、同梱のTypstのパッケージの置き場所（PDFのコンパイルと、HTML出力のGraphvizが共有する）。"""
import os

# PyPIの typst パッケージ(typst-py)はコンパイラ本体をプラットフォーム別ホイールに同梱しているため、
# tools/typst.exe のような実行バイナリをリポジトリに持たずに済む（pipがOSごとに正しい版を入れてくれる）。
# Typstを通す処理（PDFのコンパイル、HTML出力のGraphviz。#264）でだけ必要なため、初めて使うときに読み込む（#168）。
# Typstを通さないHTML出力（Markdown・Mermaid等）は、typstを入れなくても動く。


class _LazyTypst:
    """`typst`モジュールの代わり。属性に初めて触れたときに、importする。"""

    def __getattr__(self, name):
        try:
            import typst
        except ImportError as e:
            raise ImportError("The 'typst' package is required to build PDFs and to draw Graphviz diagrams "
                              "(pip install typst==0.15.0).") from e
        return getattr(typst, name)


typst_lib = _LazyTypst()

# 呼び出し元が、同梱したTypstのパッケージ（`preview/<名前>/<版>/`の形）のフォルダを教える環境変数（#263）。ViewerのZIPは、
# テンプレートが使うパッケージを同梱しており、Electronが、この変数で、ワーカーに教える。あれば、`package_cache_path`に
# 渡し、初回のダウンロードなしで、`@preview/...`のimportが解決できる。CLIは、この変数を使わない（従来どおり、取得して、キャッシュする）。
TYPST_PACKAGES_ENV = "TEXT_COMPOSITOR_TYPST_PACKAGES"


def typst_package_options():
    """`typst.compile`・`typst.Compiler`に渡す、パッケージの置き場所の引数。環境変数が、存在するフォルダを指すときだけ、値がある。"""
    path = os.environ.get(TYPST_PACKAGES_ENV)
    return {"package_cache_path": path} if path and os.path.isdir(path) else {}
