#!/usr/bin/env python3
"""Build SUBMISSION.pdf from SUBMISSION.md with the screenshots embedded as base64.

Usage:  .venv/bin/python docs/build_pdf.py
Renders a self-contained HTML (images inlined so nothing can go missing), then prints it
to PDF with headless Google Chrome.
"""
import base64, mimetypes, os, re, subprocess, sys
import markdown

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD = os.path.join(ROOT, "SUBMISSION.md")
HTML = os.path.join(ROOT, "docs", "SUBMISSION.html")
PDF = os.path.join(ROOT, "SUBMISSION.pdf")

CSS = """
@page { size: A4; margin: 16mm 15mm; }
* { box-sizing: border-box; }
body { font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
       font-size: 10.5pt; line-height: 1.5; color: #1a1a1a; max-width: 100%; }
h1 { font-size: 20pt; margin: 0 0 2pt; color: #11131a; }
h2 { font-size: 13pt; margin: 18pt 0 6pt; padding-top: 6pt; border-top: 1px solid #e3e3e8; color: #11131a; }
h3 { font-size: 11pt; margin: 12pt 0 4pt; color: #11131a; }
p, li { margin: 4pt 0; }
code { background: #f3f3f6; padding: 1px 4px; border-radius: 3px; font-size: 9.5pt;
       font-family: 'SF Mono', 'Consolas', monospace; }
pre { background: #f6f6f9; border: 1px solid #e3e3e8; border-radius: 6px; padding: 9pt 11pt;
      overflow-x: auto; font-size: 9pt; line-height: 1.45; }
pre code { background: none; padding: 0; }
blockquote { margin: 8pt 0; padding: 6pt 12pt; border-left: 3px solid #c9c9d2; background: #fafafb;
             color: #444; font-size: 9.8pt; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 9.6pt; }
th, td { border: 1px solid #dcdce2; padding: 5pt 8pt; text-align: left; vertical-align: top; }
th { background: #f3f3f6; font-weight: 600; }
img { max-width: 100%; height: auto; border: 1px solid #dcdce2; border-radius: 6px;
      margin: 6pt 0; display: block; page-break-inside: avoid; }
h2, h3 { page-break-after: avoid; }
hr { border: none; border-top: 1px solid #e3e3e8; margin: 14pt 0; }
a { color: #2b4cff; text-decoration: none; }
strong { color: #11131a; }
"""


def inline_images(html):
    def repl(m):
        src = m.group(1)
        path = src if os.path.isabs(src) else os.path.join(ROOT, src)
        if not os.path.exists(path):
            print(f"  warning: image not found: {path}", file=sys.stderr)
            return m.group(0)
        mime = mimetypes.guess_type(path)[0] or "image/png"
        data = base64.b64encode(open(path, "rb").read()).decode()
        return f'src="data:{mime};base64,{data}"'
    return re.sub(r'src="([^"]+)"', repl, html)


def main():
    body = markdown.markdown(open(MD, encoding="utf-8").read(),
                             extensions=["tables", "fenced_code", "sane_lists"])
    body = inline_images(body)
    doc = f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"
    open(HTML, "w", encoding="utf-8").write(doc)
    print(f"wrote {HTML}")

    for exe in ("google-chrome", "chromium-browser", "chromium", "google-chrome-stable"):
        if subprocess.run(["which", exe], capture_output=True).returncode == 0:
            cmd = [exe, "--headless=new", "--no-sandbox", "--disable-gpu",
                   "--no-pdf-header-footer", f"--print-to-pdf={PDF}", "file://" + HTML]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if os.path.exists(PDF):
                print(f"wrote {PDF} ({os.path.getsize(PDF) // 1024} KB) using {exe}")
                return
            print(r.stderr[-800:], file=sys.stderr)
            # older Chrome: retry without =new
            cmd[1] = "--headless"
            subprocess.run(cmd, capture_output=True, text=True)
            if os.path.exists(PDF):
                print(f"wrote {PDF} ({os.path.getsize(PDF) // 1024} KB) using {exe}")
                return
    sys.exit("Could not produce the PDF (no working Chrome/Chromium found).")


if __name__ == "__main__":
    main()
