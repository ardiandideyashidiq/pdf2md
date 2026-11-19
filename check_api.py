"""Smoke-check the pymupdf4llm-rs Python API under a uv-managed environment."""

from __future__ import annotations

import json

import pymupdf4llm_rs as pm
from pymupdf4llm_rs import LlamaMarkdownReader, PdfExtractor


def build_synthetic_pdf() -> bytes:
    """Build a minimal single-page PDF with visible + invisible text and a watermark."""
    stream = (
        b"BT\n"
        b"/F2 20 Tf 72 720 Td (1. Python Rust Hybrid Architecture) Tj\n"
        b"/F1 11 Tf 0 -28 Td (Standard body paragraph with ) Tj\n"
        b"/F2 11 Tf (reusable engine) Tj\n"
        b"/F1 11 Tf ( and CJK hygiene support.) Tj\n"
        b"/F1 11 Tf 3 Tr 1 0 0 1 72 670 Tm (INVISIBLE_OCR_NOISE) Tj\n"
        b"/F1 36 Tf 0.707 0.707 -0.707 0.707 200 400 Tm (DRAFT) Tj\n"
        b"ET\n"
    )
    objs = [
        "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>\nendobj\n",
        "4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        "5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\nendobj\n",
        f"6 0 obj\n<< /Length {len(stream)} >>\nstream\n"
        f"{stream.decode('latin1')}endstream\nendobj\n",
    ]
    buf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for obj in objs:
        offsets.append(len(buf))
        buf.extend(obj.encode("latin1"))
    xref = len(buf)
    buf.extend(b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n")
    for off in offsets:
        buf.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    buf.extend(
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(buf)


def main() -> None:
    pdf = build_synthetic_pdf()
    print(f"version: {pm.__version__}")
    print(f"exports: {', '.join(pm.__all__)}")

    # 1. Top-level convenience functions
    md = pm.to_markdown_bytes(pdf)
    assert "Python Rust Hybrid Architecture" in md
    assert "**reusable engine**" in md
    assert "INVISIBLE_OCR_NOISE" not in md, "invisible text was not stripped"
    assert "DRAFT" not in md, "watermark was not stripped"
    print("[ok] to_markdown_bytes (+ hygiene: invisible text & watermark stripped)")

    # 2. PdfExtractor reuse + with_options
    ex = PdfExtractor(table_strategy="lines_strict", ignore_invisible_text=True, strip_watermarks=True)
    assert ex.options["table_strategy"] == "lines_strict"
    derived = ex.with_options(table_strategy="text", ignore_code=True)
    assert derived.options["table_strategy"] == "text"
    assert ex.options["table_strategy"] == "lines_strict", "with_options mutated original"
    print("[ok] PdfExtractor reuse / with_options isolation")

    # 3. ParsedPdf parse-once handle (context manager)
    with ex.open_bytes(pdf) as doc:
        assert doc.page_count == 1
        assert doc.metadata()["page_count"] == 1
        chunks = doc.to_chunks(extract_words=True)
        assert len(chunks) == 1
        assert len(chunks[0]["words"]) > 0
        assert "Python Rust Hybrid Architecture" in doc.to_text()
        assert json.loads(ex.to_json(pdf))[0]["metadata"]["page_count"] == 1
    print("[ok] ParsedPdf parse-once handle (metadata/to_chunks/to_text/to_json)")

    # 4. LlamaMarkdownReader (LlamaIndex-style)
    reader = LlamaMarkdownReader(ex)
    docs = reader.load_data(pdf, extra_info={"source": "check"})
    assert len(docs) == 1
    assert docs[0]["metadata"]["source"] == "check"
    print("[ok] LlamaMarkdownReader.load_data")

    # 5. Safety limits / validation
    try:
        PdfExtractor(max_pdf_bytes=64).to_markdown_bytes(pdf)
        raise AssertionError("max_pdf_bytes guard did not trigger")
    except ValueError as e:
        assert "max_pdf_bytes" in str(e)
    try:
        PdfExtractor(unknown_option_flag=True)
        raise AssertionError("unknown option did not trigger")
    except ValueError as e:
        assert "Unknown option" in str(e)
    print("[ok] safety limits & option validation")

    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
