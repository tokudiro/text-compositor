"""wingetのマニフェスト（Obunzu Markdown Viewer。#334）を、版ごとに作る。

ポータブルZIP（GitHubのReleaseに添付する`Obunzu-Markdown-Viewer-<版>-win-x64.zip`）を、`portable (zip)`として配る。
自前のインストーラーは作らない。出力は、`microsoft/winget-pkgs`に出すPRの形（`manifests/t/tokudiro/ObunzuMarkdownViewer/<版>/`）。

使い方（SHA256は、次のどれかで渡す。省略すると、Releaseの添付ファイルのダイジェストを、`gh`で読む）:
    python packaging/winget/make_manifest.py --version 0.4.6 --out temp/winget
    python packaging/winget/make_manifest.py --version 0.4.6 --zip dist/Obunzu-Markdown-Viewer-0.4.6-win-x64.zip --out temp/winget
    python packaging/winget/make_manifest.py --version 0.4.6 --sha256 <64桁の16進> --out temp/winget

作ったマニフェストは、`winget validate --manifest <フォルダ>`で検証できる。手順は、doc/viewer-distribution.mdの
「wingetでの配布」を参照。
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

PACKAGE_ID = "tokudiro.ObunzuMarkdownViewer"
PUBLISHER = "tokudiro"
REPO = "tokudiro/text-compositor"
SCHEMA = "1.10.0"
EXE_NAME = "obunzu-markdown-viewer.exe"
COMMAND_ALIAS = "obunzu"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
SHA256_RE = re.compile(r"^[0-9A-Fa-f]{64}$")


def release_name(version):
    """ZIPの名前と、展開したフォルダの名前（viewer/scripts/build-dist.jsのreleaseNameと、そろえる）。"""
    return f"Obunzu-Markdown-Viewer-{version}-win-x64"


def installer_url(version):
    return f"https://github.com/{REPO}/releases/download/v{version}/{release_name(version)}.zip"


def output_dir(version):
    """winget-pkgsの、フォルダの配置（`manifests/<公開元の頭文字>/<公開元>/<パッケージ>/<版>/`）。"""
    return os.path.join("manifests", PUBLISHER[0].lower(), PUBLISHER, PACKAGE_ID.split(".", 1)[1], version)


def render(version, sha256):
    """3つのマニフェストの中身を、{ファイル名: 文字列}で返す。"""
    if not VERSION_RE.match(version):
        raise ValueError(f"version must look like 0.4.6: {version!r}")
    if not SHA256_RE.match(sha256):
        raise ValueError("sha256 must be 64 hex digits")
    sha = sha256.upper()
    head = f"PackageIdentifier: {PACKAGE_ID}\nPackageVersion: {version}\n"
    version_yaml = (
        f"# yaml-language-server: $schema=https://aka.ms/winget-manifest.version.{SCHEMA}.schema.json\n"
        f"{head}DefaultLocale: en-US\nManifestType: version\nManifestVersion: {SCHEMA}\n")
    installer_yaml = (
        f"# yaml-language-server: $schema=https://aka.ms/winget-manifest.installer.{SCHEMA}.schema.json\n"
        f"{head}"
        "Platform:\n- Windows.Desktop\n"
        "MinimumOSVersion: 10.0.0.0\n"
        "InstallerType: zip\n"
        "NestedInstallerType: portable\n"
        "NestedInstallerFiles:\n"
        f"- RelativeFilePath: {release_name(version)}\\{EXE_NAME}\n"
        f"  PortableCommandAlias: {COMMAND_ALIAS}\n"
        "Installers:\n"
        "- Architecture: x64\n"
        f"  InstallerUrl: {installer_url(version)}\n"
        f"  InstallerSha256: {sha}\n"
        f"ManifestType: installer\nManifestVersion: {SCHEMA}\n")
    locale_yaml = (
        f"# yaml-language-server: $schema=https://aka.ms/winget-manifest.defaultLocale.{SCHEMA}.schema.json\n"
        f"{head}"
        "PackageLocale: en-US\n"
        f"Publisher: {PUBLISHER}\n"
        f"PublisherUrl: https://github.com/{PUBLISHER}\n"
        f"PublisherSupportUrl: https://github.com/{REPO}/issues\n"
        "PackageName: Obunzu Markdown Viewer\n"
        f"PackageUrl: https://github.com/{REPO}\n"
        "License: MIT\n"
        f"LicenseUrl: https://github.com/{REPO}/blob/master/LICENSE\n"
        "ShortDescription: A fast, read-only Markdown viewer for docs, diagrams and design as code.\n"
        "Description: Obunzu is a read-only viewer for Markdown with diagrams (Mermaid, PlantUML, D2, Graphviz and more), "
        "built on text-compositor. It runs locally and bundles everything it needs.\n"
        f"Moniker: {COMMAND_ALIAS}\n"
        "Tags:\n- markdown\n- viewer\n- diagrams\n"
        f"ManifestType: defaultLocale\nManifestVersion: {SCHEMA}\n")
    return {
        f"{PACKAGE_ID}.yaml": version_yaml,
        f"{PACKAGE_ID}.installer.yaml": installer_yaml,
        f"{PACKAGE_ID}.locale.en-US.yaml": locale_yaml,
    }


def sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_from_release(version):
    """Releaseの添付ファイルのダイジェストを、`gh`で読む（ZIPは、取得しない）。"""
    out = subprocess.run(
        ["gh", "release", "view", f"v{version}", "--repo", REPO, "--json", "assets"],
        capture_output=True, text=True, check=True).stdout
    name = f"{release_name(version)}.zip"
    for asset in json.loads(out)["assets"]:
        if asset["name"] == name:
            digest = asset.get("digest") or ""
            if digest.startswith("sha256:"):
                return digest.split(":", 1)[1]
            raise SystemExit(f"the release asset {name} has no sha256 digest; pass --zip or --sha256")
    raise SystemExit(f"the release v{version} has no asset {name}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--version", required=True, help="0.4.6のような版（先頭のvは付けない）")
    p.add_argument("--out", required=True, help="出力の基準のフォルダ（この下に、manifests/...ができる）")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--sha256", help="ZIPのSHA256（64桁の16進）")
    src.add_argument("--zip", help="ZIPのパス（SHA256を計算する）")
    args = p.parse_args(argv)

    if args.sha256:
        sha = args.sha256
    elif args.zip:
        sha = sha256_of_file(args.zip)
    else:
        sha = sha256_from_release(args.version)
    files = render(args.version, sha)
    target = os.path.join(args.out, output_dir(args.version))
    os.makedirs(target, exist_ok=True)
    for name, text in files.items():
        with open(os.path.join(target, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
