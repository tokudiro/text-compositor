# 図表プラグインの設計（親Issue [#474](https://github.com/tokudiro/text-compositor/issues/474)）

> **状態：設計案（未実装）。** 本書は、図表レンダラーをプラグインとして切り出すための設計である。実装は、本書の合意後に、別issueで段階的に行う。実装済みの部分は、合意後に[spec.md](spec.md)の11章へ反映する。

## 1. 目的

親Issue（#474）の段階1にあたる。最終的な目的は、diagrams as codeの記法を変えずに、PlantUML・Mermaidなどの描画を、Java・ブラウザに依存しない自作の変換器へ、段階的に置き換えることである。そのために、**図種を1か所で定義でき、1図種に複数のバックエンドを持てる**基盤を先に作る。

本書の対象は基盤だけである。ネイティブ変換器そのもの（中間表現、シーケンス図エンジンなど）は、対象外とする（段階2以降）。

## 2. 現状の問題

調査の結果、図種を1つ追加・変更するときに、次の場所を手で同期する必要があることが分かった。

| 場所 | 図種ごとに持っているもの |
| --- | --- |
| `renderer_diagrams.py`（約1100行） | `_render_xxx`・`_xxx_svg_path`・ツールの取得と検出。`_render_diagram_fence_inner`のif/elifの連鎖で、フェンス言語から振り分ける |
| `renderer.py` | `__init__`の`xxx_enabled`引数（約20個）。`DIAGRAM_FILE_EXTS`（拡張子と図種の対応） |
| `project.py` | `plugins_config.get("xxx", 既定値)`を、図種の数だけ並べる |
| `api.py` | 同じ`plugins_config.get(...)`の列を、HTML出力側でも繰り返す |
| `config.py` | `_ALLOWED_PLUGINS_KEYS`（許可キー） |
| `env_check.py` | `--check-env`の項目 |
| `host_renderers.py`・`worker.py` | Mermaid・Vega・WaveDrom・Bytefieldの「描画を呼び出し元（Electron）に任せる口」。形が同じ4組のset関数と、worker.pyの設定・解除 |
| `deps.py` | 取得するツールのバージョンとSHA256 |

この構造では、1つの図種に複数のバックエンド（ネイティブ版と外部ツール版）を持たせる分岐が、これらすべてに入る。変換器を足すほど収拾がつかなくなる。

一方、既存の設計には、守るべきものがある。

* **Fail-fast（spec 9章）**：描画に失敗したら、テキストへ静かにフォールバックせず、診断つきで終了する。
* **決定論的な出力**：同じ入力から同じ出力を得る。ツールのバージョンとSHA256を固定する。
* **キャッシュ**：`_diagram_cache_key(kind, tool_version, code)`で、種別・レンダラーのバージョン・入力をハッシュする。
* **診断の行番号**：図の中の行を、原稿の行へ直して報告する。

これらは、プラグイン化の後も変えない。

## 3. 設計

### 3.1 プラグインの契約

図種ごとに、1つの`DiagramPlugin`を定義する。

```python
class DiagramPlugin:
    name: str                      # plugins:のキー。例: "plantuml"
    langs: tuple[str, ...]         # フェンス言語。例: ("plantuml",)
    file_exts: tuple[str, ...]     # 章ファイルの拡張子。例: (".puml", ".plantuml", ".pu")
    label: str                     # 診断に出す名前。例: "PlantUML"
    default_enabled: bool = True
    backends: dict[str, Backend]   # バックエンド名 → 実装（3.2）
    default_backend: str = "auto"
    options: tuple[Option, ...]    # この図種固有のplugins:キー（例: plantuml_auto_download）

class Backend:
    name: str
    def version(self) -> str: ...                       # キャッシュキーに入る。バックエンド名を含む
    def supports(self, code: str) -> Support: ...       # 3.3。既定は常に対応
    def render(self, code: str, ctx: RenderContext) -> RenderResult: ...
    def check_env(self) -> list[CheckResult]: ...       # --check-envの項目
    def prefetch(self, codes: list[str], ctx) -> None: ...   # 任意。PlantUMLのJVMの一括起動など
```

`RenderResult`は、SVG（文字列）と、必要なら、Typstへ直接渡す断片のどちらかである。Typstが描く図（Graphviz・Pikchr・CeTZなど）は、現行どおり、Typstのコードを返せる。

`RenderContext`が、共通の部品を渡す。各プラグインが個別に持っているものを、ここに集める。

* キャッシュ：`ctx.cached_svg(kind, version, code, produce)`。パス、キー、`Reusing cached ...`のログを一括で持つ。
* 診断：`ctx.error(label, message, line=..., code_line=...)`。原稿の行への直しを含む。
* トリム：`ctx.maybe_trim(svg)`（`plugins.diagram_trim`）。
* ホスト描画：`ctx.host(name)`（3.5）。
* ツールの取得：`ctx.ensure_tool(...)`。既存の`deps.py`の関数（SHA256固定、再試行、`.part`ファイル）を呼ぶ。

### 3.2 バックエンドと選択

1つの図種が、複数のバックエンドを持てる。

| バックエンド | 意味 | 例 |
| --- | --- | --- |
| `native` | 自作の変換器（段階2以降） | PlantUMLのシーケンス図 |
| `java` | 現行の`plantuml.jar` | PlantUML |
| `browser` | 現行のPlaywright＋システムのブラウザ | Mermaid |
| `host` | 呼び出し元（Viewer）に任せる | Mermaid（Electron） |
| `binary` | 外部の実行ファイル | D2 |
| `typst` | Typstのパッケージ | Graphviz・Pikchr・CeTZなど |

設定は、`plugins:`に、バックエンド名を値に取る形を足す。**既存の記法（`plantuml: true/false`）は、そのまま動く。**

```yaml
plugins:
  plantuml: true             # 従来どおり。有効・無効（既定true）
  plantuml_backend: auto     # 新規。native | java | auto（既定auto）
```

* 値は、`<name>_backend`というキーで指定する。`plugins:`の中の名前空間を保ち、既存の`xxx_auto_download`と並べられる。
* `auto`は、登録順にバックエンドを並べ、**最初に`supports`が対応と答えたもの**を使う。
* 明示した値（`native`など）では、そのバックエンドだけを使う。`supports`が非対応なら、診断つきで終了する（Fail-fast）。
* ネイティブ版が存在しない現時点では、`auto`は、現行のバックエンドに解決される。**既存の挙動は変わらない。**

### 3.3 フォールバックの規則（Fail-fastとの両立）

「ネイティブ版が未対応の構文は、外部ツール版へ戻す」と、Fail-fastの方針（描画失敗時は静かにフォールバックしない）が、衝突しないようにする。

* フォールバックの条件は、**描画前の宣言的な判定**（`supports(code)`）だけとする。「描画を試して、例外が出たら別のバックエンドで再試行する」は、禁止する。
* `supports`は、`Support.OK`、または`Support.UNSUPPORTED(reason)`を返す。理由は、`-v`で、どの構文のためにどのバックエンドへ回ったかを表示するために使う。
* 描画の失敗（構文エラー、内部エラー）は、従来どおり、診断つきで終了する。別のバックエンドは試さない。
* この規則により、出力が、「描画の成否」ではなく「入力」だけで決まる。決定論性（9章）が保たれる。

### 3.4 レジストリ

`text_compositor/plugins/`（新規）に、プラグインを1図種1ファイルで置き、`registry.py`が、これらを集める。

```text
text_compositor/plugins/
    __init__.py       # 登録（組み込みプラグインの一覧）
    registry.py       # DiagramPlugin・Backend・RenderContext・解決ロジック
    pikchr.py         # 例（最初に移行する）
    ...
```

レジストリが、次を**提供する**。これらが、現在は手書きで同期されている場所を置き換える。

| 現在の場所 | レジストリからの導出 |
| --- | --- |
| `_render_diagram_fence_inner`のif/elif | `registry.by_lang(lang)` |
| `DIAGRAM_FILE_EXTS` | 各プラグインの`file_exts` |
| `_ALLOWED_PLUGINS_KEYS` | 各プラグインの`name`・`<name>_backend`・`options` |
| `project.py`・`api.py`の`plugins_config.get(...)`の列 | `registry.resolve_enabled(plugins_config)`が、`{name: bool}`を返す |
| `Renderer.__init__`の`xxx_enabled`引数 | `enabled: Mapping[str, bool]`1つ |
| `env_check.py`の各図の項目 | 各バックエンドの`check_env()` |

プラグインは、**組み込みのみ**とする。外部のパッケージが後から登録する仕組み（エントリポイントなど）は、本書の対象外とする（需要が出てから検討する）。「プラグイン」という語は、現行のspec・設定の用語（`plugins:`）に合わせたものであり、第三者の拡張点を意味しない。

### 3.5 ホスト描画の一般化

`host_renderers.py`の4組のset関数を、1つの口に統合する。

```python
host_renderers.set_host_renderer(name, fn_or_None)   # nameは、図種のname
```

* 呼び出し元（`worker.py`）は、`host`バックエンドを持つ図種を、レジストリから列挙して設定・解除する。図種を足したときに、`worker.py`を直さなくてよい。
* 各図の`fn`のシグネチャ（Mermaidは`(diagram_id, code, js_path)`、Vegaは`(diagram_id, lang, spec, script, js)`など）は、図種ごとに異なる。移行時は、**シグネチャを変えない**（Electron側のJSとの契約を壊さないため）。統一は別の課題とする。

### 3.6 キャッシュ

* キャッシュキーは、現行の`_diagram_cache_key(kind, tool_version, code)`を、そのまま使う。
* `tool_version`に、バックエンド名を含める（例：`native-1`、`java-<jar版>`）。これにより、バックエンドを切り替えたときに、別のバックエンドのキャッシュを再利用しない。
* **現行のバックエンドの`tool_version`の文字列は、変えない。** 移行によって既存のキャッシュが無効にならないようにする。

## 4. 移行手順

各ステップは、独立したPRとする。**全ステップで、既存サンプルのビルド結果（SVG・PDF）が、移行の前後で変わらないこと**を確認基準とする。

1. **基盤の導入**：`plugins/registry.py`と契約を追加する。まだ誰も使わない。契約の単体テストだけを書く。
2. **Pikchrの移行**：最も小さい図種で、全経路（フェンス、章ファイル、有効・無効、`--check-env`、キャッシュ）を、レジストリ経由に切り替える。
3. **Typstで描く図の移行**：Graphviz・CeTZ・Fletcher・timeliney・finite・WaveDrom・Bytefield・Vega・bizmodel。
4. **外部ツールを使う図の移行**：D2・Structurizr・PlantUML・Mermaid。ここで、`java`・`browser`・`host`・`binary`のバックエンドを定義する。
5. **周辺の統合**：`host_renderers.py`の統合、`config.py`の許可キーの生成、`project.py`・`api.py`の`plugins_config.get(...)`の列の削除、`renderer_diagrams.py`の整理。
6. **バックエンド選択の公開**：`<name>_backend`を、設定として有効にし、spec・使い方ガイドへ書く。

ステップ1〜5は、利用者から見える挙動を変えない（内部のリファクタリング）。ステップ6で初めて、設定が増える。

### 確認基準

* `tests/`の既存のテスト（`test_diagram_cache_key.py`、`test_config_key_validation.py`、`test_bundled_diagram_tools.py`など）が、変更なく通ること。
* `doc/test_spec/`と`sample/`のビルド結果が、移行の前後で一致すること（SVGは、バイト単位で比較する）。
* `benchmarks/`で、所要時間が悪化しないこと。
* 診断のメッセージと行番号が、変わらないこと。

## 5. 見送る・決めないもの

* **第三者の拡張点**：3.4のとおり。組み込みのみ。
* **ホスト描画のシグネチャの統一**：3.5のとおり。Electron側との契約を保つ。
* **ネイティブ変換器・中間表現**：段階2以降。本書は、それらを載せる基盤だけを定める。
* **設定の名前の最終決定**：`<name>_backend`は案である。未決事項（#474）として残し、ステップ6の前に確定する。
* **外部ツール版の削除**：行わない。ネイティブ版が対応できない構文のための、フォールバックとして残す。

## 6. 未決事項

* `auto`の既定を、ネイティブ版が揃った後に、どうするか。ネイティブ版が先に選ばれると、見た目が変わる図が出る。図種・構文ごとに、`supports`の範囲を小さく保ち、段階的に広げる前提で決める。
* `supports`の判定を、簡易な字句の走査でよいか。誤判定（対応すると答えて、描画で失敗する）は、Fail-fastで報告されるため安全側に倒れるが、その場合の診断に「ネイティブ版で失敗した。`<name>_backend: java`で回避できる」と案内を付けるか。
* 描画層を、SVG経由にするか、Typstへの直接出力にするか（#474の未決事項）。`RenderResult`が両方を表せるようにしてあるが、ネイティブ変換器の設計時に決める。
