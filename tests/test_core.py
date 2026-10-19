import pymupdf
import pytest

from pdf_editor import core
from pdf_editor.cli import main


def make_pdf(path, lines_per_page, rotation=0):
    doc = pymupdf.open()
    for lines in lines_per_page:
        page = doc.new_page()
        for i, (text, kwargs) in enumerate(lines):
            page.insert_text((72, 100 + i * 13), text, **kwargs)
        page.set_rotation(rotation)
    doc.save(path)
    return path


@pytest.fixture
def sample(tmp_path):
    return make_pdf(tmp_path / "exemple.pdf", [
        [("Bonjour Jean-Pierre Dupont", {"fontsize": 12}),
         ("Montant : 100 euros", {"fontsize": 12, "fontname": "hebo", "color": (1, 0, 0)})],
        [("Page deux, Dupont encore", {"fontsize": 10, "fontname": "tiro"})],
    ])


def page_text(doc, number):
    return doc[number].get_text()


def test_add_text_top_left_and_accents(sample):
    doc = core.open_pdf(sample)
    core.add_text(doc, 0, 200, 300, "Été à Noël\nDeuxième ligne", fontsize=14, color=(0, 0, 1))
    spans = [s for s in core.get_text_spans(doc, 0) if s.text == "Été à Noël"]
    assert len(spans) == 1
    assert spans[0].bbox[0] == pytest.approx(200, abs=0.5)
    assert spans[0].bbox[1] == pytest.approx(300, abs=0.5)
    assert spans[0].color == pytest.approx((0, 0, 1))
    assert "Deuxième ligne" in page_text(doc, 0)


def test_replace_text_keeps_neighbours_and_style(sample):
    doc = core.open_pdf(sample)
    assert core.replace_text(doc, "Jean", "Marie") == 1
    text = page_text(doc, 0)
    assert "Jean" not in text
    assert "Marie" in text and "-Pierre Dupont" in text and "Bonjour" in text
    # La ligne juste en dessous (interligne serré) n'est pas touchée.
    assert "Montant : 100 euros" in text

    assert core.replace_text(doc, "100", "250") == 1
    span = next(s for s in core.get_text_spans(doc, 0) if "250" in s.text)
    assert span.color == pytest.approx((1, 0, 0))
    assert span.fontname == "hebo"
    assert span.fontsize == pytest.approx(12)


def test_replace_text_whole_document_and_single_page(sample):
    doc = core.open_pdf(sample)
    assert core.replace_text(doc, "Dupont", "Martin", page_number=1) == 1
    assert "Dupont" in page_text(doc, 0)
    assert "Martin" in page_text(doc, 1)
    assert core.replace_text(doc, "Dupont", "Durand") == 1
    assert core.replace_text(doc, "introuvable", "x") == 0


def test_replace_with_empty_text_deletes(sample):
    doc = core.open_pdf(sample)
    core.replace_text(doc, " Dupont", "", page_number=0)
    assert "Dupont" not in page_text(doc, 0)
    assert "Jean-Pierre" in page_text(doc, 0)


def test_edit_span(sample):
    doc = core.open_pdf(sample)
    span = core.span_at(doc, 0, 80, 96)
    assert span is not None and span.text == "Bonjour Jean-Pierre Dupont"
    core.edit_span(doc, span, "Bonsoir tout le monde")
    assert "Bonsoir tout le monde" in page_text(doc, 0)
    assert "Bonjour" not in page_text(doc, 0)
    assert core.span_at(doc, 0, 500, 700) is None


def test_rotated_page(tmp_path):
    path = make_pdf(tmp_path / "rot.pdf", [[("Texte original", {"rotate": 90})]], rotation=90)
    doc = core.open_pdf(path)
    page = doc[0]
    core.add_text(doc, 0, 50, 60, "Ajout")
    assert core.replace_text(doc, "original", "modifié") == 1
    for block in page.get_text("dict")["blocks"]:
        for line in block["lines"]:
            visual = pymupdf.Point(line["dir"]) * page.rotation_matrix - pymupdf.Point(0, 0) * page.rotation_matrix
            assert tuple(visual) == pytest.approx((1, 0)), line["spans"][0]["text"]
    added = next(s for s in core.get_text_spans(doc, 0) if s.text == "Ajout")
    assert added.bbox[:2] == pytest.approx((50, 60), abs=0.5)
    text = page.get_text()
    assert "original" not in text and "Texte" in text and "modifié" in text
    replaced = next(s for s in core.get_text_spans(doc, 0) if "modifié" in s.text)
    texte = next(s for s in core.get_text_spans(doc, 0) if s.text.startswith("Texte"))
    assert replaced.bbox[1] == pytest.approx(texte.bbox[1], abs=0.5)  # même ligne affichée


def test_drawn_signature_fits_rect(sample):
    doc = core.open_pdf(sample)
    strokes = [[(0, 50), (40, 0), (80, 50)], [(100, 25)]]
    core.add_drawn_signature(doc, 0, strokes, (300, 600, 500, 680))
    drawings = doc[0].get_drawings()
    assert drawings
    bounds = drawings[0]["rect"]
    for d in drawings[1:]:
        bounds |= d["rect"]
    assert pymupdf.Rect(299, 599, 501, 681).contains(bounds)


def test_drawn_signature_empty(sample):
    with pytest.raises(ValueError):
        core.add_drawn_signature(core.open_pdf(sample), 0, [], (0, 0, 10, 10))


def test_signature_image(sample, tmp_path):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 20), False)
    pix.set_rect(pix.irect, (20, 20, 120))
    image = tmp_path / "sig.png"
    pix.save(image)

    doc = core.open_pdf(sample)
    core.add_signature_image(doc, 0, (300, 600, 500, 700), image)
    core.add_signature_image(doc, 1, (300, 600, 500, 700), image.read_bytes())
    (info,) = doc[0].get_image_info()
    assert pymupdf.Rect(300, 600, 500, 700).contains(pymupdf.Rect(info["bbox"]))


def test_merge(sample, tmp_path):
    other = make_pdf(tmp_path / "autre.pdf", [[("Annexe", {})]])
    out = tmp_path / "fusion.pdf"
    merged = core.merge_pdfs([sample, other, sample], out)
    assert merged.page_count == 5
    with pymupdf.open(out) as doc:
        assert doc.page_count == 5
        assert "Annexe" in doc[2].get_text()


def test_parse_color():
    assert core.parse_color("#ff0000") == (1, 0, 0)
    with pytest.raises(ValueError):
        core.parse_color("rouge")


def test_cli(sample, tmp_path, capsys):
    out = tmp_path / "out.pdf"
    assert main(["remplacer", str(sample), str(out), "--ancien", "Dupont", "--nouveau", "Durand"]) == 0
    assert "2 remplacement(s)" in capsys.readouterr().out
    # Écraser le fichier source est autorisé.
    assert main(["texte", str(out), str(out), "--x", "72", "--y", "200",
                 "--texte", "Lu et approuvé", "--couleur", "#0000ff"]) == 0
    with pymupdf.open(out) as doc:
        assert "Durand" in doc[0].get_text() and "Lu et approuvé" in doc[0].get_text()

    assert main(["fusionner", str(tmp_path / "f.pdf"), str(sample), str(out)]) == 0
    assert main(["texte", str(sample), str(out), "--page", "9", "--x", "0", "--y", "0", "--texte", "x"]) == 1
    assert "n'existe pas" in capsys.readouterr().err
