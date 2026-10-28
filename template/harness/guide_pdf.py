"""Print an HTML user guide to PDF with Chromium. Run by harness/guide.py in the e2e container:

    python harness/guide_pdf.py <guide.html> <out.pdf>
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

FOOTER = ('<div style="width:100%;font-size:8px;color:#888;text-align:center;">'
          '<span class="pageNumber"></span> / <span class="totalPages"></span></div>')


def main(html, pdf):
    pdf = Path(pdf)
    pdf.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(Path(html).resolve().as_uri(), wait_until="load")
        page.pdf(path=str(pdf), format="A4", print_background=True,
                 display_header_footer=True, header_template="<div></div>",
                 footer_template=FOOTER,
                 margin={"top": "15mm", "bottom": "18mm", "left": "14mm", "right": "14mm"})
        browser.close()
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: guide_pdf.py <guide.html> <out.pdf>")
    sys.exit(main(*sys.argv[1:]))
