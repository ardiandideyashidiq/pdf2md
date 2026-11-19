"""pdf2md — batch-convert PDFs to clean Markdown with pymupdf4llm-rs."""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from loguru import logger
from pymupdf4llm_rs import PdfExtractor

TABLE_STRATEGIES = ("lines_strict", "lines", "text", "explicit")

LOG_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
)
FILE_LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | {name}:{function} - {message}"
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf2md",
        description="Convert PDF files or directories of PDFs to clean Markdown.",
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="one or more PDF files and/or directories",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="output file (single input) or directory (default: alongside source)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="write markdown to stdout; requires exactly one input file",
    )
    parser.add_argument(
        "--pattern",
        default="*.pdf",
        help="glob used for directory inputs (default: *.pdf)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing .md files (default: skip them)",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop at the first conversion error",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="also write logs to this file (rotating, 10 MB, 7 days)",
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v", "--verbose", action="store_true", help="show DEBUG logs"
    )
    verbosity.add_argument(
        "-q", "--quiet", action="store_true", help="only show warnings and the summary"
    )
    parser.add_argument(
        "--table-strategy",
        choices=TABLE_STRATEGIES,
        default="lines_strict",
        help="table detection strategy (default: lines_strict)",
    )
    parser.add_argument(
        "--keep-running-headers",
        action="store_true",
        help="keep repeated headers/footers instead of deduplicating them",
    )
    parser.add_argument(
        "--page-separators",
        action="store_true",
        help="insert separators between pages",
    )
    parser.add_argument(
        "--pages",
        default=None,
        help="comma-separated 1-based page numbers, e.g. 1,3-5",
    )
    parser.add_argument(
        "--max-pdf-bytes",
        type=int,
        default=134217728,
        help="reject PDFs larger than this (default: 128 MiB)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="reject PDFs with more pages than this",
    )
    return parser


def _setup_logging(verbose: bool, quiet: bool, log_file: Path | None) -> None:
    logger.remove()
    level = "DEBUG" if verbose else "WARNING" if quiet else "INFO"
    logger.add(sys.stderr, level=level, format=LOG_FORMAT, colorize=None)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_file,
            level="DEBUG",
            format=FILE_LOG_FORMAT,
            rotation="10 MB",
            retention="7 days",
            compression="zip",
            diagnose=False,
            enqueue=True,
        )


def _collect_pdfs(inputs: Sequence[Path], pattern: str) -> list[tuple[Path, Path]]:
    """Return (pdf, relative parent dir) pairs, de-duplicated and sorted."""
    collected: list[tuple[Path, Path]] = []
    seen: set[Path] = set()
    for source in inputs:
        if source.is_file():
            candidates = [(source, Path())]
        else:
            candidates = [
                (path, path.parent.relative_to(source))
                for path in source.rglob(pattern)
                if path.is_file()
            ]
        for pdf, relative in candidates:
            if pdf.suffix.lower() != ".pdf":
                continue
            key = pdf.resolve()
            if key in seen:
                continue
            seen.add(key)
            collected.append((pdf, relative))
    return sorted(collected, key=lambda item: str(item[0]).lower())


def _parse_pages(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            pages.update(range(int(start), int(end) + 1))
        elif part:
            pages.add(int(part))
    return sorted(pages)


def _write_stdout(markdown: str) -> bool:
    """Write to stdout; return False if the reader closed the pipe early."""
    try:
        sys.stdout.write(markdown)
        if not markdown.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
    except BrokenPipeError:
        # Avoid a second BrokenPipeError when Python flushes stdout at exit.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return False
    return True


def _resolve_targets(
    collected: Sequence[tuple[Path, Path]],
    output: Path | None,
    stdout: bool,
) -> list[tuple[Path, Path | None]]:
    """Resolve each source to an output path; None means write to stdout."""
    if stdout:
        if len(collected) != 1 or not collected[0][0].is_file():
            raise ValueError("--stdout requires exactly one input file")
        return [(collected[0][0], None)]

    if output is None:
        return [(pdf, pdf.with_suffix(".md")) for pdf, _ in collected]

    looks_like_file = output.suffix.lower() == ".md" and not str(output).endswith("/")
    if output.exists() and output.is_dir():
        looks_like_file = False

    if len(collected) == 1 and looks_like_file:
        return [(collected[0][0], output)]

    if looks_like_file:
        raise ValueError("-o must be a directory when converting multiple PDFs")

    output.mkdir(parents=True, exist_ok=True)
    return [(pdf, output / relative / f"{pdf.stem}.md") for pdf, relative in collected]


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _setup_logging(args.verbose, args.quiet, args.log_file)

    missing = [path for path in args.inputs if not path.exists()]
    if missing:
        for path in missing:
            logger.error("No such path: {path}", path=path)
        return 2

    collected = _collect_pdfs(args.inputs, args.pattern)
    if not collected:
        logger.error(
            "No PDFs found in: {paths}", paths=", ".join(map(str, args.inputs))
        )
        return 2

    try:
        targets = _resolve_targets(collected, args.output, args.stdout)
    except ValueError as exc:
        logger.error("{error}", error=exc)
        return 2

    options: dict[str, object] = {
        "table_strategy": args.table_strategy,
        "dedup_running_headers": not args.keep_running_headers,
        "page_separators": args.page_separators,
        "clean_mojibake": True,
        "dehyphenate": True,
        "dedup_faux_bold": True,
        "ignore_invisible_text": True,
        "strip_watermarks": True,
        "max_pdf_bytes": args.max_pdf_bytes,
        "max_pages": args.max_pages,
        "pages": _parse_pages(args.pages),
    }
    # One extractor for the whole batch: thread pools, caches and engines are reused.
    extractor = PdfExtractor(**options)

    total_start = time.perf_counter()
    timings: list[float] = []
    total_chars = 0
    skipped = 0
    failed = 0

    for (pdf, relative), (_, target) in zip(collected, targets):
        log = logger.bind(file=pdf.name)
        if target is not None and target.exists() and not args.force:
            log.info("Skipped (exists): {path}", path=target)
            skipped += 1
            continue

        started = time.perf_counter()
        try:
            markdown = extractor.to_markdown(str(pdf))
            if target is None:
                if not _write_stdout(markdown):
                    timings.append(time.perf_counter() - started)
                    total_chars += len(markdown)
                    break
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(markdown, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - keep converting other files
            failed += 1
            log.error("Failed: {error}", error=f"{type(exc).__name__}: {exc}")
            if args.fail_fast:
                break
            continue

        elapsed = time.perf_counter() - started
        timings.append(elapsed)
        total_chars += len(markdown)
        if target is not None:
            log.success(
                "{path} - {chars:,} chars in {elapsed:.3f}s",
                path=target.name,
                chars=len(markdown),
                elapsed=elapsed,
            )

    total_elapsed = time.perf_counter() - total_start
    logger.complete()  # flush the optional file sink

    if timings:
        logger.info(
            "Converted {converted}/{total} PDFs in {elapsed:.3f}s "
            "({chars:,} chars; avg {avg:.3f}s, min {fastest:.3f}s, "
            "max {slowest:.3f}s per file; {rate:,.0f} chars/s); "
            "{skipped} skipped, {failed} failed",
            converted=len(timings),
            total=len(collected),
            elapsed=total_elapsed,
            chars=total_chars,
            avg=sum(timings) / len(timings),
            fastest=min(timings),
            slowest=max(timings),
            rate=total_chars / total_elapsed,
            skipped=skipped,
            failed=failed,
        )
    else:
        logger.warning(
            "No PDFs converted in {elapsed:.3f}s ({skipped} skipped, {failed} failed)",
            elapsed=total_elapsed,
            skipped=skipped,
            failed=failed,
        )

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
