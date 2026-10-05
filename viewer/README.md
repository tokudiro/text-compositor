# Obunzu Markdown Viewer

English | [日本語](README-ja.md)

Obunzu Markdown Viewer ("Obunzu" for short) is a fast, read-only Markdown viewer for Docs, Diagrams and Design as Code, built with Electron on top of text-compositor. The name is a coined word: "Observe" plus 文図 (*bunzu*, "text and diagrams"), pronounced "oh-boon-zu". Open a Markdown file and it is converted to HTML by the resident Python worker (`render_html`, see section 14 of [doc/spec.md](../doc/spec.md)) and shown with its diagrams (Mermaid, PlantUML, D2, Structurizr, Graphviz, Pikchr, CeTZ, Fletcher, timeliney, finite, Vega-Lite, Vega, WaveDrom, Bytefield, `svg`) as images. There is no editor and no PDF output.

This README is for developers. The guide for people who use Obunzu is the [Obunzu usage guide](../doc/obunzu-guide/) (in Japanese; its PDF is attached to each release).

The visual design policy (colors, spacing, fonts) is in [doc/viewer-visual-design.md](../doc/viewer-visual-design.md).

The display engine was chosen by measurement: see [doc/html-viewer-benchmark.md](../doc/html-viewer-benchmark.md). Electron with `--disable-gpu --in-process-gpu` felt the fastest, so those flags are applied by default (set `VIEWER_GPU=1` to turn them off).

The design for making the display engine swappable (core/screen/shell split, the worker protocol, what a new shell must implement) is in [doc/viewer-engine-architecture.md](../doc/viewer-engine-architecture.md) (in Japanese).

This directory is a separate Node.js project from the Python package on PyPI. Nothing here is included in the sdist or wheel.

The version shown in the window title is `version` in `package.json`. It is kept the same as the text-compositor version in `pyproject.toml` (`tests/test_viewer_version.py` checks this), so bump both together, including `package-lock.json`.

## Run

Requirements: [Node.js](https://nodejs.org/) 22.12 or later, and a Python that can import `text_compositor` with its dependencies.

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
| Open a file | `Ctrl+O`, drag and drop a file onto the window, or pass it as a command-line argument. Opening a file while the viewer is running shows it in the existing window. The `Ctrl+O` dialog starts in the folder of the file you opened last, and can be narrowed by kind: 文 (prose: Markdown and `.txt`), Markdown, 図 (diagrams), or CSV. |
| Back / Forward | `Alt+Left` (Back) / `Alt+Right` (Forward) / toolbar Back and Forward buttons (mouse back/forward buttons also work; also in the View menu). After following links in a document or opening other files, you can navigate back to previous documents and forward again. Previous scroll positions are restored. |
| Reload | `F5` / `Ctrl+R` / the reload button. The scroll position is kept. |
| CSV header row | While a `.csv` is open, the table button in the toolbar (or View > "CSV: 1行目を見出しにする") switches between a header row and all data rows. The choice is remembered. |
| Zoom | `Ctrl` + mouse wheel, `Ctrl` + `+` / `-`, `Ctrl+0` (100%). Clicking the percentage in the toolbar also resets it. |
| Search (#325) | The magnifying-glass button, or `Ctrl+F`, opens a search bar under the toolbar. Matches are highlighted in yellow, the current one in orange, with a count. `Enter` / `Shift+Enter` (or the ▲▼ buttons) move to the next/previous match. The `.*` button switches to regular expressions, `Aa` toggles case sensitivity (an invalid regular expression is shown as an error in the bar and is not run). Close with `Esc` or the ✕ button. |
| Copy text (#409) | Select text and right-click: the menu starts with **コピー** (only when something is selected) and **すべて選択** (always). `Ctrl+C` and `Ctrl+A` work too. The copy keeps the formatting (plain text and HTML), so a table may paste as a table. With a link, image or line number under the pointer, their items follow in the same menu, after a separator. |
| Save images (#327) | Right-click any diagram or image to save it. For SVGs, you can choose "画像（SVG）を保存…" (lossless vector) or "画像（PNG）を保存…" (high-resolution raster, 2x scale). Non-SVG images can be saved in their original format. The save dialog starts in the document's folder or the last saved image folder. |
| Tabs (#332) | Available when the setting **複数のタブ** is on (default: off). `Ctrl+Shift+O` (or the "+" in the tab strip) opens another document in a new tab and keeps the current one. Dropping a file with `Ctrl` held also opens a new tab. `Ctrl+W`, the close button at the right end of the tab strip (for the current tab) or a middle click on a tab closes a tab; `Ctrl+Tab` / `Ctrl+Shift+Tab` switch (clicking a tab works too). The tab strip shows only while there are two or more tabs. Scroll position, search, back/forward and automatic reload are kept per tab. There is one Python worker for all tabs, so while one tab converts a heavy diagram, the other tab's conversion waits. |
| File tree (#339) | The button at the left end of the toolbar, or `Ctrl+B`, opens the sidebar. **File > フォルダを開く…** (or the folder button in the sidebar) picks a folder and shows it as a tree. Clicking a file opens it in the current tab and highlights it; clicking a folder expands it (its direct children are read only then, so even thousands of files open quickly). Only files the viewer can open are listed; folders starting with `.`, `node_modules` and `.text-compositor` are hidden. With a single file open (single-file mode) the sidebar is closed; `Ctrl+B` opens it with a hint. Opening a folder opens it, and opening a file outside the folder returns to single-file mode and closes it (a file inside the folder keeps the folder; #373). Neither the folder nor the sidebar's open/closed state is remembered across launches. **Chapter list (project mode, #373)**: choosing a config file (`text-compositor.config.yaml` or `.json`, detected by name) with "Open file", drop or the command line shows its `chapters` in the sidebar in the written order (a `section` is a heading, shown open; `aggregate` chapters, files the viewer cannot open and malformed chapters are left out). A chapter opens its own file. The main pane first shows the config source. The list comes from one `list_chapters` request to the worker and no chapter file is read (500 chapters take about 0.5 s from launch). An unreadable config shows no sidebar and puts the reason in the warning banner. A config file clicked in the folder tree opens as a plain file. Arrow keys, `Enter`, `Home` and `End` work in the tree. Turn it off with the setting **ファイルツリー** (default: on), which also hides the button and the menu item. |
| Settings | The gear button in the toolbar, or `Ctrl+,`. Close with the **閉じる** button, `Esc` or the gear button. Opening a file or reloading closes it too. |
| Show or hide error details | Click the error/warning bar |

Openable files: Markdown (`.md`, `.markdown`), single diagram files (`.mmd`, `.puml`, `.d2`, `.dot`, `.gv` and `.pikchr` are drawn as diagrams; Graphviz is drawn with the bundled Typst and its `diagraph` package, the same as in the PDF; `shape=record` and a graph-level `label` cannot be drawn and produce a warning), plain text (`.txt`, shown as monospace text and never as Markdown), CSV (`.csv`, as a table whose first row is the header) SVG (`.svg`, as an image), image files (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.avif`, `.bmp`, shown as one image fit to the window width; click it to switch to actual size, where zoom works too; #413), and settings files and source code (`.yaml`, `.json`, `.py` and so on, as syntax-highlighted monospace text, without colors above about 128 KB; `.html` is shown as source and never run; Pygments is bundled, #218). Text and CSV must be UTF-8 without a BOM (Shift_JIS, UTF-16 and UTF-8 with a BOM are reported as errors), and only the first 512 KB is shown for a larger file, with a note. Everything else (other image formats such as `.tiff`, PDF, files without an extension, unknown extensions, folders) is not opened: the error bar says what can be opened. A missing file given on the command line is reported too. Dropping several files opens the first one. A link in a document to any local file opens it in the viewer (and shows the same guide if it cannot be opened).

While a conversion runs, a "変換中…" indicator is shown. If it fails, the last successful display stays on screen. The error bar shows a one-line summary; a new error also opens the details list, which has each item with its Markdown line (when known) and the tool's output (errors have a red mark and side line, warnings an amber one). Click the bar to close or open the list. Web links in a document open in the default browser; a link or dropped file that points to a Markdown file opens in the viewer. Nothing else can navigate the viewer away from the document.

**Automatic reload**: saving the open Markdown file, or an image it references, refreshes the display (about 0.18 s after the save; the scroll position is kept). The lightning-bolt toggle in the toolbar (highlighted while on; and the View menu) turns it off. Details:

- The directories of the watched files are watched, not the files, so an editor's atomic save (write a temp file, then rename over) is detected. Files that do not exist yet (an image that is created later) are watched too.
- Changes are merged: the conversion starts 150 ms after the last change. A save during a conversion queues one more conversion.
- If a conversion fails, the last successful display stays, the file is still watched, and fixing and saving it recovers automatically.
- The referenced files come from the worker (`dependencies` of `render_html`).

`node scripts/check-auto-reload.js` starts the viewer and checks these behaviors and the latency (it needs Electron and the Python worker; it is not part of `npm test`).

## Settings

The settings screen (gear button) has three items: the **toolbar position** (top or bottom; the error bar follows the toolbar), the **color scheme** (follow the OS, light or dark), and **where to open files** (the folder the `Ctrl+O` dialog starts in). The last one is one of: **OSにゆだねる** (leave it to the OS; no folder is given), **前回開いたフォルダ** (the default; the folder of the file you opened last), or **特定のフォルダ** (a folder chosen with the **フォルダを選ぶ…** button). If the last opened or specific folder is not set or no longer exists, the dialog starts in the Documents folder. Changes apply at once. The automatic reload toggle is saved as well.

There are more items. First, **変換ファイルの保存場所** and **キャッシュ** (#258). **変換ファイルの保存場所** (where the converted files go) is **アプリの領域** (the default: the converted HTML and the diagram cache are kept in the app's cache folder, so nothing is written to your document's folder, and a document in a read-only place can be opened) or **原稿の隣** (a `.text-compositor/` folder next to the document, as the worker does by default; a document in a place that cannot be written is opened with the app folder instead, with a warning). A third choice, **ファイルを作らない**, is shown grayed out: it is not implemented yet. **キャッシュ** shows the size of the app folder (on Windows, `%LOCALAPPDATA%\text-compositor\Cache\viewer`) and has a delete button. Deleting removes only the converted HTML and the diagram cache there, then converts the open document again; a `.text-compositor/` next to a document, and the downloaded fonts and diagram tools, are left alone.

There are also **外部の画像** (external images; default: not loaded, #238) and three features that add elements to the screen: **行番号の表示** (line number, #328/#357), **見出しのリンク** (heading link, #337) and **コードのコピーボタン** (code copy button, #336). All three default to on and can be turned off in the settings. **ファイルツリー** (file tree, #339) also defaults to on, because nothing on the screen changes until a folder is opened (see the File tree row above). **複数のタブ** (tabs, #332) changes the structure of the screen, so it defaults to off (see the Tabs row above).

The window size and position are remembered too (also maximized state). If the saved position no longer fits on any screen, for example after unplugging a monitor, only the size is restored.

Settings are stored as `settings.json` in the app's user data folder (`%APPDATA%\Obunzu` on Windows). A missing or broken file, or an unexpected value, falls back to the defaults, so the app always starts.

## Distribution (Windows)

`npm run build-dist` builds a portable ZIP (`dist/Obunzu-Markdown-Viewer-<version>-win-x64.zip`, about 298 MB) that runs without Python installed: the Electron app, an embeddable Python next to it (`python-embed/`) with the packages it needs, the Typst compiler, the Noto Sans JP fonts (`fonts/`) and the Typst packages (`typst-packages/`) (all of these work without a network; #263), Java (`jre/`), `plantuml.jar`, the D2 CLI, a trimmed Structurizr CLI, and `mermaid.min.js` (so Mermaid, PlantUML, D2 and Structurizr diagrams all work with zero additional downloads; #290, #310), and the third-party notices (`licenses/`). `playwright` is not bundled. Mermaid diagrams are rendered by Electron's own Chromium (no `playwright` and no Chrome or Edge needed; #207). `node scripts/check-dist.js` runs the unpacked app with every hint of Python removed from the environment. Contents, sizes, licenses and how to update: [doc/viewer-distribution.md](../doc/viewer-distribution.md). Obunzu does not update itself: security fixes ship as new releases, so use the latest ZIP.
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
| `src/selection-menu.js` | The right-click menu items for copying the selection and selecting all (#409) |
| `src/directory-list.js` | Lists one folder's direct children for the file tree (openable files and folders only, never recursive), and checks that a path is inside the tree root (#339) |
| `src/project.js` | Project mode (#373): detects a config file by name and turns the worker's `list_chapters` result into the entries the sidebar tree reads |
| `src/chrome/tree.js` | The file tree in the sidebar: a lazy-loaded WAI-ARIA tree with keyboard support (#339) |
| `src/mermaid-host.js` | Renders Mermaid diagrams in a hidden window when the worker asks (#207) |
| `src/document-tab.js` | The state of one document (tab): file, history, diagnostics, search, content view, conversion queue (#332) |
| `src/settings.js` | Reads and writes the settings (falls back to defaults) |
| `src/workdir.js` | Where the converted HTML and the diagram cache go (app folder or next to the document), and the cache size and delete (#258) |
| `src/watcher.js` | Watches the open file and the files it references |
| `src/image-save.js` | Saves and rasterizes diagrams and images (SVG and PNG, #327) |
| `src/search-match.js` | The text/regex matching behind in-document search (#325); the part with no DOM, so it is unit-tested |
| `scripts/check-auto-reload.js` | Starts the viewer and checks automatic reload (manual) |
| `scripts/check-tabs.js` | Starts the viewer and checks the tabs: opening, switching, keeping the scroll position, closing, turning the setting off (manual; the automatic-update item needs a working file watcher) |
| `scripts/check-selection.js` | Starts the viewer and checks that `Ctrl+C` copies the selection and `Ctrl+A` selects the whole document (manual, Windows only) |
| `scripts/check-project.js` | Starts the viewer and checks project mode: the chapter list, opening a chapter, leaving the project, an unreadable config, and 500 chapters (manual) |
| `scripts/check-sidebar.js` | Starts the viewer and checks that the sidebar opens and closes, narrows the document by its width, follows the mode changes (folder and single-file; #373) and is closed again after a restart (manual) |
| `scripts/check-tree.js` | Starts the viewer and checks the file tree: direct children only, lazy expansion, opening and highlighting, keyboard, files outside the tree, the off setting, and a folder with thousands of files (manual) |
| `scripts/check-search.js` | Starts the viewer and checks in-document search (count, move, regex, case sensitivity, `Ctrl+F`/`Esc`) (manual) |
| `scripts/check-work-location.js` | Starts the viewer with a throwaway user folder and checks where the converted files go, the cache size and delete, and the switch to "next to the document" (manual) |
| `scripts/check-open-files.js` | Opens .txt, .csv, .svg, diagram files, unsupported files, a folder, a missing file and a large file from the command line and checks what is shown (manual) |
| `scripts/check-a11y.js` | Checks the screen for accessibility with axe-core (light and dark) and real key presses: landmarks, names, alerts, focus, `F6` (Windows only; see [doc/viewer-accessibility.md](../doc/viewer-accessibility.md), #340) |
| `scripts/check-window.js` | Checks every way of closing the settings screen with real key presses (manual, Windows only) |
| `scripts/check-window-state.js` | Checks that the window size, position and maximized state come back after a restart (manual, Windows only) |
| `scripts/build-dist.js` | Builds the Windows portable ZIP (Electron + embeddable Python + minimal packages + notices) |
| `scripts/check-dist.js` | Runs the unpacked distribution with Python hidden from the environment and checks it (manual, Windows only) |
| `scripts/check-embed-dependencies.py` | Checks that the embedded Python needs only bundled or standard Windows DLLs (needs `pefile`; manual) |
| `dist-requirements.txt` | Python packages bundled in the distribution (pinned; `playwright` is left out) |
| `scripts/build-icons.js` | Exports `assets/icon.ico` and `assets/icon.png` from `assets/icon.svg` |
| `assets/` | The app icon: the source SVG and the exported `.ico` / `.png` |
| `src/chrome/` | The toolbar, the error bar and the diagnostics list |
| `test/` | `node --test` tests (a fake worker covers crashes, timeouts and restarts; one test runs the real Python worker) |

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

`test/worker-integration.test.js` runs the real Python worker (`render_html` round trips for Markdown and CSV, an error case, and the resident worker). It needs a Python with the packages of `dist-requirements.txt`; without one it is skipped. Set `REQUIRE_WORKER_INTEGRATION=1` to fail instead of skip.

CI (`.github/workflows/viewer.yml`) runs `npm test` on Windows for pull requests and pushes that touch `viewer/` or `text_compositor/`. It does not start Electron. Releases are made together with text-compositor: pushing one tag `v<version>` builds the portable ZIP and attaches it to the same GitHub Release (`.github/workflows/release.yml` and `viewer-release.yml`; the exception for releasing Obunzu alone is a tag `obunzu-markdown-viewer-v<version>`; see [doc/viewer-distribution.md](../doc/viewer-distribution.md)).

## Third-party components

Electron (MIT) and its bundled Chromium. The distribution package (ZIP) ships a list of the bundled software and the full license texts in `licenses/` (see "ライセンス表記" in [doc/viewer-distribution.md](../doc/viewer-distribution.md)).
