"""Turn docs/solution_doc.md into docs/Solution_Doc.pdf (A4, must stay within 2 pages).

    pip install reportlab pypdf        # once
    python3 docs/make_solution_doc.py

Edit solution_doc.md (plain text: # title, ## headings, - bullets, 1. steps, | tables |, **bold**, `code`), then re-run.
Text in [FILL IN ...] is highlighted yellow so it can't be missed.
"""
import os, re, sys
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

HERE = os.path.dirname(os.path.abspath(__file__))
SRC, OUT = os.path.join(HERE, "solution_doc.md"), os.path.join(HERE, "Solution_Doc.pdf")
INK, ACCENT, LINE, HEAD = colors.HexColor("#1f2328"), colors.HexColor("#1a5fb4"), colors.HexColor("#d0d7de"), colors.HexColor("#f3f6fa")
base = dict(fontName="Helvetica", fontSize=9.8, leading=13.4, textColor=INK)
ST = {"title": ParagraphStyle("t", **{**base, "fontName": "Helvetica-Bold", "fontSize": 15.5, "leading": 19, "spaceAfter": 4}),
      "h": ParagraphStyle("h", **{**base, "fontName": "Helvetica-Bold", "fontSize": 11.5, "leading": 14.5, "textColor": ACCENT,
                                  "spaceBefore": 7, "spaceAfter": 3}),
      "p": ParagraphStyle("p", **{**base, "spaceAfter": 3}),
      "li": ParagraphStyle("li", **{**base, "leftIndent": 11, "bulletIndent": 1, "spaceAfter": 1.2}),
      "cell": ParagraphStyle("c", **{**base, "fontSize": 9.2, "leading": 11.6})}
W = A4[0] - 2 * 15 * mm


def inline(text):
    """**bold**, `code`, [FILL IN] highlight; escape the rest."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`(.+?)`", r'<font face="Courier">\1</font>', text)
    return re.sub(r"(\[FILL IN[^\]]*\])", r'<font backColor="#fff3a3"><b>\1</b></font>', text)


def table(rows):
    cells = [[r.strip() for r in row.strip().strip("|").split("|")] for row in rows if not re.match(r"^\|\s*-", row)]
    n = len(cells[0])
    widths = [0.52, 0.16, 0.16, 0.16] if n == 4 else [0.60, 0.20, 0.20] if n == 3 else [1 / n] * n
    data = [[Paragraph(("<b>%s</b>" if i == 0 else "%s") % inline(c), ST["cell"]) for c in row] for i, row in enumerate(cells)]
    t = Table(data, colWidths=[w * W for w in widths], repeatRows=1)   # header repeats if a table splits
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, LINE), ("BACKGROUND", (0, 0), (-1, 0), HEAD),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("LEFTPADDING", (0, 0), (-1, -1), 4)]))
    return [t, Spacer(1, 3)]


def build():
    story, lines, i = [], open(SRC, encoding="utf-8").read().splitlines(), 0
    while i < len(lines):
        l = lines[i]
        if l.startswith("# "): story.append(Paragraph(inline(l[2:]), ST["title"]))
        elif l.startswith("## "): story.append(Paragraph(inline(l[3:]), ST["h"]))
        elif l.startswith("|"):
            block = []
            while i < len(lines) and lines[i].startswith("|"): block.append(lines[i]); i += 1
            story += table(block); continue
        elif re.match(r"^- ", l): story.append(Paragraph(inline(l[2:]), ST["li"], bulletText="•"))
        elif re.match(r"^\d+\. ", l):
            num, rest = l.split(". ", 1)
            story.append(Paragraph(inline(rest), ST["li"], bulletText=f"{num}."))
        elif l.strip(): story.append(Paragraph(inline(l), ST["p"]))
        i += 1
    doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
                            title="Promo Finder - Solution Doc")
    doc.build(story)
    from pypdf import PdfReader
    pages = len(PdfReader(OUT).pages)
    print(f"wrote {OUT}: {pages} page(s)" + ("" if pages <= 2 else "  <-- TOO LONG: the brief allows 2 pages, shorten the text"))
    return pages


if __name__ == "__main__":
    sys.exit(0 if build() <= 2 else 1)
