from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

FONT = '맑은 고딕'

def set_font(run, size=None, bold=None, color=None, italic=None):
    run.font.name = FONT
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn('w:rFonts'))
    if rfonts is None:
        rfonts = OxmlElement('w:rFonts'); rpr.append(rfonts)
    for a in ('w:ascii', 'w:hAnsi', 'w:eastAsia', 'w:cs'):
        rfonts.set(qn(a), FONT)
    if size: run.font.size = Pt(size)
    if bold is not None: run.font.bold = bold
    if italic is not None: run.font.italic = italic
    if color: run.font.color.rgb = RGBColor(*color)

def shade(cell, fill):
    tcpr = cell._element.get_or_add_tcPr()
    shd = OxmlElement('w:shd'); shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), fill)
    tcpr.append(shd)

def cell_margins(table, top=50, bottom=50, left=90, right=90):
    tblpr = table._element.tblPr
    m = OxmlElement('w:tblCellMar')
    for k, v in (('top', top), ('left', left), ('bottom', bottom), ('right', right)):
        e = OxmlElement(f'w:{k}'); e.set(qn('w:w'), str(v)); e.set(qn('w:type'), 'dxa'); m.append(e)
    tblpr.append(m)

def add_runs(p, text, size=10, color=None, base_bold=False):
    """**bold** and [[placeholder]] markup."""
    import re
    for part in re.split(r'(\*\*.+?\*\*|\[\[.+?\]\])', text):
        if not part: continue
        if part.startswith('**'):
            r = p.add_run(part[2:-2]); set_font(r, size, True, color)
        elif part.startswith('[['):
            r = p.add_run('[' + part[2:-2] + ']'); set_font(r, size, True, color)
            r.font.highlight_color = WD_COLOR_INDEX.YELLOW
        else:
            r = p.add_run(part); set_font(r, size, base_bold, color)

class Report:
    def __init__(self, header_text):
        self.d = Document()
        sec = self.d.sections[0]
        sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
        sec.left_margin = sec.right_margin = Cm(2.0); sec.top_margin = Cm(2.2); sec.bottom_margin = Cm(2.0)
        st = self.d.styles['Normal']; st.font.name = FONT; st.font.size = Pt(10)
        st.element.rPr.rFonts.set(qn('w:eastAsia'), FONT)
        st.paragraph_format.space_after = Pt(4); st.paragraph_format.line_spacing = 1.25
        for name, size, color, before in (('Heading 1', 16, (31, 56, 100), 14), ('Heading 2', 12.5, (46, 84, 150), 10), ('Heading 3', 11, (60, 60, 60), 8)):
            h = self.d.styles[name]; h.font.name = FONT; h.font.size = Pt(size); h.font.bold = True
            h.font.color.rgb = RGBColor(*color); h.element.rPr.rFonts.set(qn('w:eastAsia'), FONT)
            h.element.rPr.rFonts.set(qn('w:ascii'), FONT); h.element.rPr.rFonts.set(qn('w:hAnsi'), FONT)
            h.paragraph_format.space_before = Pt(before); h.paragraph_format.space_after = Pt(4)
            h.paragraph_format.keep_with_next = True
        hp = sec.header.paragraphs[0]; hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        add_runs(hp, header_text, 9, (90, 90, 90))
        fp = sec.footer.paragraphs[0]; fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = fp.add_run(); set_font(r, 9, color=(90, 90, 90))
        for t, txt in (('begin', None), (None, 'PAGE'), ('end', None)):
            if t:
                e = OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'), t); r._element.append(e)
            else:
                e = OxmlElement('w:instrText'); e.set(qn('xml:space'), 'preserve'); e.text = txt; r._element.append(e)
        self.fig = 0; self.tab = 0

    def h(self, text, level=1):
        p = self.d.add_heading(level=level)
        r = p.add_run(text); set_font(r, None, True)
        return p

    def p(self, text, size=10, align=None, after=None, color=None, bold=False):
        para = self.d.add_paragraph(); add_runs(para, text, size, color, bold)
        if align: para.alignment = align
        if after is not None: para.paragraph_format.space_after = Pt(after)
        return para

    def bullets(self, items, size=10):
        for it in items:
            para = self.d.add_paragraph(style='List Bullet'); add_runs(para, it, size)
            para.paragraph_format.space_after = Pt(2)

    def table(self, rows, widths, header=True, size=9, fills=None, caption=None, align_center_from=None):
        if caption:
            self.tab += 1
            cp = self.d.add_paragraph(); cp.paragraph_format.keep_with_next = True; cp.paragraph_format.space_after = Pt(2)
            add_runs(cp, f'표 {self.tab}. {caption}', 9, (60, 60, 60), True)
        t = self.d.add_table(rows=len(rows), cols=len(rows[0])); t.style = 'Table Grid'
        t.alignment = WD_TABLE_ALIGNMENT.CENTER; t.autofit = False; cell_margins(t)
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                c = t.cell(i, j); c.width = Cm(widths[j])
                para = c.paragraphs[0]; para.paragraph_format.space_after = Pt(0); para.paragraph_format.line_spacing = 1.1
                add_runs(para, str(val), size, None, header and i == 0)
                if align_center_from is not None and j >= align_center_from: para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                if header and i == 0:
                    shade(c, 'D9E2F3'); para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    para.paragraph_format.keep_with_next = True   # header row never sits alone at a page bottom
                elif fills and (i, j) in fills: shade(c, fills[(i, j)])
        for ri, row in enumerate(t.rows):
            trpr = row._tr.get_or_add_trPr()
            cs = OxmlElement('w:cantSplit'); trpr.append(cs)
            if header and ri == 0:
                th = OxmlElement('w:tblHeader'); trpr.append(th)
        self.d.add_paragraph().paragraph_format.space_after = Pt(2)
        return t

    def callout(self, text, fill='FFF4DE', size=9.5):
        t = self.d.add_table(rows=1, cols=1); t.style = 'Table Grid'; t.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell_margins(t, 90, 90, 140, 140)
        c = t.cell(0, 0); c.width = Cm(17); shade(c, fill)
        lines = text.split('\n')
        add_runs(c.paragraphs[0], lines[0], size)
        for ln in lines[1:]:
            pp = c.add_paragraph(); add_runs(pp, ln, size); pp.paragraph_format.space_after = Pt(0)
        c.paragraphs[0].paragraph_format.space_after = Pt(2)
        self.d.add_paragraph().paragraph_format.space_after = Pt(2)

    def image(self, path, width_cm, caption):
        para = self.d.add_paragraph(); para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.keep_with_next = True; para.paragraph_format.space_after = Pt(2)
        para.add_run().add_picture(str(path), width=Cm(width_cm))
        self.fig += 1
        cp = self.d.add_paragraph(); cp.alignment = WD_ALIGN_PARAGRAPH.CENTER; cp.paragraph_format.space_after = Pt(8)
        add_runs(cp, f'그림 {self.fig}. {caption}', 9, (60, 60, 60))

    def page_break(self):
        self.d.add_page_break()

    def save(self, path):
        self.d.save(str(path))
