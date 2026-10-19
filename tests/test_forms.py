import pymupdf
import pytest

from pdf_editor import core

# PDF écrit à la main, structuré comme ceux produits par Acrobat ou
# LibreOffice : une case à cocher, un groupe de deux boutons radio, une zone
# de texte, ainsi qu'un carré simplement dessiné dans la page.
FORM_PDF = b"""%PDF-1.7
1 0 obj <</Type/Catalog/Pages 2 0 R/AcroForm <</Fields[4 0 R 5 0 R 8 0 R]/DA(/Helv 0 Tf 0 g)>> >> endobj
2 0 obj <</Type/Pages/Kids[3 0 R]/Count 1>> endobj
3 0 obj <</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 20 0 R/Annots[4 0 R 6 0 R 7 0 R 8 0 R]>> endobj
4 0 obj <</Type/Annot/Subtype/Widget/FT/Btn/T(accepte)/Rect[72 742 86 756]/V/Off/AS/Off/AP<</N<</Oui 10 0 R/Off 11 0 R>> >>/P 3 0 R>> endobj
5 0 obj <</FT/Btn/Ff 49152/T(civilite)/V/Off/Kids[6 0 R 7 0 R]>> endobj
6 0 obj <</Type/Annot/Subtype/Widget/Parent 5 0 R/Rect[72 712 86 726]/AS/Off/AP<</N<</Mme 10 0 R/Off 11 0 R>> >>/P 3 0 R>> endobj
7 0 obj <</Type/Annot/Subtype/Widget/Parent 5 0 R/Rect[120 712 134 726]/AS/Off/AP<</N<</M 10 0 R/Off 11 0 R>> >>/P 3 0 R>> endobj
8 0 obj <</Type/Annot/Subtype/Widget/FT/Tx/T(nom)/Rect[72 670 300 690]/V()/DA(/Helv 10 Tf 0 g)/P 3 0 R>> endobj
10 0 obj <</Type/XObject/Subtype/Form/BBox[0 0 14 14]/Length 21>> stream
0 0 0 rg 3 3 8 8 re f
endstream endobj
11 0 obj <</Type/XObject/Subtype/Form/BBox[0 0 14 14]/Length 0>> stream

endstream endobj
20 0 obj <</Length 54>> stream
0 0 0 RG 1 w 300 730 12 12 re S 72 600 m 400 600 l S
endstream endobj
trailer <</Root 1 0 R>>
%%EOF
"""


@pytest.fixture
def form(tmp_path):
    path = tmp_path / "formulaire.pdf"
    path.write_bytes(FORM_PDF)
    return core.open_pdf(path)


def fields_by_name(doc):
    return {(f.name, f.bbox[0]): f for f in core.get_form_fields(doc, 0)}


def reopen(doc):
    return pymupdf.open(stream=doc.tobytes(garbage=3), filetype="pdf")


def test_list_fields(form):
    fields = core.get_form_fields(form, 0)
    assert [(f.name, f.kind, f.value) for f in fields] == [
        ("accepte", "case", False),
        ("civilite", "radio", False),
        ("civilite", "radio", False),
        ("nom", "texte", ""),
    ]
    # Coordonnées affichées (origine en haut à gauche).
    assert fields[0].bbox == pytest.approx((72, 86, 86, 100))
    assert core.field_at(fields, 79, 93) == fields[0]
    assert core.field_at(fields, 5, 5) is None


def test_toggle_checkbox(form):
    case = fields_by_name(form)[("accepte", 72)]
    core.toggle_field(form, case)
    doc = reopen(form)
    case = fields_by_name(doc)[("accepte", 72)]
    assert case.value is True
    assert doc.xref_get_key(case.xref, "V") == ("name", "/Oui")
    core.toggle_field(doc, case)
    assert fields_by_name(doc)[("accepte", 72)].value is False


def test_radio_group_is_exclusive(form):
    core.toggle_field(form, fields_by_name(form)[("civilite", 72)])
    fields = fields_by_name(form)
    assert fields[("civilite", 72)].value and not fields[("civilite", 120)].value

    core.toggle_field(form, fields[("civilite", 120)])
    doc = reopen(form)
    fields = fields_by_name(doc)
    assert not fields[("civilite", 72)].value and fields[("civilite", 120)].value
    assert doc.xref_get_key(5, "V") == ("name", "/M")


def test_fill_text_field(form):
    core.set_field(form, fields_by_name(form)[("nom", 72)], "Hélène Dupré")
    doc = reopen(form)
    assert fields_by_name(doc)[("nom", 72)].value == "Hélène Dupré"


def test_read_only_field(form):
    field = fields_by_name(form)[("accepte", 72)]
    locked = core.FormField(**{**field.__dict__, "read_only": True})
    with pytest.raises(ValueError):
        core.toggle_field(form, locked)


def test_printed_box_detection(form):
    boxes = core.find_boxes(form, 0)
    assert boxes == [pytest.approx((300, 100, 312, 112))]  # la ligne n'est pas une case
    assert core.box_at(boxes, 306, 106) == boxes[0]
    assert core.box_at(boxes, 313, 113) == boxes[0]  # petite marge de tolérance
    assert core.box_at(boxes, 350, 106) is None


def test_glyph_box_detection(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    font = pymupdf.Font("cjk")  # police intégrée contenant le caractère □
    page.insert_font(fontname="F0", fontbuffer=font.buffer)
    page.insert_text((72, 100), "□ Oui", fontname="F0", fontsize=12)
    (box,) = core.find_boxes(doc, 0)
    assert box[3] == pytest.approx(100, abs=0.5)
    assert box[0] == pytest.approx(72, abs=1)


def test_toggle_check_mark(form):
    box = core.find_boxes(form, 0)[0]
    assert core.toggle_check_mark(form, 0, box) is True
    page = form[0]  # garder la page en vie tant que ses annotations sont utilisées
    (annot,) = page.annots(types=[pymupdf.PDF_ANNOT_INK])
    assert pymupdf.Rect(box).intersects(annot.rect)
    assert annot.flags & pymupdf.PDF_ANNOT_IS_PRINT

    doc = reopen(form)
    assert core.toggle_check_mark(doc, 0, box) is False
    page = doc[0]
    assert not list(page.annots(types=[pymupdf.PDF_ANNOT_INK]))


def test_check_mark_on_rotated_page():
    doc = pymupdf.open()
    page = doc.new_page()
    page.set_rotation(90)
    core.toggle_check_mark(doc, 0, (100, 200, 120, 220))
    (annot,) = page.annots()
    visual = annot.rect * page.rotation_matrix
    assert pymupdf.Rect(90, 190, 130, 230).contains(visual)
    assert core.toggle_check_mark(doc, 0, (100, 200, 120, 220)) is False
