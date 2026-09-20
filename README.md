# text-compositor

*[日本語版 (Japanese version)](README-ja.md)*

A tool that treats multiple text files as independent fragments and deterministically composes them into a single human-readable PDF document. Works equally well for AI-generated drafts refined by humans and for existing, hand-authored documents you want to organize and consolidate.

This README covers only the essentials needed to get started quickly. For a full walkthrough of `config.yaml` and how to write your source documents, see the [usage guide](doc/usage/) (which can also be built into a PDF with `cd doc/usage && python ../../build.py`). For detailed design rationale and implementation status, see [doc/spec.md](doc/spec.md). Differences from general-purpose tools like Quarto are summarized in [doc/diff.md](doc/diff.md).

## Features

- Combines multiple text files (chapters) into a single PDF
- Markdown → AST via [markdown-it-py](https://github.com/executablebooks/markdown-it-py) → deterministic conversion to [Typst](https://typst.app/) syntax → PDF output
- Outputs other text files to the PDF unchanged
- Separates the tool itself from the documentation (source files), which can live anywhere outside the repository
- Python-centric with minimal downloads, no dependency on external servers or SaaS (runs the same way on GitHub Actions and locally on Windows/Linux/macOS)

Files listed in `chapters` are handled differently depending on their extension:

- `.md`/`.markdown`: converted as Markdown
- `.yaml`/`.yml`/`.json`: rendered as monospaced text with syntax highlighting
- `.dot`/`.gv`, `.mmd`, `.puml`/`.plantuml`/`.pu`, `.d2`, `.pikchr`: each rendered as a one-chapter diagram (Graphviz, Mermaid, PlantUML, D2, Pikchr respectively)
- `.csv`: rendered as a structured Typst table
- everything else (plain text, code files, etc.): rendered as plain monospaced text

See the [usage guide](doc/usage/) for details.

## Requirements

- Python 3.10+

> **Windows note — Microsoft Store Python is not supported, even inside `pipx`/`venv`:** If Python was installed from the Microsoft Store, this tool cannot be used with it, full stop — `pipx` or a `venv` does **not** work around this.
>
> Windows redirects that Python's writes under `%LOCALAPPDATA%` into a package-private folder, and this redirection follows the Store installation into any `venv`/`pipx` environment created from it (verified by testing), breaking every subprocess-based feature (PlantUML, Mermaid, D2) even though the files appear to exist to Python itself.
>
> Before installing this tool, install Python from [python.org](https://www.python.org/downloads/) (or another non-Store distribution such as `winget install Python.Python.3.12`) and use that Python for the steps below. Run `text-compositor --check-env` afterward to confirm the environment is set up correctly.

There are two ways to install and run this tool.

### Option A: `pip install` (recommended)

```bash
pipx install text-compositor
```

`pipx` installs the tool into an isolated environment and exposes the `text-compositor` command — recommended for most users. If you're developing this tool itself, use a `venv` instead so an editable install (`pip install -e .`) picks up code changes immediately:

```bash
python -m venv .venv
.venv/bin/pip install -e .        # Windows: .venv\Scripts\pip install -e .
```

### Option B: Clone and run directly (no installation)

```bash
pip install -r requirements.txt
```

No Typst compiler binary is bundled; it's obtained from the `typst` package (PyPI wheel) installed via `pip install` above. No additional downloads or installation steps are needed.

### Keeping up to date

Security and bug fixes ship as new releases. There is no automatic update, so use the latest release: `pipx upgrade text-compositor` (or `pip install -U text-compositor`). For the [Obunzu Viewer](viewer/README.md), download the latest ZIP from the [Releases page](https://github.com/tokudiro/text-compositor/releases/latest). The Viewer bundles its own Python, so a new ZIP also updates that Python and the other bundled parts.

### Using Mermaid diagrams (optional)

This is only needed if your source documents use ` ```mermaid ` fences (or specify an `.mmd` file directly in `chapters`). With Option A, install the `mermaid` extra:

```bash
pipx install "text-compositor[mermaid]"
# or, if already installed: pipx inject text-compositor playwright==1.62.0
```

With Option B (clone and run directly):

```bash
pip install playwright==1.62.0
```

- **A Google Chrome or Microsoft Edge installation already present on your system** (no new download by default; it's auto-detected and reused at build time)
- The `playwright` package above (used only to connect to the existing browser via CDP; Playwright's own browser-download feature is not used by default)

Node.js/npm is not required. At build time, the official single-file Mermaid bundle (`mermaid.min.js`, ~3.4MB) is fetched and loaded into a headless browser to convert diagrams to SVG (the bundle JS itself is cached under an OS-standard user cache directory — e.g. `%LOCALAPPDATA%\text-compositor\Cache` on Windows, `~/.cache/text-compositor` on Linux — and conversion results are cached under `.text-compositor/cache/`; neither is re-fetched afterward). None of this is needed for documents that don't use Mermaid.

If no Chrome/Edge is found on the system, the build fails by default. Setting `plugins: { mermaid_auto_download: true }` instead auto-fetches Playwright's own Chromium, but **this download is about 700MB** (this setting exists as a last resort for when no pre-installed browser is available; downloading that much by default is intentionally avoided).

### Using PlantUML diagrams (optional)

No extra `config.yaml` settings are needed to use ` ```plantuml ` fences in your source documents (or to specify a `.puml` file directly in `chapters`) — `plugins.plantuml` defaults to `true` and no additional `pip install` is required.

- If Java (11+) is available locally, it's reused as-is
- Otherwise, Eclipse Temurin JRE (Adoptium distribution, ~49.7MB) is auto-fetched and cached by default under the same user cache directory as above. Setting `plugins: { plantuml_auto_download: false }` disables the auto-fetch and fails the build instead
- GitHub Actions' `ubuntu-latest` ships with Java by default, so no extra download happens on CI

The layout engine is the pure-Java Smetana implementation, so no external binary like Graphviz (`dot`) is required. PlantUML itself (MIT edition, ~17.6MB) is cached under the same user cache directory, and conversion results are cached under `.text-compositor/cache/`, same as Mermaid.

### Using D2 diagrams (optional)

No extra `config.yaml` settings are needed to use ` ```d2 ` fences in your source documents (or to specify a `.d2` file directly in `chapters`) — `plugins.d2` defaults to `true` and no additional `pip install` is required.

- If the `d2` command is available locally, it's reused as-is
- Otherwise, the official D2 CLI binary (a single Go executable, ~13MB) is auto-fetched and cached by default under the same user cache directory as above. Setting `plugins: { d2_auto_download: false }` disables the auto-fetch and fails the build instead

Unlike Java (used by PlantUML) or a browser (used by Mermaid), GitHub Actions' `ubuntu-latest` does not ship with D2 preinstalled, so a `d2` diagram triggers this ~13MB download on every CI run (this project's workflows don't persist the cache directory across separate runs).

## Usage

If installed via `pip`/`pipx` (Option A):

```bash
text-compositor --config <path/to/text-compositor.config.yaml>
```

If cloned and run directly (Option B):

```bash
python build.py --config <path/to/text-compositor.config.yaml>
```

If `--config` is omitted, `text-compositor.config.yaml` (or `.json`) located directly in the current directory is auto-detected.

```bash
cd my-project/
python /path/to/text-compositor/build.py
```

Run `text-compositor --check-env` (or `python build.py --check-env`) to check your environment (dependencies, Typst version, cached assets, Mermaid/PlantUML/D2 prerequisites) without running a build.

Other flags control runtime behavior only (not document content, which stays entirely in `config.yaml`): `-q`/`--quiet` suppresses `[Info]`-level logging, `-v`/`--verbose` adds extra detail (which chapter is being processed, cache reuse), and `--keep-temp` keeps the intermediate `temp_build.typ` around after a successful build instead of deleting it (useful for debugging; it's always kept after a failed build).

`--watch` keeps running after the first build and rebuilds whenever it detects a save in the config, the input files, or a custom `.typ` template. A failed build does not stop it; fix the file and save again. Press Ctrl+C to stop. Changes to files outside the project directory (e.g. images referenced via `../`) are not detected.

`--if-changed` skips the build, like `make`, when the output PDF is newer than the config, the input files, the template, and text-compositor itself (judged by modification time only). Without it, the PDF is always regenerated. Changes to Typst's version, to files outside the project directory, or to environment variables used by `variables` are not detected. On CI, `actions/checkout` resets every file's modification time, so restore the output directory from a cache if you want the skip to take effect.

`--clean` deletes the output PDF and the intermediate files under `.text-compositor/` (`temp_build.typ`, `_template.typ`, `_common.typ`) without building. `--clean-cache` additionally deletes the diagram cache (`.text-compositor/cache/`). Input files and the config are never deleted.

### Python API

`text_compositor.Session` and `build_markdown()` turn a single Markdown file into a PDF without a `config.yaml`, and return warnings and errors as structured diagnostics (Markdown file and line included) instead of printing them. A resident worker (`python -m text_compositor.worker`) exposes the same over JSON lines on stdin/stdout, for GUI viewers. See the usage guide chapter "Using from Python" and section 14 of [doc/spec.md](doc/spec.md).

```python
from text_compositor import Session

with Session() as session:  # reuses the Mermaid browser and the Typst compiler across builds
    result = session.build("doc.md", "out/doc.pdf")
    print(result.ok, result.pdf_path, [d.message for d in result.diagnostics])
```

`session.render_html("doc.md")` (experimental, [#161](https://github.com/tokudiro/text-compositor/issues/161)) writes a self-contained HTML file instead. Diagrams (Mermaid, PlantUML, D2, `svg`) become images next to it. `typst-exec` and raw HTML are not supported yet and are shown as code with a warning. Graphviz is drawn with the Typst package `diagraph`, the same as in the PDF (`shape=record` and a graph-level `label` cannot be drawn and produce a warning).

See [sample/text-compositor.config.yaml](sample/text-compositor.config.yaml) for how to write the config file, and the [usage guide](doc/usage/) for details on `document:`/`plugins:`, front matter, Marp directives, and more. The Markdown files listed in `chapters` are concatenated in order to produce the PDF.

## Trying the sample

```bash
cd sample/
python ../build.py
```

This generates `sample/SampleDocument.pdf`. Two more samples show other templates: `sample/paper/` (two-column paper layout, `template.path: paper`) and `sample/universe-ilm/` (a [Typst Universe](https://typst.app/universe) template used through an adapter; needs network access on the first build).

## Implementation status

The core feature implemented so far is combining multiple files into a single PDF according to the config file specified via `--config` (or auto-detected). Expanding CLI options (e.g., overriding the output path) is still in the planning stage. See [GitHub Issues](https://github.com/tokudiro/text-compositor/issues) for known issues and upcoming plans.

## License

[MIT License](LICENSE)
