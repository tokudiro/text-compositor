# 図表プラグインの設計（親Issue [#474](https://github.com/tokudiro/text-compositor/issues/474)、検討 [#448](https://github.com/tokudiro/text-compositor/issues/448)）

> **状態：設計案（未実装）。** 本書は、図表レンダラーをプラグインとして切り出すための設計である。実装は、本書の合意後に、別issueで段階的に行う。実装済みの部分は、合意後に[spec.md](spec.md)の11章へ反映する。

## 1. 目的と、#448との関係

プラグイン化の検討は、[#448](https://github.com/tokudiro/text-compositor/issues/448)（検討：図の描画をプラグイン化する）で、すでに始まっている。#448の「進め方（案）」は、次の4段階である。

1. 内蔵の描画を、同じ登録の仕組みに載せ替える（外に出さない、本体の中の整理）。
2. 外部コマンドのプラグインを、設定で登録できるようにする。
3. 重い4つ（Mermaid・PlantUML・D2・Structurizr）を、追加部品として切り離す。
4. 必要なら、軽い代替をプラグインとして足す。

**本書は、このうち1を具体化するものである。** 2・3は、本書の対象外とし、#448で引き続き扱う。4（軽い代替）は、#474の段階2以降（ネイティブ変換器）が担う。#448の論点との対応は、次のとおり。

| #448の論点 | 本書での扱い |
| --- | --- |
| 1. プラグインの形（外部コマンドかPython関数か） | 本書は、組み込みのPythonの契約（3.1）だけを定める。外部コマンドは、2で扱う |
| 2. 登録の方法 | 組み込みの一覧（3.4）のみ。設定やエントリポイントによる登録は、2で扱う |
| 3. 出力の形式 | `RenderResult`が、SVGとTypstの断片の両方を表す（3.1）。Typstで描く図も、内蔵のプラグインとして載せる |
| 4. 安全性 | 組み込みのみのため、新しい実行経路は増えない。外部コマンドの許可は、2で扱う |
| 5. 決定性とキャッシュ | 3.3（宣言的なフォールバック）と3.6（キャッシュキー）で保つ |
| 7. 本体と追加部品の分け方 | 対象外（3）。ただし、バックエンドを分けることで、後から切り離しやすくなる |
| 8. 互換性 | 3.2・3.3。同じフェンス名のまま、バックエンドを選ぶ |

#448は、ChordPro（#440）・ピクト図解（#447）を足した後の着手を想定していた。どちらも実装済み（closed）のため、その前提は満たされている。

### 目的

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

### 2.1 現状の出力方式の分類

PDFとHTMLに、図をどの形で渡しているかは、図種ごとにコードが決めており、設計としては明示されていない。調べた結果は次のとおり（3.2.1の`default_output`の根拠になる）。

| 分類 | 図種 | PDF | HTML |
| --- | --- | --- | --- |
| **A. SVGを作り、画像として埋め込む** | Mermaid・PlantUML・D2・Structurizr・Vega・WaveDrom・Bytefield・bizmodel・`svg`フェンス | SVGのファイルを`image()`で埋め込む | 同じSVG |
| **B. Typstの中でSVGを作り、画像として埋め込む** | Pikchr | Typstのパッケージ`kip`（WASM）が返したSVGを、`image(bytes(out), format: "svg")`で埋め込む。**結果は画像** | Typstでコンパイルして得たSVG |
| **C. Typstが図形として直接描く** | Graphviz（`diagraph`）・CeTZ・Fletcher・timeliney・finite | Typstのコードとして本文に描く（図形・文字はベクター） | Typstでコンパイルして得たSVG |
| **D. 中間表現から、出力ごとに別々に描く** | ChordPro（**本書の対象外**。下記） | 解析結果をTypstのコードに描く | 同じ解析結果をHTMLに描く |

* **Pikchrは、載せ替えで、Aになった**（[#474](https://github.com/tokudiro/text-compositor/issues/474)の最初の載せ替え）。PDFも、HTMLと同じSVG（キャッシュを共有）を、画像として埋め込む。載せ替えの前は、Typstの中で`kip`を動かし、その場で画像にしていた。ただし、キャッシュしていたSVGは、Typstが書き出した「入れ物」のSVG（Pikchrの図を、base64の画像として入れ子にしたもの）で、そのままPDFへ埋め込むと、入れ子の中の文字が描かれなかった（箱だけが残る）。そのため、バックエンドは、入れ物から、中のPikchrのSVGを取り出し、入れ物が持つ幅・高さ（pt）を付けて返す（`pikchr_render._pikchr_svg`）。ギャラリーのPDFは、載せ替えの前後で、画素まで一致した。縦に長い図は、`fit-image`の高さの上限（12cm）で縮み、これまで、はみ出して作っていた空白のページが、なくなった。
* **BとCは、見た目が似ていても別物である。** Pikchrは、Typstが実行するだけで、PDFに入るのは画像である。Cは、PDFに入るのがTypstの図形そのものである。
* **Graphvizは、Cである。** `diagraph`は、WASMのGraphvizでレイアウトを求め、図形をTypstで描く。これは、リポジトリの記述から確かめた。`diagraph`が`shape=record`・`Mrecord`・図全体の`label`を描けない（spec 11章。「`diagraph`の制限」として警告する）のは、図形の描画を`diagraph`自身が持つためである。また、`finite`は`diagraph-layout`に依存する（spec 11章）。`diagraph`のソース（`packages.typst.org`）そのものは、この環境から取得できず、読んでいない。
* **Dは、ネイティブ変換器の手本になる。** 解析して中間表現を作り、出力ごとに別の描画器で描く構造は、3.2.1の「同じ中間表現から`svg`と`typst`を描く」と同じである。
* **ChordProは、本書の対象外とする。** 図ではなく、コード譜（歌詞の上にコードを並べる文書要素）であり、HTMLにSVGではなくHTML自体を出す。3.2.1の「HTMLは常に`svg`」「すべてのバックエンドは`svg`を出力できる」が当てはまらない。`DiagramPlugin`の契約に載せると、この規則に例外が要る。したがって、ChordProは、現行の経路（`chordpro_render.py`・`renderer_chordpro.py`、拡張子`.cho`・`.chordpro`・`.pro`、`plugins.chordpro`）のまま、レジストリの外に置く。レジストリが導出する拡張子の対応・許可キー（3.4）は、ChordProの分を、これまでどおり別に持つ。
  ただし、**ChordProの中のタブ譜（`{start_of_tab}`〜`{end_of_tab}`）は、図として扱うことを検討する。** 現状は、中身を探さず、等幅の素のテキストとして描いている（`renderer_chordpro.py`）。タブ譜は、弦と指板を表す図であり、ASCIIの記述から、五線に近い図（SVG）を作れる。その場合、ChordPro本体は対象外のまま、タブ譜の部分だけを、図のプラグイン（例：`tab`）に委譲する。詳しくは5章・6章と、[#476](https://github.com/tokudiro/text-compositor/issues/476)。

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
    default_output: str = "svg"    # 出力方式の既定（3.2）。"svg" | "typst"
    options: tuple[Option, ...]    # この図種固有のplugins:キー（例: plantuml_auto_download）

class Backend:
    name: str
    outputs: tuple[str, ...]       # 出力できる方式。"svg"は必ず含む。例: ("svg",)、("svg", "typst")
    def version(self) -> str: ...                       # キャッシュキーに入る。バックエンド名を含む
    def supports(self, code: str, output: str) -> Support: ...   # 3.3。既定は、outputsに含まれる方式なら対応
    def render(self, code: str, ctx: RenderContext, output: str) -> RenderResult: ...
    def check_env(self) -> list[CheckResult]: ...       # --check-envの項目
    def prefetch(self, codes: list[str], ctx) -> None: ...   # 任意。PlantUMLのJVMの一括起動など
```

`RenderResult`は、`output`で要求された方式に応じて、SVG（文字列）か、Typstへ直接渡す断片のどちらかである。方式の選択は3.2で定める。Typstが描く図（Graphviz・Pikchr・CeTZなど）は、現行どおり、Typstのコードを返せる。

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
| `typst` | Typstのパッケージ（出力方式は図種による。2.1のBとC） | Graphviz・Pikchr・CeTZなど |

設定は、`plugins:`に、バックエンド名を値に取る形を足す。**既存の記法（`plantuml: true/false`）は、そのまま動く。**

```yaml
plugins:
  plantuml: true             # 従来どおり。有効・無効（既定true）
  plantuml_backend: auto     # 新規。native | java | auto（既定auto）
```

* 値は、`<name>_backend`というキーで指定する（出力方式は`<name>_output`。3.2.1）。`plugins:`の中の名前空間を保ち、既存の`xxx_auto_download`と並べられる。
* `auto`は、登録順にバックエンドを並べ、**最初に`supports`が対応と答えたもの**を使う。
* 明示した値（`native`など）では、そのバックエンドだけを使う。`supports`が非対応なら、診断つきで終了する（Fail-fast）。
* ネイティブ版が存在しない現時点では、`auto`は、現行のバックエンドに解決される。**既存の挙動は変わらない。**

### 3.2.1 出力方式（SVGとTypst直接）

描画の結果を、どの形で本文に渡すかを、**出力方式**として、バックエンドの選択とは別の軸で切り替えられるようにする。

| 方式 | 意味 | 特徴 |
| --- | --- | --- |
| `svg` | SVGを作り、画像としてTypstに埋め込む | PDF・HTML・Viewerで共通。キャッシュと比較が簡単。文字は画像になり、図中リンクは使えない |
| `typst` | Typstのコードとして、本文に直接描く | 本文のフォント・色を継承し、図中の文字がPDFの検索・選択の対象になる。図中リンクも使える。PDF専用 |

```yaml
plugins:
  plantuml_output: auto      # 新規。svg | typst | auto（既定auto）
```

* **標準はSVG。** 図種の`default_output`は、新規のプラグインでは`svg`とする。`typst`は、その方式が必要な図種だけに、後から足す。
* `auto`は、`default_output`に解決される。2.1の分類Cの図種（Graphviz・CeTZ・Fletcher・timeliney・finite）は、現行のPDFの出力を保つため、`default_output`を`typst`とする。分類A・Bの図種（Pikchrを含む。PDFに入るのが画像のため）は、`svg`とする。**既存の出力は変わらない。**
* バックエンドは、`outputs`に、出力できる方式を宣言する。**すべてのバックエンドは、`svg`を出力できなければならない。** HTML・Viewer・図の単体表示は、常にSVGを使うためである（分類Cの図も、HTMLではTypstでコンパイルしてSVGを作っている）。`typst`は任意である。
* **出力先による制約。** HTML出力・Viewer・単体の図は、設定にかかわらず`svg`で描く。`typst`が効くのは、PDF出力だけである。
* 明示した方式（`typst`）を、選ばれたバックエンドが出力できない場合は、診断つきで終了する（Fail-fast）。`auto`のバックエンド選択では、方式も含めて`supports(code, output)`で判定し、`outputs`が対応するバックエンドを選ぶ。
* ネイティブ変換器は、`svg`と`typst`で、**同じ中間表現から**描く。レイアウトの結果が方式によって変わらないようにするためである（段階2）。

`typst`方式に対しては、`ctx`が、本文のフォントと色を渡す。`svg`方式でも、同じ値を`font-family`などに反映し、見た目の不一致を減らす。

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
* 出力方式が`svg`のときは、現行のSVGのキャッシュと同じ形にする。`typst`のときは、キャッシュキーの`kind`に方式を含め（例：`plantuml:typst`）、SVGのキャッシュと混ざらないようにする。
* **現行のバックエンドの`tool_version`の文字列は、変えない。** 移行によって既存のキャッシュが無効にならないようにする。

## 4. 移行手順

各ステップは、独立したPRとする。**全ステップで、既存サンプルのビルド結果（SVG・PDF）が、移行の前後で変わらないこと**を確認基準とする。

1. **基盤の導入**：`plugins/registry.py`と契約を追加する。まだ誰も使わない。契約の単体テストだけを書く。
2. **Pikchrの移行**：最も小さい図種で、全経路（フェンス、章ファイル、有効・無効、`--check-env`、キャッシュ）を、レジストリ経由に切り替える。
3. **Typstを使う図の移行**：分類C（Graphviz・CeTZ・Fletcher・timeliney・finite。`default_output: typst`）と、分類B（Pikchr。`svg`）。出力方式の違いを、プラグインの契約で扱えることを、ここで確かめる。
   あわせて、分類Aのうち、ブラウザも外部ツールも使わないもの（bizmodel・`svg`フェンス）も、ここで移行する。
4. **外部ツール・ブラウザを使う図の移行**：D2・Structurizr・PlantUML・Mermaid・Vega・WaveDrom・Bytefield（後の3つは、ヘッドレスブラウザまたはホストで描く）。ここで、`java`・`browser`・`host`・`binary`のバックエンドを定義する。
5. **周辺の統合**：`host_renderers.py`の統合、`config.py`の許可キーの生成、`project.py`・`api.py`の`plugins_config.get(...)`の列の削除、`renderer_diagrams.py`の整理。
6. **バックエンド・出力方式の選択の公開**：`<name>_backend`と`<name>_output`を、設定として有効にし、spec・使い方ガイドへ書く。

ステップ1〜5は、利用者から見える挙動を変えない（内部のリファクタリング）。ステップ6で初めて、設定が増える。

### 確認基準

* `tests/`の既存のテスト（`test_diagram_cache_key.py`、`test_config_key_validation.py`、`test_bundled_diagram_tools.py`など）が、変更なく通ること。
* `doc/test_spec/`と`sample/`のビルド結果が、移行の前後で一致すること（SVGは、バイト単位で比較する）。
* `benchmarks/`で、所要時間が悪化しないこと。
* 診断のメッセージと行番号が、変わらないこと。

## 5. 見送る・決めないもの

* **外部コマンドのプラグイン・追加部品としての切り離し**：#448の2・3。本書の基盤の上に、後から載せる。
* **第三者の拡張点**：3.4のとおり。組み込みのみ。
* **ホスト描画のシグネチャの統一**：3.5のとおり。Electron側との契約を保つ。
* **ネイティブ変換器・中間表現**：段階2以降。本書は、それらを載せる基盤だけを定める。
* **設定の名前の最終決定**：`<name>_backend`と`<name>_output`は案である。未決事項（#474）として残し、ステップ6の前に確定する。
* **ChordProのプラグイン化**：2.1のとおり、図ではなく、HTMLにHTML自体を出すため、対象外。必要になった時点で、別の契約（出力ごとの描画器を持つ文書要素）として検討する。
* **ChordProのタブ譜の図化**：対象外ではなく、**本書の基盤の上に載せる候補**とする。タブ譜（ASCIIの記述）を、SVGの図へ変換する`tab`プラグインを、通常の`DiagramPlugin`として作り、次の2つから使えるようにする。
  * 単独のフェンス（```` ```tab ````）と章ファイル。
  * ChordProの`{start_of_tab}`区間。ChordProの描画器が、区間の中身を`tab`プラグインに渡し、得たSVGを埋め込む。ChordProの契約は変えない（`tab`は、`svg`を出力する通常の図として振る舞う）。
  変換器の設計（記法の範囲、弦数・チューニング、小節線、リズム表記）は、段階2以降のネイティブ変換器と同じ扱いとし、本書では決めない。
* **外部ツール版の削除**：行わない。ネイティブ版が対応できない構文のための、フォールバックとして残す。

## 6. 未決事項

* `auto`の既定を、ネイティブ版が揃った後に、どうするか。ネイティブ版が先に選ばれると、見た目が変わる図が出る。図種・構文ごとに、`supports`の範囲を小さく保ち、段階的に広げる前提で決める。
* `supports`の判定を、簡易な字句の走査でよいか。誤判定（対応すると答えて、描画で失敗する）は、Fail-fastで報告されるため安全側に倒れるが、その場合の診断に「ネイティブ版で失敗した。`<name>_backend: java`で回避できる」と案内を付けるか。
* **タブ譜の図化の範囲（ChordPro）。** 次の3点を決める。
  * 入力：ChordProの`{start_of_tab}`の中身は、ASCIIタブ譜（`e|---0---|`の形）に限るか。ほかの記法（ABC、MusicXMLなど）は扱わないか。
  * 出力：`svg`を標準とする（基盤の規則と同じ）。コードやフレット番号を、本文のフォントで描きたい場合の`typst`方式は、後から足す。
  * 後方互換：現行の等幅表示を、既定のまま残すか。残す場合は、`plugins.tab`のような有効・無効、または`{start_of_tab: render}`のような属性で、図化を選べるようにする。既存のコード譜の見た目を、勝手に変えない。
* ~~描画層を、SVG経由にするか、Typstへの直接出力にするか（#474の未決事項）。~~ **決定：SVGを標準とし、Typst直接出力は、図中リンクやフォントの継承が必要になった図種だけ、後から追加する。** 両方を切り替えられるよう、出力方式を契約に含める（3.2.1）。残る論点は、次の2つ。
  * `typst`方式で、図中リンクをどう記述するか（フェンスの属性か、図の記法の拡張か）。最初に`typst`方式を足す図種の設計時に決める。
  * `typst`方式のエラーの診断。Typstのエラーは`eval`の中の位置を含まないため、原稿の行への対応が粗くなる。ネイティブ変換器が、Typstへ渡す前に、自分の入力の行を検査して報告する。
