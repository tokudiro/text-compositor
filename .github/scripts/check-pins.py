"""コードに直接書いた部品の版を、上流の最新版と比べて、差を報告する（#240）。

Dependabotが見られるのは、npm・pip・GitHub Actionsの一部だけである。Mermaid・PlantUML・D2・JRE・
組込版Python・Typstのパッケージ・フォントは、ソースコードに版を直接書いているため、このスクリプトで確認する。

使い方（標準ライブラリだけで動く）:
    python .github/scripts/check-pins.py [--output report.md]

- 差があるかどうかは、環境変数GITHUB_OUTPUTが設定されていれば`has_updates=true|false`として書く。
- 固定値をソースから読み取れなかったときは、終了コード2で終わる（ソースの書き方が変わって、確認が
  空振りになるのを防ぐため）。上流の最新版を取得できなかった部品は、「確認できず」と報告し、差には数えない。
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TIMEOUT = 30


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def read_pins():
    """ソースに固定した版を読み取る。読み取れなかった項目は、値をNoneにする。"""
    def find(text, pattern):
        m = re.search(pattern, text)
        return m.group(1) if m else None

    deps = read("text_compositor/deps.py")
    build_dist = read("viewer/scripts/build-dist.js")
    common = read("text_compositor/templates/_common.typ")
    pins = {
        "Mermaid": find(deps, r"npm/mermaid@([\d.]+)/"),
        "PlantUML": find(deps, r"download/v([\d.]+)/plantuml-mit"),
        "D2": find(deps, r'D2_RELEASE = "v([\d.]+)"'),
        "Temurin JRE 21": find(deps, r'TEMURIN_JRE_RELEASE = "jdk-([\d.]+\+\d+)"'),
        "Noto Sans JP": find(deps, r"releases/download/Sans([\d.]+)/"),
        "組込版Python": find(build_dist, r"const PYTHON = \{\s*version: '([\d.]+)'"),
    }
    for name, version in re.findall(r"@preview/([a-z0-9-]+):([\d.]+)", common):
        pins[f"Typstパッケージ {name}"] = version
    return pins


def parse_version(text):
    """"21.0.12.1+1"や"v3.30.0"を、大小を比べられる形にする。
    "+"の前（版）と後（ビルド番号）を分ける。版は、桁数が違っても、前の桁が同じなら、桁が多いほうを新しいとする。
    """
    main, _, build = text.lstrip("v").partition("+")
    numbers = tuple(int(n) for n in re.findall(r"\d+", main))
    build_numbers = tuple(int(n) for n in re.findall(r"\d+", build))
    return numbers, build_numbers


def is_newer(latest, current):
    return parse_version(latest) > parse_version(current)


def is_major_update(latest, current):
    return parse_version(latest)[0][:1] != parse_version(current)[0][:1]


def http_get(url):
    headers = {"User-Agent": "text-compositor-check-pins"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8")


def http_json(url):
    return json.loads(http_get(url))


def latest_npm(package):
    return http_json(f"https://registry.npmjs.org/{urllib.parse.quote(package, safe='@')}/latest")["version"]


def latest_github_release(repo, prefix=""):
    """GitHubのReleaseのうち、タグが`prefix`で始まる最新の版を返す（ドラフト・プレリリースを除く）。
    Releaseの一覧は、作成順で、版の順ではない（Temurinは、古い版のReleaseを、後から作り直すことがある）。
    そのため、先頭ではなく、版の最大値を取る。
    """
    releases = http_json(f"https://api.github.com/repos/{repo}/releases?per_page=100")
    versions = [release["tag_name"][len(prefix):] for release in releases
                if not (release.get("draft") or release.get("prerelease")) and release["tag_name"].startswith(prefix)
                and re.search(r"\d", release["tag_name"][len(prefix):])]
    if not versions:
        raise LookupError(f"{repo}に、{prefix or '(prefixなし)'}で始まるReleaseがない")
    return max(versions, key=parse_version)


def latest_typst_package(name):
    versions = [entry["version"] for entry in http_json("https://packages.typst.org/preview/index.json")
                if entry["name"] == name]
    if not versions:
        raise LookupError(f"Typst Universeに{name}がない")
    return max(versions, key=parse_version)


def latest_embed_python(current):
    """固定した版と同じ系（3.14など）で、組込版のzipがある、最新のパッチ版を返す。
    パッチ版のフォルダはあるのに、組込版のzipがない場合は、バイナリの配布が終わったと見て、注記を付ける。
    """
    minor = ".".join(current.split(".")[:2])
    listing = http_get("https://www.python.org/ftp/python/")
    patches = sorted({m for m in re.findall(rf'href="({re.escape(minor)}\.\d+)/"', listing)}, key=parse_version, reverse=True)
    if not patches:
        raise LookupError(f"python.orgに{minor}系のフォルダがない")
    for patch in patches:
        url = f"https://www.python.org/ftp/python/{patch}/python-{patch}-embed-amd64.zip"
        request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "text-compositor-check-pins"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT):
                pass
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            raise
        note = ""
        if patch != patches[0]:
            note = f"{patches[0]}は、ソースだけの配布（組込版のバイナリは{patch}が最後）。次の系へ移す時期"
        return patch, note
    raise LookupError(f"{minor}系に、組込版のzipがない")


def latest_versions(pins):
    """部品名 -> (最新版, 注記) または、取得に失敗したときは、例外を値にして返す。"""
    fetchers = {
        "Mermaid": lambda: (latest_npm("mermaid"), ""),
        "PlantUML": lambda: (latest_github_release("plantuml/plantuml", "v"), ""),
        "D2": lambda: (latest_github_release("d2lang/d2", "v"), ""),
        "Temurin JRE 21": lambda: (latest_github_release("adoptium/temurin21-binaries", "jdk-"), ""),
        "Noto Sans JP": lambda: (latest_github_release("notofonts/noto-cjk", "Sans"), ""),
        "組込版Python": lambda: latest_embed_python(pins["組込版Python"]),
    }
    for name in pins:
        if name.startswith("Typstパッケージ "):
            package = name.split(" ", 1)[1]
            fetchers[name] = (lambda package=package: (latest_typst_package(package), ""))
    results = {}
    for name, fetch in fetchers.items():
        try:
            results[name] = fetch()
        except Exception as error:  # 1つの部品の失敗で、ほかの確認を止めない
            results[name] = error
    return results


def build_report(pins, latest):
    """(Markdownの報告, 差の数, 確認できなかった数)を返す。"""
    rows = []
    updates = failures = 0
    for name, current in pins.items():
        result = latest[name]
        if isinstance(result, Exception):
            failures += 1
            rows.append(f"| {name} | {current} | 確認できず（{type(result).__name__}: {result}） | |")
            continue
        newest, note = result
        if is_newer(newest, current):
            updates += 1
            kind = "**メジャー更新**。互換性を確認する" if is_major_update(newest, current) else "更新あり"
            rows.append(f"| {name} | {current} | **{newest}** | {kind}{('。' + note) if note else ''} |")
        else:
            rows.append(f"| {name} | {current} | {newest} | 最新{('。' + note) if note else ''} |")
    repo = os.environ.get("GITHUB_REPOSITORY", "tokudiro/text-compositor")
    lines = [
        "コードに直接書いた部品の版を、上流の最新版と比べた結果です（週次のワークフロー`check-pins`が、自動で書いています）。",
        "",
        "| 部品 | 固定している版 | 上流の最新版 | 状態 |",
        "| --- | --- | --- | --- |",
        *rows,
        "",
        f"更新の方針は、[doc/viewer-distribution.md](https://github.com/{repo}/blob/master/doc/viewer-distribution.md)の「更新の方針」にあります。"
        "Electron・PyPIのパッケージ・GitHub Actionsは、Dependabotが、PRで知らせます。",
    ]
    return "\n".join(lines) + "\n", updates, failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", help="報告（Markdown）の書き出し先")
    args = parser.parse_args(argv)

    pins = read_pins()
    missing = [name for name, version in pins.items() if version is None]
    if missing:
        print("固定した版を、ソースから読み取れませんでした: " + ", ".join(missing), file=sys.stderr)
        return 2

    report, updates, failures = build_report(pins, latest_versions(pins))
    print(report)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"has_updates={'true' if updates else 'false'}\n")
    print(f"差: {updates}件、確認できず: {failures}件", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
