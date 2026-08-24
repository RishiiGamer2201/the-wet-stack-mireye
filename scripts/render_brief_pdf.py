"""Render docs/submission-technical-brief.html to a two-page A4 PDF.

Uses the Chromium that Playwright already cached, driven through its own
--print-to-pdf flag, so no new dependency is needed to produce the file.
"""

import pathlib
import re
import subprocess
import sys

CHROME = pathlib.Path(
    r"C:/Users/admin/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe"
)
SRC = pathlib.Path("docs/submission-technical-brief.html")
SCRATCH = pathlib.Path(
    "C:/Users/admin/AppData/Local/Temp/claude/c--developer-hackathons-mireye/"
    "30302c78-86db-472c-b9a2-3013a381147b/scratchpad"
)
STANDALONE = SCRATCH / "brief-standalone.html"
OUT = pathlib.Path("docs/The-Wet-Stack-Mireye-Technical-Brief.pdf")


INLINE_FONTS = SCRATCH / "fonts-inline.css"


def build_standalone() -> None:
    """The artifact host supplies <html>/<head>/<body>; a local render needs them.

    The Google Fonts <link> is swapped for inlined faces, because the headless
    render finished before the network fetch did and the first PDF shipped in
    Georgia and Arial with only the monospace embedded.
    """
    fragment = SRC.read_text(encoding="utf-8")
    marker = '<div class="sheet">'
    head, body = fragment.split(marker, 1)

    head = re.sub(
        r'<link rel="(?:preconnect|stylesheet)"[^>]*fonts\.(?:googleapis|gstatic)\.com[^>]*>\s*',
        "",
        head,
    )
    # The static v1 API serves "Source Serif Pro"; the page's stack asks for
    # "Source Serif 4". Same typeface, so alias the inlined faces rather than
    # change the page, which keeps the published artifact on its own stack.
    faces = INLINE_FONTS.read_text(encoding="utf-8").replace(
        "'Source Serif Pro'", "'Source Serif 4'"
    )
    head = head.replace("<style>", "<style>\n" + faces + "\n", 1)

    STANDALONE.write_text(
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{head}</head>\n<body>\n{marker}{body}\n</body>\n</html>\n",
        encoding="utf-8",
    )


def render() -> None:
    subprocess.run(
        [
            str(CHROME),
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            f"--print-to-pdf={OUT.resolve()}",
            # Google Fonts are fetched over the network; give them time to land
            # or the PDF silently ships in the fallback stack.
            "--virtual-time-budget=10000",
            STANDALONE.resolve().as_uri(),
        ],
        check=True,
        capture_output=True,
    )


def report() -> int:
    import pymupdf

    with pymupdf.open(OUT) as doc:
        pages = doc.page_count
        fonts = {f[3] for page in doc for f in page.get_fonts()}
        print(f"{OUT}  {OUT.stat().st_size / 1024:.0f} kB  {pages} page(s)")
        for i, page in enumerate(doc, 1):
            mm = (page.rect.width / 72 * 25.4, page.rect.height / 72 * 25.4)
            print(f"   page {i}: {mm[0]:.0f} x {mm[1]:.0f} mm, {len(page.get_text().split())} words")
        embedded = sorted(n for n in fonts if any(k in n for k in ("Archivo", "Plex", "Source")))
        print("   fonts:", ", ".join(embedded) or "FALLBACK ONLY - webfonts did not load")
    return pages


if __name__ == "__main__":
    build_standalone()
    render()
    sys.exit(0 if report() == 2 else 1)
