#!/usr/bin/env python3
"""Generate a one-page PDF summary of marcle.ai from repo evidence."""

from __future__ import annotations

from pathlib import Path


PAGE_WIDTH = 612
PAGE_HEIGHT = 792
LEFT = 54
RIGHT = 558
TOP = 744
LINE = 14


def wrap_text(text: str, max_chars: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_block(lines: list[tuple[str, int, float, float]]) -> str:
    out: list[str] = ["BT", "/F1 11 Tf", "0 g"]
    for text, size, x, y in lines:
        out.append(f"/F1 {size} Tf")
        out.append(f"1 0 0 1 {x:.1f} {y:.1f} Tm ({pdf_escape(text)}) Tj")
    out.append("ET")
    return "\n".join(out) + "\n"


def build_lines() -> list[tuple[str, int, float, float]]:
    y = TOP
    lines: list[tuple[str, int, float, float]] = []

    def add_heading(text: str) -> None:
        nonlocal y
        lines.append((text, 15, LEFT, y))
        y -= LINE + 3

    def add_subheading(text: str) -> None:
        nonlocal y
        lines.append((text, 12, LEFT, y))
        y -= LINE

    def add_wrapped(text: str, indent: float = 0, max_chars: int = 95) -> None:
        nonlocal y
        for ln in wrap_text(text, max_chars):
            lines.append((ln, 10, LEFT + indent, y))
            y -= LINE

    def add_bullets(items: list[str]) -> None:
        nonlocal y
        for item in items:
            wrapped = wrap_text(item, 90)
            lines.append((f"- {wrapped[0]}", 10, LEFT + 4, y))
            y -= LINE
            for cont in wrapped[1:]:
                lines.append((cont, 10, LEFT + 16, y))
                y -= LINE

    add_heading("marcle.ai - One-Page App Summary")
    add_wrapped("Evidence source: README.md, docker-compose.yml, frontend/*, backend/app/*", max_chars=100)
    y -= 4

    add_subheading("What it is")
    add_wrapped(
        "A self-hosted web app that combines a public homelab status dashboard with an authenticated Q&A app "
        "at /ask. It serves static frontend pages through nginx and proxies API traffic to a FastAPI backend."
    )
    y -= 2

    add_subheading("Who it's for")
    add_bullets(
        [
            "Primary persona: a self-hosting homelab operator (owner/operator context appears throughout README "
            "and frontend copy).",
            "Secondary users: authenticated Ask users who submit questions and receive email answers.",
        ]
    )
    y -= 2

    add_subheading("What it does")
    add_bullets(
        [
            "Publishes service health states (healthy, degraded, down, unknown) via /api/status and a live dashboard.",
            "Tracks incidents and exposes overview/service detail APIs with cache age, last incident, and history.",
            "Runs concurrent background checks on configured services with check-type profiles and auth references.",
            "Provides admin APIs/UI to create/update/toggle services, bulk enable/disable, and view audit logs.",
            "Supports configurable outbound notifications with endpoint filters and test dispatch.",
            "Implements Google OAuth login for Ask, per-user points, and rate-limited question submission.",
            "Posts Ask questions to Discord webhook and accepts secure answer webhooks that email users.",
        ]
    )
    y -= 2

    add_subheading("How it works (architecture)")
    add_bullets(
        [
            "Frontend container (nginx): serves /, /admin, /ask static pages; proxies /api/* and /healthz to backend:8000.",
            "Backend container (FastAPI): status + admin endpoints in app.main, Ask routes in app.routers.ask.",
            "Data layer: JSON files for services, observations, notifications, and audit log under /data; SQLite for Ask DB.",
            "Flow: browser polls status/overview -> backend serves cached payload from refresh loop -> observations update.",
            "Ask flow: Google OAuth callback -> session cookie + SQLite user record -> question insert and points decrement "
            "-> Discord webhook -> answer webhook -> email send.",
            "Dedicated distributed session store/queue worker: Not found in repo (sessions and rate limits are in-memory).",
        ]
    )
    y -= 2

    add_subheading("How to run (minimal)")
    add_bullets(
        [
            "Copy env template: cp .env.example .env",
            "Set required values in .env (at minimum ADMIN_TOKEN to enable admin; Ask vars for OAuth/Discord/SMTP if used).",
            "Start containers: docker compose up --build",
            "Open: http://localhost:9182 (status), /ask (Ask app), /admin (admin panel).",
        ]
    )

    if y < 40:
        raise RuntimeError("Content overflowed the one-page layout.")
    return lines


def generate_pdf(output_path: Path) -> None:
    lines = build_lines()
    stream = text_block(lines).encode("latin-1", errors="replace")

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
        f"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>".encode("ascii")
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"endstream")

    pdf = bytearray()
    pdf.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    xref_positions: list[int] = [0]

    for i, obj in enumerate(objects, start=1):
        xref_positions.append(len(pdf))
        pdf.extend(f"{i} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_start = len(pdf)
    pdf.extend(f"xref\n0 {len(xref_positions)}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in xref_positions[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(xref_positions)} /Root 1 0 R >>\n"
            f"startxref\n{xref_start}\n%%EOF\n"
        ).encode("ascii")
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(pdf)


if __name__ == "__main__":
    generate_pdf(Path("output/pdf/marcle-ai-one-page-summary.pdf"))
