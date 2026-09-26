# Differences from general-purpose tools

*[日本語版 (Japanese version)](diff-ja.md)*

The underlying "text → PDF" stack is not unique to text-compositor. [Quarto](https://quarto.org/docs/output-formats/typst.html) is a general-purpose publishing system that can target Typst as a backend, and since v1.9 its book projects can also compose multiple `.qmd` files into a single PDF. Several lightweight single-file CLIs, such as [md2pdf](https://github.com/cipherchabon/md2pdf), also exist.

So text-compositor's reason to exist isn't "a technical capability nothing else has." It's that **it embeds, as operating rules built into the tool itself, the specific workflow of taking fragmentary text contributed by multiple writers — human or AI — and safely turning it into a reviewed, production-ready document.** The sections below spell out the concrete differences.

## Difference from Typst itself

Before comparing against Quarto, it's worth answering a more basic question first: "why not just use the Typst compiler directly?"

The answer is that the two operate at different layers, so they aren't really comparable. Typst is a typesetting engine: it converts files written in Typst syntax into a PDF. text-compositor is a tool that depends on Typst; it doesn't replace it. text-compositor's only interaction with Typst is calling the Typst compiler (`typst.compile()`) from `compiler.py` — Typst itself does the actual PDF generation (spec chapter 3).

The two differ in role in three ways.

* **Input format**: the person writing the source (AI included) writes in plain text such as Markdown, never Typst syntax directly. text-compositor turns it into an AST via `markdown-it-py` and deterministically converts that into Typst syntax (chapter 1). Using Typst directly means writing the source itself in Typst syntax.
* **Composing multiple files**: the `config.yaml`-driven mechanism that assembles independent text files (`chapters`) into one PDF — including per-chapter paper settings and headers/footers — doesn't exist in Typst itself. You could write your own with Typst's `#include`, but that amounts to writing a one-off build system in Typst each time, and it doesn't give you the "separation between the tool and the document" described in chapter 3.
* **Withholding layout authority from the writer**: this is the most fundamental difference. Typst is, at heart, a programmable layout language — anyone who can write Typst syntax directly can also control layout on the spot. Letting the writer (AI or human) write raw Typst syntax means handing them layout decisions as well. text-compositor accepts only Markdown by design, precisely so that layout decisions stay fixed on the template side (a `.typ` file that a human writes and reviews; chapter 1).

An analogy: this is close to Sphinx's or Pandoc's relationship to LaTeX. Just as "what's the difference between Pandoc and LaTeX" isn't a question that comes up much, text-compositor isn't a Typst replacement — it's a tool that uses Typst as its conversion target.

## Comparison table

| Aspect | General-purpose tools (Quarto, etc.) | text-compositor |
| --- | --- | --- |
| Controlling execution of unreviewed code | Generally none — code inside Markdown (code cells, etc.) is typically passed straight to an execution engine | `typst-exec` is allowlist-based. Raw Typst code is only permitted in files under `reviewed/`; everything else errors immediately (spec chapters 7–8). This embeds, in the tool itself, the operating rule that unreviewed expressive power contributed by a writer (AI or human) never mixes into production output |
| Detecting unintended HTML | Usually rendered as-is, silently | AST analysis flags any HTML tag with a line-numbered warning (spec chapter 9) — a design that never silently swallows HTML that slips into Markdown by accident |
| File access boundary | The whole project directory is generally trusted | `--root` is strictly confined to the project directory. Even if `typst-exec` calls `read()`, it's sandboxed against reading unintended files (spec chapters 5, 8) |
| Separation of tool and document | Often assumes tool config/extensions live inside the project directory | Fully separated via a single `--config`. The tool itself is never modified, and it can build a document living anywhere (spec chapter 3) |
| Attitude toward reproducibility | Version pinning is left to the user | Typst itself, plugins, and fonts are all pinned by SHA256/version (spec chapter 9) — strongly guarantees "same input, same output" |
| Unit of file splitting | Splitting by chapter/section is common | Granularity of "one file = one independent fragment." A single AI conversation turn or a single chapter of an existing document can become a file boundary as-is, regardless of origin (spec chapter 1) |
| Codebase size | Large and general-purpose (many output formats, extension mechanisms, executable cells, etc.) | The implementation lives under `text_compositor/` (the top-level `build.py` is a thin wrapper that calls into it, [#111](https://github.com/tokudiro/text-compositor/issues/111)). `build.py` alone once grew to about 2,300 lines, but [#157](https://github.com/tokudiro/text-compositor/issues/157) split it into modules by responsibility (`config.py`, `renderer.py`, `chapters.py`, `compiler.py`, etc., with one-directional, non-circular dependencies). Kept small enough to read and modify as a whole |

## Download volume on GitHub Actions

Previously (before #34/#35), Mermaid support was implemented via `mmdc` (`@mermaid-js/mermaid-cli`) run through `npx`, which meant text-compositor actually downloaded *more* than Quarto when Mermaid was in use — the opposite of the intended positioning. With #34 (detecting and reusing the system browser) and #35 (replacing the whole `mermaid-cli` package with a single bundled JS file driven directly over CDP via Playwright) now implemented, that's reversed, as shown below.

| | Download volume | Breakdown |
| --- | --- | --- |
| Quarto (no Mermaid, book composition with Typst backend) | ~140MB | A single [Quarto CLI tarball](https://github.com/quarto-dev/quarto-cli/releases/). Pandoc, Deno, and [even Typst are bundled in](https://quarto.org/docs/output-formats/typst.html), so nothing extra is downloaded |
| Quarto (with Mermaid) | **~254MB** | The 140MB above + the linux64 [Chrome Headless Shell](https://quarto.org/docs/blog/posts/2026-04-14-chrome-headless-shell.html) needed to turn Mermaid diagrams into PDF. Measured directly from [Google's official distribution](https://storage.googleapis.com/chrome-for-testing-public/152.0.7977.42/linux64/chrome-headless-shell-linux64.zip): **119,483,791 bytes (~114MB, compressed zip)** |
| text-compositor (no Mermaid) | ~60.5MB | pip: `typst` (32.6MB) + `markdown-it-py` (0.08MB) + `mdit-py-plugins` (0.05MB) + `PyYAML` (0.73MB) ≈ 33.5MB / Noto Sans JP: downloads a 27MB ZIP but only uses 2 files from it |
| text-compositor (with Mermaid) | **~109MB** | The 60.5MB above + the `playwright` package (PyPI, manylinux1_x86_64 wheel, measured at **~45.5MB**) + `mermaid.min.js` (measured at 3.4MB). The browser itself is detected and reused via `find_system_browser()` (#34) against the Chrome preinstalled on `ubuntu-latest`, so nothing extra is downloaded for it (chapter 11, implemented in #35) |
| text-compositor (with PlantUML) | ~78MB | The 60.5MB above + `plantuml-mit-*.jar` (measured at ~17.6MB). Java is detected and reused via `find_system_java()` against the version preinstalled on `ubuntu-latest`, so no extra Eclipse Temurin JRE download happens on CI (chapter 11, implemented in #22). Quarto has no standard equivalent here, so there's nothing to compare against |
| Marp CLI (`npx @marp-team/marp-cli`) | ~123MB + browser | Renders HTML/CSS to PDF via a headless browser (Puppeteer-core). The package itself is ~123MB; Chromium is needed on top |
| Vivliostyle CLI (`npx @vivliostyle/cli`) | ~242MB + browser | Also Puppeteer-core based, like Marp. Its dependency tree is larger still, reflecting its full CSS-typesetting feature set |

Including Mermaid, text-compositor (~109MB) comes in at well under half of Quarto (~254MB). Without Mermaid, the gap widens further (60.5MB vs. 140MB). This gap could be narrowed further by eliminating the waste in the Noto Sans font ZIP (downloading 27MB to use only 9.2MB of it) — that remains a future improvement.

Figures are either the on-disk size after extraction, or the compressed file size read directly from HTTP headers (see each row for which method was used). For both tools, caching mechanisms on GitHub Actions (e.g. `actions/cache`) can substantially reduce the cost of runs after the first.

## Diagram rendering support (Mermaid / Graphviz / PlantUML / D2)

Looking at this concretely, text-compositor has little edge over Quarto for Mermaid/Graphviz. PlantUML and D2 are a different story.

| Tool | Mermaid | Graphviz (dot) | PlantUML | D2 |
| --- | --- | --- | --- | --- |
| text-compositor | Implemented (direct CDP control via Playwright, #35) | Implemented (`diagraph`) | Implemented (local Java + Smetana, #22) | Implemented (official D2 CLI binary, #90) |
| [Quarto](https://quarto.org/docs/authoring/diagrams.html) | **Native, built in**, no extra setup | **Native, built in** — usable immediately via a `{dot}` cell ([reference](https://medium.com/codex/quarto-1-4-adds-mermaid-and-graphviz-604de76fca21)) | Not supported out of the box. Requires a third-party pandoc filter or a manual Java + PlantUML jar setup ([reference](https://github.com/orgs/quarto-dev/discussions/6549)) | Not supported out of the box (not documented officially) |
| Marp CLI | Not built in — you have to wire something like `markdown-it-mermaid` into `engine.js` yourself ([reference](https://github.com/orgs/marp-team/discussions/207)) | Not built in ([feature request open](https://github.com/orgs/marp-team/discussions/219), unimplemented) | Not built in | Not built in |
| Vivliostyle CLI | Not built in — requires manually wiring something like `rehype-mermaid` in via its processor-replacement extension point ([reference](https://zenn.dev/mura_mi/articles/4f08cc99f19887)) | No information found; presumably manual as well | No information found; presumably manual as well | No information found; presumably manual as well |

Quarto has Mermaid and Graphviz natively from the start, with zero extra configuration needed. text-compositor's own diagram integration (direct Playwright/CDP control, `diagraph`) now comes out ahead on download volume, but it doesn't match Quarto's "ready to use with zero config" convenience. On the other hand, Quarto has no standard support for PlantUML or D2, while text-compositor only needs `plugins.plantuml: true` / `plugins.d2: true` (auto-fetching the Eclipse Temurin JRE or the official D2 CLI binary respectively when no local runtime is present) — a clear point of differentiation.

## Conclusion

On "how easy diagram rendering is to turn on," we couldn't find a clear edge for text-compositor over Quarto for Mermaid/Graphviz. But since Quarto has no standard support for PlantUML or D2, while text-compositor only needs `plugins.plantuml: true` (#22) / `plugins.d2: true` (#90), that remains a clear differentiator. On download volume, the #34/#35 work means text-compositor now comes in at under half of Quarto's, even including Mermaid.

That said, the items in the comparison table above — the `typst-exec` allowlist, fail-fast on stray HTML, the `--root` sandbox, full separation of tool and document — are operating rules that general-purpose tools including Quarto don't provide by default: **rules for safely turning text contributed by multiple writers (human or AI) into production output after review.** That remains the core of why text-compositor exists. Being lightweight is a welcome side effect it happens to have achieved, not the main argument — the case for this tool should keep resting on that governance angle.
