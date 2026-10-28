"""Inline site/ into ONE html file (dist/promise-tracker.html) that opens by double-click on any device."""
from __future__ import annotations

from common import ROOT, SITE, log


def run() -> dict:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    css = (SITE / "style.css").read_text(encoding="utf-8")
    js = {n: (SITE / n).read_text(encoding="utf-8").replace("</", "<\\/") for n in ("data.js", "app.js")}
    html = html.replace('<link rel="stylesheet" href="style.css">', f"<style>\n{css}</style>")
    for name, body in js.items():
        html = html.replace(f'<script src="{name}"></script>', f"<script>\n{body}</script>")
    out = ROOT / "dist" / "promise-tracker.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    log(f"bundle: wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")
    return {"bytes": out.stat().st_size}


if __name__ == "__main__":
    run()
