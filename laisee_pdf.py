import csv
import os
import struct
from datetime import date

import olefile
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

'''
Turn the output of laisee.py (e.g. csv/laisee_out.csv) into a printable pdf
of QR code labels that lines up with an Avery label sheet.

The sheet geometry (page size, margins, label size and spacing) is read from
the Avery Word template, e.g. pdf/Avery_07670.doc (24 labels of 1.5" x 1.5").

Each label shows:   title (top), QR code of the lnurl (middle),
                    id (rotated, left), expiration date (rotated, right),
                    empty space at the bottom for the sender to write the amount

Tip: print one page on plain paper first and hold it against a label sheet.
If everything is shifted, adjust OFFSET_X / OFFSET_Y below.
'''

##################################
# default variables
template = "pdf/Avery_07670.doc"
infile = "laisee_out.csv"
outfile = "laisee_labels.pdf"

# shift the whole page to compensate for printer misalignment (in points, 72pt = 1 inch)
OFFSET_X = 0
OFFSET_Y = 0
# draw the label outlines, handy for a test print on plain paper
DRAW_OUTLINES = False

# font used for CJK characters in the title, must be a .ttf.
# Characters the font doesn't have (e.g. latin letters) are written in Helvetica.
# If none of these exist, a built-in (non embedded) Traditional Chinese font is used.
CJK_FONTS = ["/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
             "/usr/share/fonts/truetype/arphic/uming.ttc",
             "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
             "C:/Windows/Fonts/msjh.ttc",
             "C:/Windows/Fonts/mingliu.ttc"]

# positions inside a label, in points, measured from the label's top left corner.
# These are designed for a 108pt (1.5") square label and scale with the label size.
QR_SIZE = 72            # QR code incl. its 1 module white border
QR_TOP = 18
TITLE_BASELINE = 13.5
TITLE_SIZE = 10
ID_CENTER_X = 16        # id runs top to bottom along the left edge of the QR code
ID_SIZE = 4
EXP_CENTER_X = 92.5     # expiration runs bottom to top along the right edge
EXP_SIZE = 6
DESIGN_SIZE = 108


def twips(value):
    return value / 20.0     # 1 twip = 1/20 pt


def read_template(path):
    '''
    Read the label grid from a Word 97-2003 (.doc) Avery template.
    Avery templates are a single table: label rows separated by thin spacer rows,
    label columns separated by thin spacer columns.

    Returns page width/height and a list of label rectangles (x, y, w, h) in points,
    with y measured from the top of the page, ordered left to right, top to bottom.
    '''
    ole = olefile.OleFileIO(path)
    wd = ole.openstream("WordDocument").read()
    ole.close()

    def sprm(code, fmt):
        i = wd.find(struct.pack("<H", code))
        if i < 0:
            raise ValueError(f"{path}: page setting {code:#06x} not found")
        return struct.unpack_from(fmt, wd, i + 2)[0]

    page_w = sprm(0xB01F, "<H")   # sprmSXaPage
    page_h = sprm(0xB020, "<H")   # sprmSYaPage
    left = sprm(0xB021, "<H")     # sprmSDxaLeft
    top = sprm(0x9023, "<h")      # sprmSDyaTop

    # every table row stores its height (sprmTDyaRowHeight) followed by
    # its cell boundaries (sprmTDefTable), all in twips
    rows = []
    i = wd.find(b"\x07\x94")
    while i >= 0:
        if wd[i + 4:i + 6] == b"\x08\xd6":
            height = abs(struct.unpack_from("<h", wd, i + 2)[0])
            ncells = wd[i + 8]
            edges = struct.unpack_from(f"<{ncells + 1}h", wd, i + 9)
            rows.append((height, edges))
        i = wd.find(b"\x07\x94", i + 2)
    if not rows:
        raise ValueError(f"{path}: no label table found")

    label_h = max(h for h, _ in rows)
    labels = []
    y = top
    for height, edges in rows:
        if height == label_h:
            cells = list(zip(edges, edges[1:]))
            label_w = max(b - a for a, b in cells)
            for a, b in cells:
                if b - a == label_w:
                    labels.append(tuple(twips(v) for v in (left + a, y, label_w, label_h)))
        y += height
    page_w, page_h = twips(page_w), twips(page_h)
    return page_w, page_h, labels


def register_title_font():
    for path in CJK_FONTS:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("Title", path))
                return "Title"
            except Exception:
                continue    # e.g. a .ttc with outlines reportlab can't read
    print("No CJK .ttf font found, using built-in MSung-Light (not embedded in the pdf)")
    pdfmetrics.registerFont(UnicodeCIDFont("MSung-Light"))
    return "MSung-Light"


def font_runs(text, font):
    '''split text into (font, text) runs, using Helvetica for characters font lacks'''
    face = pdfmetrics.getFont(font).face
    glyphs = getattr(face, "charToGlyph", None)     # None for the built-in CID font
    runs = []
    for ch in text:
        f = font if glyphs is None or ord(ch) in glyphs else "Helvetica"
        if runs and runs[-1][0] == f:
            runs[-1][1] += ch
        else:
            runs.append([f, ch])
    return runs


def runs_width(runs, size):
    return sum(pdfmetrics.stringWidth(t, f, size) for f, t in runs)


def draw_centred_runs(c, cx, y, runs, size):
    x = cx - runs_width(runs, size) / 2
    for f, t in runs:
        c.setFont(f, size)
        c.drawString(x, y, t)
        x += pdfmetrics.stringWidth(t, f, size)


def fit(runs, size, max_width):
    '''shrink the font size until the text fits'''
    while size > 3 and runs_width(runs, size) > max_width:
        size -= 0.5
    return size


def draw_label(c, row, expiration, label, page_h, title_font):
    x, y, w, h = label
    s = min(w, h) / DESIGN_SIZE
    # reportlab measures y from the bottom of the page
    left = x + OFFSET_X
    bottom = page_h - y - h - OFFSET_Y
    cx = left + w / 2

    def from_top(v):
        return bottom + h - v * s

    if DRAW_OUTLINES:
        c.setLineWidth(0.25)
        c.rect(left, bottom, w, h)

    runs = font_runs(row["title"], title_font)
    size = fit(runs, TITLE_SIZE * s, w - 8 * s)
    draw_centred_runs(c, cx, from_top(TITLE_BASELINE), runs, size)

    # upper case lnurl + scheme lets the QR use alphanumeric mode -> fewer, bigger modules
    qr = QrCodeWidget(("lightning:" + row["lnurl"]).upper(), barLevel="M", barBorder=1)
    qr_size = QR_SIZE * s
    qr.barWidth = qr.barHeight = qr_size
    d = Drawing(qr_size, qr_size)
    d.add(qr)
    renderPDF.draw(d, c, cx - qr_size / 2, from_top(QR_TOP) - qr_size)
    qr_mid = from_top(QR_TOP + QR_SIZE / 2)

    # id, reading top to bottom
    c.saveState()
    c.translate(left + ID_CENTER_X * s, qr_mid)
    c.rotate(-90)
    c.setFont("Helvetica", ID_SIZE * s)
    c.drawCentredString(0, -ID_SIZE * s * 0.35, row["id"])
    c.restoreState()

    # expiration, reading bottom to top
    c.saveState()
    c.translate(left + EXP_CENTER_X * s, qr_mid)
    c.rotate(90)
    c.setFont("Times-Roman", EXP_SIZE * s)
    c.drawCentredString(0, -EXP_SIZE * s * 0.35, f"Expiration: {expiration}")
    c.restoreState()


def write_pdf(filename, rows, expiration, template):
    page_w, page_h, labels = read_template(template)
    print(f"Template {template}: {len(labels)} labels per page")
    title_font = register_title_font()

    c = canvas.Canvas('pdf/' + filename, pagesize=(page_w, page_h))
    c.setTitle("Laisee labels")
    for n, row in enumerate(rows):
        if n and n % len(labels) == 0:
            c.showPage()
        draw_label(c, row, expiration, labels[n % len(labels)], page_h, title_font)
    c.save()
    pages = -(-len(rows) // len(labels))
    print(f"Wrote {len(rows)} labels on {pages} page(s)")


def read_csv(filename):
    with open('csv/' + filename, mode='r', newline='') as csv_file:
        return list(csv.DictReader(csv_file))


def ask(question, default):
    answer = input(f"{question} [{default}]: ").strip()
    return answer or default


def ask_expiration():
    while True:
        answer = input('Please enter the expiration date (YYYY-MM-DD): ').strip()
        try:
            return date.fromisoformat(answer).isoformat()
        except ValueError:
            print("\t That is not a valid date, try again.")


if __name__ == "__main__":

    print('Hi - This is the Laisee label printer.')
    expiration = ask_expiration()
    infile = ask('Enter your laisee .csv file name (in csv/)', infile)
    template = ask('Enter your Avery .doc template', template)
    outfile = ask('Enter your output .pdf file name (in pdf/)', outfile)

    print("Okay, Processing.........")
    rows = read_csv(infile)
    write_pdf(outfile, rows, expiration, template)
    print(f" >>>>>>>>> Finished writing out to pdf/{outfile}\n\n")
