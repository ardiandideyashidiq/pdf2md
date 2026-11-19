# pdf2md

Batch-convert PDFs to clean Markdown using [pymupdf4llm-rs](https://github.com/0passion0/pymupdf4llm-rs), with Loguru logging and per-file timing.

Requires Python >= 3.15 and [uv](https://docs.astral.sh/uv/).

Install as a standalone tool from GitHub (then run `pdf2md` directly):

```bash
uv tool install git+https://github.com/ardiandideyashidiq/pdf2md.git
pdf2md --help
```

For local development, use `uv sync` and prefix commands with `uv run`:

```bash
uv sync
uv run pdf2md INPUT... [OPTIONS]
```

`INPUT...` accepts one or more PDF files and/or directories. Directories are searched **recursively** by default, and their relative sub-directory structure is mirrored into the output.

## Behavior

| Case | Result |
| --- | --- |
| `pdf2md paper.pdf` | `paper.md` beside the source |
| `pdf2md paper.pdf -o final.md` | exact output file |
| `pdf2md ./papers -o ./md` | `.md` per PDF in `./md`, sub-directories preserved |
| `pdf2md a.pdf b.pdf -o ./md` | batch into a directory |
| `pdf2md paper.pdf --stdout` | Markdown to stdout, logs to stderr |

Existing `.md` files are **skipped** by default; use `--force` to overwrite. Failures are logged and skipped (use `--fail-fast` to stop). Exit codes: `0` success, `1` conversion failure, `2` usage error.

## Options

| Flag | Description |
| --- | --- |
| `-o, --output PATH` | output file (single input) or directory |
| `--stdout` | write Markdown to stdout (one input file only) |
| `--pattern GLOB` | directory glob (default `*.pdf`) |
| `--force` | overwrite existing `.md` |
| `--fail-fast` | stop at first error |
| `--log-file PATH` | rotating log file (10 MB, 7 days) |
| `-v` / `-q` | DEBUG / WARNING console logs (default INFO) |
| `--table-strategy` | `lines_strict` (default), `lines`, `text`, `explicit` |
| `--pages 1,3-5` | restrict to specific pages |
| `--keep-running-headers`, `--page-separators` | tune Markdown output |
| `--max-pdf-bytes`, `--max-pages` | input safety limits |

## Examples

```bash
uv run pdf2md ./papers -o ./md --force
uv run pdf2md paper.pdf --stdout > paper.md
uv run pdf2md ./papers --pattern 'laporan*.pdf' -v --log-file convert.log
```

Development: `uv run ruff check src` and `uv run ruff format --check src`.
