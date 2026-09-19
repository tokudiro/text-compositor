"""常駐するPython API（`Session`、#167）の、保存から更新までの時間の計測。

原稿を書き換えては、同じ`Session`で`build()`を繰り返し、2回目以降（warm）の時間を測る。CLIの`_build_one`を
使う`gui_latency.py`（毎回、Mermaidのブラウザと`typst.Compiler`を作り直す）との差を見る。

使い方（リポジトリ直下で実行）:
    python benchmarks/api_latency.py [--runs 20] [--mermaid]
"""
import argparse
import os
import shutil
import statistics
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui_latency import doc_large, doc_mermaid, doc_minimal, doc_typical, write  # noqa: E402
from text_compositor.api import Session  # noqa: E402

PLAIN = {"mermaid": False, "plantuml": False, "d2": False}


def run(session, md, out, gen, plugins, runs, clear_cache=False):
    rows = []
    for i in range(runs):
        write(md, gen(i))
        if clear_cache:
            shutil.rmtree(os.path.join(os.path.dirname(md), ".text-compositor", "cache"), ignore_errors=True)
        r = session.build(md, out, plugins=plugins)
        if not r.ok:
            raise SystemExit(f"build failed: {[d.message for d in r.errors]}")
        rows.append(r.timings_ms)
    return rows


def report(name, rows):
    cold, warm = rows[0], rows[1:]

    def mean(key):
        return statistics.mean(r.get(key, 0.0) for r in warm)
    print(f"[{name}] cold total={cold['total']:.0f} ms (render {cold['render']:.0f} / compile {cold['compile']:.0f})")
    print(f"    warm(n={len(warm)}) total mean={mean('total'):.0f} min={min(r['total'] for r in warm):.0f} "
          f"max={max(r['total'] for r in warm):.0f} | render {mean('render'):.0f} / compile {mean('compile'):.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--mermaid", action="store_true", help="Mermaid（Chrome/Edgeとplaywrightが要る）も測る")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="api-latency-")
    try:
        with Session() as session:
            for name, gen in (("minimal", doc_minimal), ("typical (5節・表・dot図)", doc_typical),
                              ("large (40節・約30ページ)", doc_large)):
                project = os.path.join(tmp, name.split()[0])
                report(name, run(session, os.path.join(project, "doc.md"), os.path.join(project, "o.pdf"),
                                 gen, PLAIN, args.runs))
            if args.mermaid:
                project = os.path.join(tmp, "mermaid")
                plugins = {"plantuml": False, "d2": False}
                report("mermaid・図を毎回変更（ブラウザは常駐）",
                       run(session, os.path.join(project, "doc.md"), os.path.join(project, "o.pdf"),
                           doc_mermaid, plugins, 8, clear_cache=True))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
