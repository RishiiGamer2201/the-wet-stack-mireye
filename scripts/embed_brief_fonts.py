"""Inline the webfonts as data URIs for the local PDF render.

Chrome's --print-to-fdf run fetched Google Fonts too late, so the first PDF
shipped in Georgia and Arial with only the monospace embedded. For a document
that gets read as a PDF, the typography is the whole impression, so the fonts
are downloaded once and inlined into the copy that is rendered. The published
artifact keeps the ordinary stylesheet link.

Only the Latin subset of each weight actually used is inlined, which keeps the
PDF near its current size rather than ballooning it.
"""

import base64
import pathlib
import re

import httpx

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
}
# The v1 API serves *static* instances. css2 returns variable fonts, and Chrome
# rasterises a variable instance into a Type3 font when printing, which renders
# but is not properly searchable or selectable in the resulting PDF.
CSS_URL = (
    "https://fonts.googleapis.com/css"
    "?family=Chivo:400,700"
    "|IBM+Plex+Mono:400,500,600"
    "|Source+Serif+Pro:400,600,400italic"
    "&display=swap"
)
SCRATCH = pathlib.Path(
    "C:/Users/admin/AppData/Local/Temp/claude/c--developer-hackathons-mireye/"
    "30302c78-86db-472c-b9a2-3013a381147b/scratchpad"
)
OUT = SCRATCH / "fonts-inline.css"


def main() -> None:
    css = httpx.get(CSS_URL, headers=UA, timeout=60).text

    # Google serves one @font-face per unicode subset. Latin is all this
    # document needs; the rest would triple the file for characters it has none of.
    blocks = re.findall(r"/\*\s*([\w\-\[\]]+)\s*\*/\s*(@font-face\s*\{[^}]+\})", css)
    kept = [block for subset, block in blocks if subset in ("latin", "latin-ext")]

    cache: dict[str, str] = {}
    out_blocks = []
    for block in kept:
        match = re.search(r"url\((https://[^)]+\.woff2)\)", block)
        if not match:
            continue
        url = match.group(1)
        if url not in cache:
            data = httpx.get(url, headers=UA, timeout=60).content
            cache[url] = base64.b64encode(data).decode()
        block = block.replace(url, f"data:font/woff2;base64,{cache[url]}")
        out_blocks.append(block)

    OUT.write_text("\n".join(out_blocks), encoding="utf-8")
    print(f"{len(out_blocks)} faces inlined, {len(cache)} files, {OUT.stat().st_size / 1024:.0f} kB")


if __name__ == "__main__":
    main()
