# Obunzu

English | [日本語](README-ja.md)

A fast, read-only Markdown viewer for Docs, Diagrams and Design as Code, built with Electron on top of text-compositor. The name is a coined word: "Observe" plus 文図 (*bunzu*, "text and diagrams"), pronounced "oh-boon-zu". Open a Markdown file and it is converted to HTML by the resident Python worker (`render_html`, see section 14 of [doc/spec.md](../doc/spec.md)) and shown with its diagrams (Mermaid, PlantUML, D2, `svg`) as images. There is no editor and no PDF output.

The visual design policy (colors, spacing, fonts) is in [doc/viewer-visual-design.md](../doc/viewer-visual-design.md).

The display engine was chosen by measurement: see [doc/html-viewer-benchmark.md](../doc/html-viewer-benchmark.md). Electron with `--disable-gpu --in-process-gpu` felt the fastest, so those flags are applied by default (set `VIEWER_GPU=1` to turn them off).

This directory is a separate Node.js project from the Python package on PyPI. Nothing here is included in the sdist or wheel.

The version shown in the window title is `version` in `package.json`. It is kept the same as the text-compositor version in `pyproject.toml` (`tests/test_viewer_version.py` checks this), so bump both together, including `package-lock.json`.

## Run

Requirements: [Node.js](https://nodejs.org/) 20 or later, and a Python that can import `text_compositor` with its dependencies.

```bash
cd viewer
npm install
npm start -- path/to/file.md
```

The worker's Python is searched in this order:

1. The `TEXT_COMPOSITOR_PYTHON` environment variable (full path to the Python executable)
2. `python-embed/` next to the app (reserved for the distribution package, #168)
3. `python`, `python3` or `py` on `PATH`

When you run from a repository checkout without installing the package, set `TEXT_COMPOSITOR_PYTHONPATH` to the repository root. It is prepended to the worker's `PYTHONPATH`.

If no Python is found, the window still opens and explains what to do.

## Usage

| Action | How |
| --- | --- |
| Open a file | `Ctrl+O`, drag and drop a file onto the window, or pass it as a command-line argument. Opening a file while the viewer is running shows it in the existing window. |
| Reload | `F5` / `Ctrl+R` / the reload button. The scroll position is kept. |
| Zoom | `Ctrl` + mouse wheel, `Ctrl` + `+` / `-`, `Ctrl+0` (100%). Clicking the percentage in the toolbar also resets it. |
| Settings | The gear button in the toolbar, or `Ctrl+,`. Close with the **← 戻る** button, `Esc` or the gear button. Opening a file or reloading closes it too. |
| Show or hide error details | Click the error/warning bar |

Openable files: Markdown (`.md`, `.markdown`) and single diagram files (`.mmd`, `.puml`, `.d2`; `.dot` is shown as code with a warning until Graphviz is supported in HTML output, #181).

While a conversion runs, a "変換中…" indicator is shown. If it fails, the last successful display stays on screen. The error bar shows a one-line summary; a new error also opens the details list, which has each item with its Markdown line (when known) and the tool's output (errors have a red mark and side line, warnings an amber one). Click the bar to close or open the list. Web links in a document open in the default browser; a link or dropped file that points to a Markdown file opens in the viewer. Nothing else can navigate the viewer away from the document.

**Automatic reload**: saving the open Markdown file, or an image it references, refreshes the display (about 0.18 s after the save; the scroll position is kept). The lightning-bolt toggle in the toolbar (highlighted while on; and the View menu) turns it off. Details:

- The directories of the watched files are watched, not the files, so an editor's atomic save (write a temp file, then rename over) is detected. Files that do not exist yet (an image that is created later) are watched too.
- Changes are merged: the conversion starts 150 ms after the last change. A save during a conversion queues one more conversion.
- If a conversion fails, the last successful display stays, the file is still watched, and fixing and saving it recovers automatically.
- The referenced files come from the worker (`dependencies` of `render_html`).

`node scripts/check-auto-reload.js` starts the viewer and checks these behaviors and the latency (it needs Electron and the Python worker; it is not part of `npm test`).

## Settings

The settings screen (gear button) has two items: the **toolbar position** (top or bottom; the error bar follows the toolbar) and the **color scheme** (follow the OS, light or dark). Changes apply at once. The automatic reload toggle is saved as well.

The window size and position are remembered too (also maximized state). If the saved position no longer fits on any screen, for example after unplugging a monitor, only the size is restored.

Settings are stored as `settings.json` in the app's user data folder (`%APPDATA%\Obunzu` on Windows). A missing or broken file, or an unexpected value, falls back to the defaults, so the app always starts.

## Distribution (Windows)

`npm run build-dist` builds a portable ZIP (`dist/Obunzu-<version>-win-x64.zip`, about 162 MB) that runs without Python installed: the Electron app, an embeddable Python next to it (`python-embed/`) with only the packages HTML output needs, and the third-party notices (`licenses/`). `typst` (PDF only) and `playwright` (Mermaid) are not bundled, so **Mermaid diagrams do not render in the ZIP yet** (#207). `node scripts/check-dist.js` runs the unpacked app with every hint of Python removed from the environment. Contents, sizes, on-demand downloads, licenses and how to update: [doc/viewer-distribution.md](../doc/viewer-distribution.md).
## Environment variables

| Variable | Meaning |
| --- | --- |
| `TEXT_COMPOSITOR_PYTHON` | Python executable for the worker |
| `TEXT_COMPOSITOR_PYTHONPATH` | Added to the worker's `PYTHONPATH` (repository checkout without `pip install`) |
| `VIEWER_GPU=1` | Use the standard Chromium GPU settings instead of `--disable-gpu --in-process-gpu` |
| `VIEWER_TRACE=1` | Print startup timings to stderr |
| `VIEWER_DEBUG=1` | Add a "toggle developer tools" item to the View menu |
| `VIEWER_THEME=light` / `dark` | Fix the color scheme regardless of the OS and the settings (for checking both looks) |

## Structure

| Path | Contents |
| --- | --- |
| `src/main.js` | Main process: window, menu, conversion flow, navigation rules |
| `src/worker-client.js` | Client for the Python worker (JSON lines over stdin/stdout) |
| `src/python.js` | Finds the Python for the worker |
| `src/diagnostics.js` | Turns the worker's diagnostics into what the window shows |
| `src/targets.js` | Which files can be opened; how links and drops are handled |
| `src/settings.js` | Reads and writes the settings (falls back to defaults) |
| `src/watcher.js` | Watches the open file and the files it references |
| `scripts/check-auto-reload.js` | Starts the viewer and checks automatic reload (manual) |
| `scripts/check-window.js` | Checks every way of closing the settings screen with real key presses (manual, Windows only) |
| `scripts/check-window-state.js` | Checks that the window size, position and maximized state come back after a restart (manual, Windows only) |
| `scripts/build-dist.js` | Builds the Windows portable ZIP (Electron + embeddable Python + minimal packages + notices) |
| `scripts/check-dist.js` | Runs the unpacked distribution with Python hidden from the environment and checks it (manual, Windows only) |
| `dist-requirements.txt` | Python packages bundled in the distribution (pinned; `typst` and `playwright` are left out) |
| `scripts/build-icons.js` | Exports `assets/icon.ico` and `assets/icon.png` from `assets/icon.svg` |
| `assets/` | The app icon: the source SVG and the exported `.ico` / `.png` |
| `src/chrome/` | The toolbar, the error bar and the diagnostics list |
| `test/` | `node --test` tests (a fake worker covers crashes, timeouts and restarts) |

## Icon

The icon shows a document page with a small diagram (two nodes joined by an arrow) on a sky-blue rounded square: text and diagrams together, which is what Obunzu shows. `assets/icon.svg` is the source. It is original work and follows the repository's license (MIT). It does not use any third-party or character artwork.

After changing `assets/icon.svg`, export again and commit the results. `icon.ico` holds 16, 24, 32, 48, 64, 128 and 256 px. Electron renders the SVG, so no extra packages are needed.

```bash
cd viewer
npm run build-icons
```

## Test

```bash
cd viewer
npm test
```

## Third-party components

Electron (MIT) and its bundled Chromium. The full list of notices for the distribution package is handled in #168.
