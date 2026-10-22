"""図表プラグインの契約とレジストリ（#474・#533。設計は`doc/plugin-architecture.md`の3章）。

図の種類（Mermaid・PlantUMLなど）ごとの情報を、1つの`DiagramPlugin`にまとめ、`Registry`へ登録する。
いまは、フェンス言語の振り分け・拡張子の表・`plugins:`の許可キー・有効無効の既定値などを、複数のファイルが
手で同期している。これらを、レジストリから導けるようにするための土台である。

この段階（#533）では、誰もレジストリを使わない。既存のコードは、まだ、変わらない。
`RenderContext`（キャッシュ・診断・トリムなどの共通部品）は、載せ替えの中で、必要になった分だけ足す。
"""
from dataclasses import dataclass, field
from typing import Mapping, Optional

# 出力方式（設計書3.2.1）。`svg`は、SVGを作って画像として埋め込む。`typst`は、Typstのコードとして直接描く（PDFだけ）。
OUTPUT_SVG = "svg"
OUTPUT_TYPST = "typst"
OUTPUTS = (OUTPUT_SVG, OUTPUT_TYPST)

# `<name>_backend`・`<name>_output`の、既定の値。登録の順に、最初に対応したバックエンドを使う
AUTO = "auto"


class PluginError(Exception):
    """プラグインの契約・選択に関する誤りの、基底。呼び出し側が、診断にして、終了する（Fail-fast）。"""


class PluginRegistrationError(PluginError, ValueError):
    """登録できない（名前・言語・拡張子の重複、契約に反する定義）。コードの誤りなので、利用者の設定の誤りではない。"""


class BackendSelectionError(PluginError):
    """バックエンドまたは出力方式を選べない（設定の値が不正、または、選んだものが対応していない）。"""


@dataclass(frozen=True)
class Support:
    """バックエンドが、あるコードと出力方式に対応するか（設計書3.3）。

    フォールバックの条件は、描画の前の、宣言的な判定だけにする。「描画して、失敗したら別のバックエンドで再試行する」は、
    出力が、入力だけで決まらなくなる（決定論性を損なう）ため、行わない。
    """
    ok: bool
    reason: str = ""

    @staticmethod
    def UNSUPPORTED(reason: str) -> "Support":
        return Support(False, reason)


Support.OK = Support(True)


@dataclass(frozen=True)
class RenderResult:
    """描画の結果。要求された出力方式に応じて、SVG（文字列）か、Typstへ直接渡す断片のどちらか。"""
    output: str
    svg: Optional[str] = None
    typst: Optional[str] = None

    def __post_init__(self):
        if self.output not in OUTPUTS:
            raise ValueError(f"Unknown output {self.output!r} (expected one of {OUTPUTS}).")
        if self.output == OUTPUT_SVG and self.svg is None:
            raise ValueError("A result for the 'svg' output needs svg.")
        if self.output == OUTPUT_TYPST and self.typst is None:
            raise ValueError("A result for the 'typst' output needs typst.")


@dataclass(frozen=True)
class Option:
    """図種に固有の`plugins:`キー（例: `plantuml_auto_download`）。"""
    key: str
    default: object = False
    description: str = ""


class Backend:
    """図を描く、1つの実装（自作の変換器・Java・ブラウザなど）。サブクラスで、`version`と`render`を書く。

    outputs: 出力できる方式。**`svg`を、必ず含める**（HTML・Viewer・単体の図は、常にSVGを使うため。設計書3.2.1）。
    """
    name: str = ""
    outputs: tuple = (OUTPUT_SVG,)

    def version(self) -> str:
        """キャッシュのキーに入る。バックエンドの名前を含める（別のバックエンドのキャッシュを、再利用しないため。設計書3.6）。"""
        raise NotImplementedError

    def supports(self, code: str, output: str) -> Support:
        """このコードを、この出力方式で、描けるか。既定は、出力方式だけで決める。構文を見る場合は、上書きする。"""
        if output in self.outputs:
            return Support.OK
        return Support.UNSUPPORTED(f"the {self.name} backend cannot produce {output!r} output")

    def render(self, code: str, ctx, output: str) -> RenderResult:
        raise NotImplementedError

    def check_env(self) -> list:
        """`--check-env`の項目。環境の確認が要らないバックエンドは、空でよい。"""
        return []

    def prefetch(self, codes: list, ctx) -> None:
        """任意。描く前に、まとめて準備できるもの（PlantUMLのJVMの一括起動など）があれば、ここで行う。"""


@dataclass(frozen=True)
class DiagramPlugin:
    """図の種類1つ分の、登録情報。

    name: `plugins:`のキー（例: "plantuml"）。 langs: フェンスの言語。 file_exts: 章ファイルの拡張子（ドットつき）。
    label: 診断に出す名前。 backends: バックエンド名 → 実装。**並べた順が、`auto`の優先順位**。
    """
    name: str
    langs: tuple
    file_exts: tuple
    label: str
    backends: Mapping[str, Backend]
    default_enabled: bool = True
    default_backend: str = AUTO
    default_output: str = OUTPUT_SVG
    options: tuple = field(default_factory=tuple)

    def __post_init__(self):
        where = f"plugin {self.name!r}"
        if not self.name:
            raise PluginRegistrationError("A plugin needs a name.")
        for ext in self.file_exts:
            if not ext.startswith(".") or ext != ext.lower():
                raise PluginRegistrationError(f"{where}: file extension {ext!r} must start with '.' and be lowercase.")
        for lang in self.langs:
            if lang != lang.lower():
                raise PluginRegistrationError(f"{where}: fence language {lang!r} must be lowercase.")
        if not self.backends:
            raise PluginRegistrationError(f"{where}: at least one backend is required.")
        for key, backend in self.backends.items():
            if key != backend.name:
                raise PluginRegistrationError(f"{where}: backend registered as {key!r} is named {backend.name!r}.")
            if key == AUTO:
                raise PluginRegistrationError(f"{where}: {AUTO!r} is reserved and cannot be a backend name.")
            if OUTPUT_SVG not in backend.outputs:
                raise PluginRegistrationError(f"{where}: backend {key!r} must be able to produce 'svg' output.")
            unknown = [o for o in backend.outputs if o not in OUTPUTS]
            if unknown:
                raise PluginRegistrationError(f"{where}: backend {key!r} declares unknown output(s) {unknown}.")
        if self.default_output not in OUTPUTS:
            raise PluginRegistrationError(f"{where}: default_output {self.default_output!r} is not one of {OUTPUTS}.")
        if self.default_backend != AUTO and self.default_backend not in self.backends:
            raise PluginRegistrationError(f"{where}: default_backend {self.default_backend!r} is not a registered backend.")


class Registry:
    """登録された`DiagramPlugin`の一覧。現在、複数のファイルが手で同期している情報を、ここから導く。"""

    def __init__(self):
        self._plugins = {}      # name → DiagramPlugin（登録の順を保つ）
        self._by_lang = {}
        self._by_ext = {}

    def register(self, plugin: DiagramPlugin) -> None:
        """登録する。名前・フェンスの言語・拡張子が、すでに、ほかのプラグインのものなら、登録しない。"""
        if plugin.name in self._plugins:
            raise PluginRegistrationError(f"Plugin {plugin.name!r} is already registered.")
        for lang in plugin.langs:
            if lang in self._by_lang:
                raise PluginRegistrationError(f"Fence language {lang!r} of {plugin.name!r} belongs to {self._by_lang[lang].name!r}.")
        for ext in plugin.file_exts:
            if ext in self._by_ext:
                raise PluginRegistrationError(f"File extension {ext!r} of {plugin.name!r} belongs to {self._by_ext[ext].name!r}.")
        self._plugins[plugin.name] = plugin
        for lang in plugin.langs:
            self._by_lang[lang] = plugin
        for ext in plugin.file_exts:
            self._by_ext[ext] = plugin

    def plugins(self) -> tuple:
        return tuple(self._plugins.values())

    def get(self, name: str) -> Optional[DiagramPlugin]:
        return self._plugins.get(name)

    def by_lang(self, lang: str) -> Optional[DiagramPlugin]:
        """フェンスの言語から、プラグインを引く（`_render_diagram_fence_inner`の、if/elifの連鎖の代わり）。"""
        return self._by_lang.get(lang.lower())

    def by_ext(self, ext: str) -> Optional[DiagramPlugin]:
        """章ファイルの拡張子（ドットつき）から、プラグインを引く。"""
        return self._by_ext.get(ext.lower())

    def file_exts(self) -> dict:
        """拡張子 → プラグインの名前（`DIAGRAM_FILE_EXTS`の代わり）。"""
        return {ext: plugin.name for ext, plugin in self._by_ext.items()}

    def allowed_plugin_keys(self, with_selection: bool = False) -> set:
        """`plugins:`の許可キー（`config.py`の`_ALLOWED_PLUGINS_KEYS`の代わり）。

        `<name>_backend`・`<name>_output`は、設定として公開する段階（設計書4章のステップ6）まで、含めない。
        """
        keys = set()
        for plugin in self._plugins.values():
            keys.add(plugin.name)
            keys.update(option.key for option in plugin.options)
            if with_selection:
                keys.update((f"{plugin.name}_backend", f"{plugin.name}_output"))
        return keys

    def resolve_enabled(self, plugins_config: Mapping) -> dict:
        """`{name: 有効か}`。`plugins:`に書かれていなければ、プラグインの既定値（`project.py`・`api.py`の、`.get(...)`の列の代わり）。"""
        plugins_config = plugins_config or {}
        return {name: bool(plugins_config.get(name, plugin.default_enabled)) for name, plugin in self._plugins.items()}

    def resolve_output(self, plugin: DiagramPlugin, plugins_config: Mapping, target: str = "pdf") -> str:
        """出力方式を決める（設計書3.2.1）。HTML・Viewer・単体の図（target != "pdf"）は、設定によらず`svg`。"""
        if target != "pdf":
            return OUTPUT_SVG
        requested = (plugins_config or {}).get(f"{plugin.name}_output", AUTO)
        if requested == AUTO:
            return plugin.default_output
        if requested not in OUTPUTS:
            raise BackendSelectionError(f"{plugin.label}: {plugin.name}_output must be one of {AUTO}, {', '.join(OUTPUTS)} (got {requested!r}).")
        return requested

    def resolve_backend(self, plugin: DiagramPlugin, code: str, output: str, plugins_config: Mapping) -> Backend:
        """バックエンドを選ぶ（設計書3.2・3.3）。

        `auto`は、登録の順に、最初に`supports`が対応と答えたもの。明示した名前は、そのバックエンドだけを使い、
        対応しないときは、別のものへ戻さず、エラーにする（Fail-fast）。
        """
        requested = (plugins_config or {}).get(f"{plugin.name}_backend", plugin.default_backend)
        if requested == AUTO:
            reasons = []
            for backend in plugin.backends.values():
                support = backend.supports(code, output)
                if support.ok:
                    return backend
                reasons.append(f"{backend.name}: {support.reason}")
            raise BackendSelectionError(f"{plugin.label}: no backend can render this diagram as {output!r} ({'; '.join(reasons)}).")
        backend = plugin.backends.get(requested)
        if backend is None:
            raise BackendSelectionError(
                f"{plugin.label}: unknown backend {requested!r} in {plugin.name}_backend (expected {AUTO} or one of {', '.join(plugin.backends)}).")
        support = backend.supports(code, output)
        if not support.ok:
            raise BackendSelectionError(f"{plugin.label}: the {requested!r} backend cannot render this diagram as {output!r} ({support.reason}).")
        return backend
