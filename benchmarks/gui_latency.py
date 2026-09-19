"""GUI版Viewer（#165）向けの、「保存から更新まで」のレイテンシ計測（#166、#103のベースライン）。

常駐プロセスで、Markdownを更新しては`_build_one`（configの読み込み → `TypstRenderer.render()` →
Typstコンパイル → PDF書き出し）を繰り返し呼び、内訳を測る。GUIの実装言語に関わらず、この
Python側の処理が更新までの時間の大半を占めるかを確かめるのが目的である。

使い方（リポジトリ直下で実行）:
    python benchmarks/gui_latency.py [--runs 10] [--slow-runs 3] [--json out.json]

計測するもの:
  * import: `import text_compositor.build`にかかる時間（プロセス起動後に1回）
  * 各シナリオの1回目（cold）と、2回目以降（warm）の`_build_one`の所要時間と内訳
      render  : `TypstRenderer.render()`（Markdown → Typstコード。図表の描画を含む）
      compile : `typst.compile()`（Typstコード → PDF）
      other   : 上記以外（config読み込み、テンプレートのコピー、ファイルI/O等）
  * Typstコンパイル単体を、毎回`typst.compile()`を呼ぶ場合と、`typst.Compiler`を使い回す場合で比較
  * PDFの1ページをビットマップへ描画する時間（表示側のコストの目安。PyMuPDFを使う）
  * 別プロセスのPythonへ、JSON行で依頼して返答を受け取る往復の時間（常駐サブプロセス方式の通信コスト）
"""
import argparse
import contextlib
import io
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


def ms(seconds):
    return seconds * 1000.0


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# --- シナリオの原稿 ---------------------------------------------------------

PARAGRAPH = ("これは本文の段落である。文章が連続して流れる文書では、段落・箇条書き・表が交互に現れる。"
             "日本語の長い文章が、折り返されるときの組版も含めて計測に入る。\n")


def doc_minimal(i):
    return f"# 最小\n\n{PARAGRAPH}\n更新 {i}\n\n{PARAGRAPH}\n- 項目1\n- 項目2\n"


def doc_typical(i):
    sections = []
    for n in range(1, 6):
        sections.append(f"## 節{n}\n\n{PARAGRAPH}\n- 項目A\n- 項目B\n- 項目C\n\n"
                        f"| 項目 | 値 |\n| --- | --- |\n| a | {n} |\n| b | {i} |\n")
    return "# 標準的な文書\n\n" + "\n".join(sections) + "\n```dot\ndigraph { a -> b -> c }\n```\n"


def doc_large(i):
    sections = []
    for n in range(1, 41):
        sections.append(f"## 節{n}\n\n{PARAGRAPH}\n{PARAGRAPH}\n- 項目A\n- 項目B\n\n"
                        f"| 項目 | 値 |\n| --- | --- |\n| a | {n} |\n| b | {i} |\n")
    return "# 大きな文書\n\n" + "\n".join(sections)


def doc_mermaid(i):
    # 図のソースを毎回変えると、キャッシュ（複合ハッシュ、#26）に当たらない。i=0固定ならキャッシュに当たる。
    return f"# Mermaid\n\n{PARAGRAPH}\n```mermaid\ngraph TD\n  A[開始{i}] --> B[処理] --> C[終了]\n```\n"


def doc_plantuml(i):
    return f"# PlantUML\n\n{PARAGRAPH}\n```plantuml\n@startuml\nAlice -> Bob: 要求{i}\nBob --> Alice: 応答\n@enduml\n```\n"


def doc_d2(i):
    return f"# D2\n\n{PARAGRAPH}\n```d2\nx{i}: 開始\ny: 処理\nx{i} -> y\n```\n"


# (名前, 原稿の生成関数, 反復ごとに内容を変えるか, 図表キャッシュを毎回消すか, 遅いシナリオか)
SCENARIOS = [
    ("minimal", doc_minimal, False, False),
    ("typical (5節・表・dot図)", doc_typical, False, False),
    ("large (40節・約30ページ)", doc_large, False, False),
    ("mermaid・キャッシュ命中", lambda i: doc_mermaid(0), False, False),
    ("mermaid・キャッシュ外れ", doc_mermaid, True, True),
    ("plantuml・キャッシュ外れ", doc_plantuml, True, True),
    ("d2・キャッシュ外れ", doc_d2, True, True),
]


def make_project(tmp, index):
    project = os.path.join(tmp, f"proj{index}")
    shutil.rmtree(project, ignore_errors=True)
    write(os.path.join(project, "text-compositor.config.yaml"),
          "document:\n  title: bench\n  cover: template\nplugins:\n  graphviz: true\n"
          "inputs:\n  dir: \".\"\nchapters:\n  - doc.md\n")
    return project


def run_scenario(B, font_dir, name, gen, slow, runs, tmp, index):
    project = make_project(tmp, index)
    config = os.path.join(project, "text-compositor.config.yaml")
    md = os.path.join(project, "doc.md")
    tool_dir = os.path.dirname(os.path.abspath(B.__file__))

    acc = {"render": 0.0, "compile": 0.0}
    orig_render = B.TypstRenderer.render
    orig_compile = B.typst_lib.compile

    def timed_render(self, *a, **k):
        t = time.perf_counter()
        try:
            return orig_render(self, *a, **k)
        finally:
            acc["render"] += time.perf_counter() - t

    def timed_compile(*a, **k):
        t = time.perf_counter()
        try:
            return orig_compile(*a, **k)
        finally:
            acc["compile"] += time.perf_counter() - t

    B.TypstRenderer.render = timed_render
    B.typst_lib.compile = timed_compile
    rows = []
    try:
        for i in range(runs):
            write(md, gen(i))
            if slow:
                shutil.rmtree(os.path.join(project, ".text-compositor", "cache"), ignore_errors=True)
            acc["render"] = acc["compile"] = 0.0
            t = time.perf_counter()
            with contextlib.redirect_stdout(io.StringIO()):
                B._build_one(tool_dir, REPO_ROOT, font_dir, config, keep_temp=(i == runs - 1))
            total = time.perf_counter() - t
            rows.append({"total": ms(total), "render": ms(acc["render"]), "compile": ms(acc["compile"]),
                         "other": ms(total - acc["render"] - acc["compile"])})
    finally:
        B.TypstRenderer.render = orig_render
        B.typst_lib.compile = orig_compile
    return project, rows


def summarize(rows):
    def col(k):
        return [r[k] for r in rows]
    out = {}
    for k in ("total", "render", "compile", "other"):
        v = col(k)
        out[k] = {"mean": statistics.mean(v), "min": min(v), "max": max(v)}
    return out


# --- コンパイル単体、PDF描画、IPC ------------------------------------------------

def bench_compile_only(B, font_dir, project, runs):
    """最後の反復で残した`temp_build.typ`を、毎回書き換えながらコンパイルし、`typst.compile()`と
    `typst.Compiler`の使い回しを比べる。入力を変えずに繰り返すと、使い回しが実際より速く見える
    （変更が無ければ再計算が省かれる）ため、必ず内容を変える。更新がPDFへ反映されたかも確認する。"""
    import typst
    import pymupdf
    typ = os.path.join(project, ".text-compositor", "temp_build.typ")
    base = open(typ, encoding="utf-8").read()

    def has_marker(pdf_bytes, marker):
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        return marker in "".join(page.get_text() for page in doc)

    def run(compile_fn):
        times, reflected = [], 0
        for i in range(runs):
            marker = f"ZQMARK{i}ZQ"
            with open(typ, "w", encoding="utf-8") as f:
                f.write(base + f"\n\n{marker}\n")
            t = time.perf_counter()
            pdf = compile_fn()
            times.append(ms(time.perf_counter() - t))
            reflected += has_marker(pdf, marker)
        return {"times": times, "reflected": reflected, "runs": runs}

    res = {}
    res["typst.compile()を毎回呼ぶ"] = run(lambda: typst.compile(
        typ, root=project, font_paths=[font_dir], ignore_system_fonts=True))
    compiler = typst.Compiler(typ, root=project, font_paths=[font_dir], ignore_system_fonts=True)
    res["typst.Compilerを使い回す"] = run(lambda: compiler.compile(format="pdf"))
    with open(typ, "w", encoding="utf-8") as f:
        f.write(base)
    return res


def bench_mermaid_resident(B, tmp, runs):
    """同じ`TypstRenderer`を使い回した（Mermaid用のブラウザを開いたままにした）場合の、図1つあたりの時間。
    `_build_one`は、ビルドのたびにrendererを閉じてブラウザを終了するため、毎回ブラウザの起動が乗る。"""
    project = os.path.join(tmp, "mermaid-resident")
    os.makedirs(project, exist_ok=True)
    md = os.path.join(project, "doc.md")
    renderer = B.TypstRenderer(base_dir=project, typst_root=project)
    times = []
    try:
        for i in range(runs):
            t = time.perf_counter()
            with contextlib.redirect_stdout(io.StringIO()):
                renderer.render(doc_mermaid(1000 + i), filepath=md)
            times.append(ms(time.perf_counter() - t))
    finally:
        renderer.close()
    return times


def bench_pdf_render(pdf_path, runs):
    """PDFの1ページ目を、ビットマップへ描画する時間（表示側のコストの目安）。"""
    try:
        import pymupdf
    except ImportError:
        return "pymupdf not installed"
    res = {}
    for dpi in (96, 200):
        times = []
        for _ in range(runs):
            t = time.perf_counter()
            doc = pymupdf.open(pdf_path)
            doc[0].get_pixmap(dpi=dpi)
            doc.close()
            times.append(ms(time.perf_counter() - t))
        res[f"1ページ目を{dpi}dpiで描画（開く時間を含む）"] = times
    return res


WORKER = r'''
import json, sys
for line in sys.stdin:
    req = json.loads(line)
    sys.stdout.write(json.dumps({"id": req["id"], "ok": True, "warnings": []}) + "\n")
    sys.stdout.flush()
'''


def bench_ipc(runs):
    """常駐サブプロセスへJSON行で依頼し、返答を受け取る往復の時間（依頼の中身は空）。"""
    proc = subprocess.Popen([sys.executable, "-c", WORKER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            text=True, encoding="utf-8")
    times = []
    try:
        for i in range(runs + 5):
            t = time.perf_counter()
            proc.stdin.write(json.dumps({"id": i, "path": "C:/x/doc.md"}) + "\n")
            proc.stdin.flush()
            proc.stdout.readline()
            if i >= 5:  # 最初の数回は、起動直後の揺らぎがあるため除く
                times.append(ms(time.perf_counter() - t))
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)
    return times


def stat(v):
    return {"mean": statistics.mean(v), "min": min(v), "max": max(v)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10, help="通常のシナリオの反復回数（1回目をcold、以降をwarmとして扱う）")
    ap.add_argument("--slow-runs", type=int, default=3, help="図表キャッシュ外れのシナリオの反復回数")
    ap.add_argument("--json", help="結果をJSONで保存するパス")
    ap.add_argument("--only", help="名前にこの文字列を含むシナリオだけ実行する")
    args = ap.parse_args()

    t = time.perf_counter()
    import text_compositor.build as B
    import_ms = ms(time.perf_counter() - t)
    font_dir = B.ensure_fonts()

    result = {"import_ms": import_ms, "scenarios": {}}
    print(f"import text_compositor.build: {import_ms:.0f} ms\n")
    tmp = tempfile.mkdtemp(prefix="gui-latency-")
    last_project = None
    try:
        for index, (name, gen, changing, slow) in enumerate(SCENARIOS):
            if args.only and args.only not in name:
                continue
            runs = args.slow_runs if slow else args.runs
            project, rows = run_scenario(B, font_dir, name, gen, slow, runs, tmp, index)
            cold, warm = rows[0], rows[1:]
            result["scenarios"][name] = {"cold": cold, "warm": summarize(warm) if warm else None, "runs": runs}
            print(f"[{name}] cold total={cold['total']:.0f} ms (render {cold['render']:.0f} / compile "
                  f"{cold['compile']:.0f} / other {cold['other']:.0f})")
            if warm:
                s = summarize(warm)
                print(f"    warm(n={len(warm)}) total mean={s['total']['mean']:.0f} min={s['total']['min']:.0f} "
                      f"max={s['total']['max']:.0f} | render {s['render']['mean']:.0f} / compile "
                      f"{s['compile']['mean']:.0f} / other {s['other']['mean']:.0f}")
            if name.startswith("typical"):
                last_project = project  # 生成コードを、Typstコンパイル単体の計測に使う
        if last_project and os.path.isdir(os.path.join(last_project, ".text-compositor")):
            print("\n[Typstコンパイル単体（typicalの生成コード。毎回、内容を書き換える）]")
            comp = bench_compile_only(B, font_dir, last_project, args.runs)
            result["compile_only"] = {}
            for k, v in comp.items():
                t = v["times"]
                result["compile_only"][k] = {"first": t[0], **stat(t[1:]), "reflected": f"{v['reflected']}/{v['runs']}"}
                print(f"  {k}: 1回目 {t[0]:.0f} ms / 2回目以降 mean={statistics.mean(t[1:]):.1f} "
                      f"min={min(t[1:]):.1f} max={max(t[1:]):.1f} ms / 更新の反映 {v['reflected']}/{v['runs']}")
            pdf = os.path.join(last_project, "outputs", "System_Specification.pdf")
            print("\n[PDFの描画（表示側の目安）]")
            r = bench_pdf_render(pdf, args.runs)
            result["pdf_render"] = {}
            if isinstance(r, dict):
                for k, v in r.items():
                    result["pdf_render"][k] = stat(v[1:])
                    print(f"  {k}: mean={statistics.mean(v[1:]):.1f} min={min(v[1:]):.1f} max={max(v[1:]):.1f} ms")
            else:
                print(f"  {r}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if not args.only or "mermaid" in args.only:
        print("\n[Mermaid: rendererを使い回した場合の、図1つあたりの時間（図は毎回別）]")
        tmp2 = tempfile.mkdtemp(prefix="gui-latency-m-")
        try:
            times = bench_mermaid_resident(B, tmp2, 5)
            result["mermaid_resident"] = {"first": times[0], **stat(times[1:])}
            print(f"  1回目（ブラウザの起動を含む）{times[0]:.0f} ms / 2回目以降 mean={statistics.mean(times[1:]):.0f} "
                  f"min={min(times[1:]):.0f} max={max(times[1:]):.0f} ms")
        except Exception as e:
            print(f"  skipped: {e!r}")
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)

    print("\n[常駐サブプロセスへの依頼の往復（JSON行、stdin/stdout）]")
    ipc = bench_ipc(50)
    result["ipc_roundtrip"] = stat(ipc)
    print(f"  mean={statistics.mean(ipc):.3f} min={min(ipc):.3f} max={max(ipc):.3f} ms")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
