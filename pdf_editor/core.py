"""Fonctions d'édition de PDF, basées sur PyMuPDF.

Conventions :
- les numéros de page commencent à 0 ;
- les coordonnées sont en points (1/72 de pouce), origine en haut à gauche
  de la page *telle qu'elle est affichée* (la rotation de la page est prise
  en compte) ;
- les couleurs sont des triplets (r, g, b) avec des valeurs entre 0 et 1.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import pymupdf

Color = tuple[float, float, float]
Point = tuple[float, float]
Stroke = Sequence[Point]

BLACK: Color = (0.0, 0.0, 0.0)
SIGNATURE_BLUE: Color = (0.05, 0.1, 0.45)

# Flags de police renvoyés par PyMuPDF dans get_text("dict").
_FLAG_ITALIC = 2
_FLAG_SERIF = 4
_FLAG_MONO = 8
_FLAG_BOLD = 16


# --------------------------------------------------------------------------
# Ouverture / enregistrement
# --------------------------------------------------------------------------

def open_pdf(path: str | Path) -> pymupdf.Document:
    """Ouvre un PDF en mémoire, ce qui permet ensuite d'écraser le fichier."""
    return pymupdf.open(stream=Path(path).read_bytes(), filetype="pdf")


def save_pdf(doc: pymupdf.Document, path: str | Path) -> None:
    doc.save(str(path), garbage=3, deflate=True)


def parse_color(value: str) -> Color:
    """Convertit une couleur "#RRGGBB" en triplet (r, g, b)."""
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Couleur invalide : #{value} (format attendu : #RRGGBB)")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


# --------------------------------------------------------------------------
# Ajout de texte
# --------------------------------------------------------------------------

def add_text(
    doc: pymupdf.Document,
    page_number: int,
    x: float,
    y: float,
    text: str,
    fontsize: float = 12,
    color: Color = BLACK,
    fontname: str = "helv",
) -> None:
    """Ajoute du texte (éventuellement sur plusieurs lignes) dont le coin
    supérieur gauche est en (x, y)."""
    page = doc[page_number]
    baseline = pymupdf.Point(x, y + pymupdf.Font(fontname).ascender * fontsize)
    page.insert_text(
        baseline * page.derotation_matrix,
        text,
        fontsize=fontsize,
        fontname=fontname,
        color=color,
        rotate=page.rotation,
    )


# --------------------------------------------------------------------------
# Signature
# --------------------------------------------------------------------------

def add_signature_image(
    doc: pymupdf.Document,
    page_number: int,
    rect: Sequence[float],
    image: str | Path | bytes,
) -> None:
    """Place une image de signature (PNG, JPEG…) dans le rectangle donné,
    en conservant ses proportions."""
    page = doc[page_number]
    source = {"stream": image} if isinstance(image, bytes) else {"filename": str(image)}
    page.insert_image(
        _rect_to_page(page, rect),
        keep_proportion=True,
        rotate=page.rotation,
        **source,
    )


def add_drawn_signature(
    doc: pymupdf.Document,
    page_number: int,
    strokes: Iterable[Stroke],
    rect: Sequence[float],
    color: Color = SIGNATURE_BLUE,
    width: float = 1.5,
) -> None:
    """Dessine une signature manuscrite (liste de traits, chacun étant une
    liste de points) mise à l'échelle pour tenir dans le rectangle donné.

    Les coordonnées des traits sont libres (par exemple des pixels d'une
    zone de dessin) : seule leur forme compte.
    """
    strokes = [list(s) for s in strokes if len(s) > 0]
    points = [p for s in strokes for p in s]
    if not points:
        raise ValueError("La signature est vide.")

    min_x = min(p[0] for p in points)
    min_y = min(p[1] for p in points)
    span_x = max(p[0] for p in points) - min_x
    span_y = max(p[1] for p in points) - min_y

    target = pymupdf.Rect(rect)
    avail_w = max(target.width - 2 * width, 1)
    avail_h = max(target.height - 2 * width, 1)
    scales = [s for s in (avail_w / span_x if span_x else None,
                          avail_h / span_y if span_y else None) if s]
    scale = min(scales) if scales else 1.0
    off_x = target.x0 + (target.width - span_x * scale) / 2
    off_y = target.y0 + (target.height - span_y * scale) / 2

    page = doc[page_number]
    to_page = page.derotation_matrix
    shape = page.new_shape()
    for stroke in strokes:
        pts = [pymupdf.Point(off_x + (px - min_x) * scale,
                             off_y + (py - min_y) * scale) * to_page
               for px, py in stroke]
        if len(pts) == 1:
            pts.append(pts[0])  # un simple point : tracé grâce aux extrémités arrondies
        shape.draw_polyline(pts)
    shape.finish(color=color, width=width, closePath=False, lineCap=1, lineJoin=1)
    shape.commit()


# --------------------------------------------------------------------------
# Fusion
# --------------------------------------------------------------------------

def append_pdf(doc: pymupdf.Document, path: str | Path) -> int:
    """Ajoute à la fin de `doc` toutes les pages du PDF `path`.
    Renvoie le nombre de pages ajoutées."""
    with pymupdf.open(str(path)) as src:
        doc.insert_pdf(src)
        return src.page_count


def merge_pdfs(inputs: Iterable[str | Path], output: str | Path | None = None) -> pymupdf.Document:
    """Fusionne plusieurs PDF dans l'ordre donné ; enregistre le résultat
    dans `output` s'il est fourni."""
    merged = pymupdf.open()
    for path in inputs:
        append_pdf(merged, path)
    if merged.page_count == 0:
        raise ValueError("Aucune page à fusionner.")
    if output is not None:
        save_pdf(merged, output)
    return merged


# --------------------------------------------------------------------------
# Modification du texte existant
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TextSpan:
    """Un morceau de texte du PDF ayant un style uniforme."""

    page_number: int
    text: str
    bbox: tuple[float, float, float, float]  # coordonnées affichées
    fontsize: float
    color: Color
    fontname: str  # police standard utilisée pour réécrire ce texte
    # Coordonnées internes (sans rotation) utilisées pour la réécriture.
    raw_bbox: tuple[float, float, float, float]
    origin: Point
    direction: Point


def get_text_spans(doc: pymupdf.Document, page_number: int) -> list[TextSpan]:
    """Liste les morceaux de texte d'une page."""
    page = doc[page_number]
    spans = []
    for line in _text_lines(page):
        for span in line["spans"]:
            text = "".join(c["c"] for c in span["chars"])
            if not text.strip():
                continue
            spans.append(_make_span(page, span, line["dir"], text,
                                    pymupdf.Rect(span["bbox"]), span["origin"]))
    return spans


def span_at(doc: pymupdf.Document, page_number: int, x: float, y: float) -> TextSpan | None:
    """Renvoie le morceau de texte situé sous le point (x, y), s'il y en a un."""
    return find_span(get_text_spans(doc, page_number), x, y)


def find_span(spans: Iterable[TextSpan], x: float, y: float) -> TextSpan | None:
    for span in spans:
        if pymupdf.Rect(span.bbox).contains(pymupdf.Point(x, y)):
            return span
    return None


def edit_span(doc: pymupdf.Document, span: TextSpan, new_text: str) -> None:
    """Remplace un morceau de texte par `new_text`, en conservant sa
    position, sa taille et sa couleur."""
    _rewrite(doc[span.page_number], [(span, new_text)])


def replace_text(
    doc: pymupdf.Document,
    old: str,
    new: str,
    page_number: int | None = None,
) -> int:
    """Remplace toutes les occurrences de `old` par `new` (sur une page ou
    sur tout le document). Renvoie le nombre de remplacements.

    La recherche se fait ligne par ligne : une occurrence coupée par un
    retour à la ligne n'est pas trouvée.
    """
    if not old:
        raise ValueError("Le texte à rechercher est vide.")
    pages = range(doc.page_count) if page_number is None else [page_number]
    count = 0
    for number in pages:
        page = doc[number]
        matches = [(span, new) for span in _find_in_lines(page, old)]
        if matches:
            _rewrite(page, matches)
            count += len(matches)
    return count


def _text_lines(page: pymupdf.Page):
    for block in page.get_text("rawdict")["blocks"]:
        if block["type"] == 0:
            yield from block["lines"]


def _find_in_lines(page: pymupdf.Page, old: str) -> list[TextSpan]:
    found = []
    for line in _text_lines(page):
        # Une ligne peut être découpée en plusieurs morceaux : on la recompose
        # caractère par caractère pour trouver aussi les occurrences à cheval.
        chars = [(c, span) for span in line["spans"] for c in span["chars"]]
        text = "".join(c["c"] for c, _ in chars)
        start = text.find(old)
        while start != -1:
            matched = chars[start:start + len(old)]
            rect = pymupdf.Rect(matched[0][0]["bbox"])
            for c, _ in matched[1:]:
                rect |= c["bbox"]
            first_char, span = matched[0]
            found.append(_make_span(page, span, line["dir"], old, rect, first_char["origin"]))
            start = text.find(old, start + len(old))
    return found


def _make_span(page, span, direction, text, raw_rect, origin) -> TextSpan:
    visual = raw_rect * page.rotation_matrix
    return TextSpan(
        page_number=page.number,
        text=text,
        bbox=tuple(visual),
        fontsize=span["size"],
        color=pymupdf.sRGB_to_pdf(span["color"]),
        fontname=_standard_font(span["font"], span["flags"]),
        raw_bbox=tuple(raw_rect),
        origin=tuple(origin),
        direction=tuple(direction),
    )


def _rewrite(page: pymupdf.Page, replacements: list[tuple[TextSpan, str]]) -> None:
    for span, _ in replacements:
        # Rectangle légèrement réduit : on efface le texte visé sans toucher
        # aux lignes voisines ni aux caractères adjacents.
        page.add_redact_annot(_core_rect(span), fill=False)
    page.apply_redactions(
        images=pymupdf.PDF_REDACT_IMAGE_NONE,
        graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
    )
    for span, new_text in replacements:
        if not new_text:
            continue
        dx, dy = span.direction
        angle = round(math.degrees(math.atan2(-dy, dx)) / 90) * 90 % 360
        page.insert_text(
            span.origin,
            new_text,
            fontsize=span.fontsize,
            fontname=span.fontname,
            color=span.color,
            rotate=angle,
        )


def _core_rect(span: TextSpan) -> pymupdf.Rect:
    r = pymupdf.Rect(span.raw_bbox)
    horizontal = abs(span.direction[0]) >= abs(span.direction[1])
    if horizontal:
        inset = min(0.5, r.width / 4)
        return pymupdf.Rect(r.x0 + inset, r.y0 + r.height / 4, r.x1 - inset, r.y1 - r.height / 4)
    inset = min(0.5, r.height / 4)
    return pymupdf.Rect(r.x0 + r.width / 4, r.y0 + inset, r.x1 - r.width / 4, r.y1 - inset)


def _standard_font(fontname: str, flags: int) -> str:
    """Choisit la police standard PDF la plus proche de la police d'origine
    (les polices intégrées aux PDF ne contiennent souvent que les caractères
    déjà utilisés et ne peuvent pas être réutilisées)."""
    name = fontname.lower()
    bold = bool(flags & _FLAG_BOLD) or any(w in name for w in ("bold", "black", "heavy"))
    italic = bool(flags & _FLAG_ITALIC) or "italic" in name or "oblique" in name
    if flags & _FLAG_MONO or "courier" in name or "mono" in name:
        family = ("cour", "cobo", "coit", "cobi")
    elif flags & _FLAG_SERIF or "times" in name or ("serif" in name and "sans" not in name):
        family = ("tiro", "tibo", "tiit", "tibi")
    else:
        family = ("helv", "hebo", "heit", "hebi")
    return family[int(bold) + 2 * int(italic)]


def _rect_to_page(page: pymupdf.Page, rect: Sequence[float]) -> pymupdf.Rect:
    return (pymupdf.Rect(rect) * page.derotation_matrix).normalize()


# --------------------------------------------------------------------------
# Formulaires (vrais champs PDF : cases, boutons radio, zones de texte…)
# --------------------------------------------------------------------------

_FIELD_KINDS = {
    pymupdf.PDF_WIDGET_TYPE_CHECKBOX: "case",
    pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON: "radio",
    pymupdf.PDF_WIDGET_TYPE_TEXT: "texte",
    pymupdf.PDF_WIDGET_TYPE_COMBOBOX: "liste",
    pymupdf.PDF_WIDGET_TYPE_LISTBOX: "liste",
}
_FLAG_READ_ONLY = 1


@dataclass(frozen=True)
class FormField:
    """Un champ de formulaire. `value` est un booléen pour les cases et
    boutons radio, une chaîne pour les autres."""

    page_number: int
    xref: int
    name: str
    kind: str  # "case", "radio", "texte" ou "liste"
    value: str | bool
    bbox: tuple[float, float, float, float]  # coordonnées affichées
    choices: tuple[str, ...] = ()
    read_only: bool = False


def get_form_fields(doc: pymupdf.Document, page_number: int) -> list[FormField]:
    page = doc[page_number]
    fields = []
    for widget in page.widgets():
        kind = _FIELD_KINDS.get(widget.field_type)
        if kind is None:
            continue
        if kind in ("case", "radio"):
            value = _button_state(doc, widget.xref) != "Off"
        else:
            value = widget.field_value or ""
        fields.append(FormField(
            page_number=page.number,
            xref=widget.xref,
            name=widget.field_name or "",
            kind=kind,
            value=value,
            bbox=tuple(widget.rect * page.rotation_matrix),
            choices=tuple(widget.choice_values or ()),
            read_only=bool(widget.field_flags & _FLAG_READ_ONLY),
        ))
    return fields


def field_at(fields: Iterable[FormField], x: float, y: float) -> FormField | None:
    point = pymupdf.Point(x, y)
    for field in fields:
        if pymupdf.Rect(field.bbox).contains(point):
            return field
    return None


def set_field(doc: pymupdf.Document, field: FormField, value: str | bool) -> None:
    """Coche/décoche une case ou un bouton radio (value booléen), ou remplit
    un champ texte ou une liste (value chaîne)."""
    if field.read_only:
        raise ValueError(f"Le champ « {field.name} » est en lecture seule.")
    page = doc[field.page_number]
    if field.kind in ("case", "radio"):
        _set_button(doc, page, field.xref, bool(value))
    else:
        widget = page.load_widget(field.xref)
        widget.field_value = str(value)
        widget.update()


def toggle_field(doc: pymupdf.Document, field: FormField) -> None:
    """Inverse une case à cocher ; sélectionne un bouton radio."""
    set_field(doc, field, True if field.kind == "radio" else not field.value)


def _set_button(doc: pymupdf.Document, page: pymupdf.Page, xref: int, checked: bool) -> None:
    on_state = _on_state(doc, xref)
    if on_state is None:
        # Case sans apparence prédéfinie : on laisse PyMuPDF la dessiner.
        widget = page.load_widget(xref)
        widget.field_value = widget.on_state() if checked else "Off"
        widget.update()
        return

    # La valeur appartient au champ, qui est soit le widget lui-même, soit
    # son parent (cas des groupes de boutons radio).
    parent = _xref_of(doc.xref_get_key(xref, "Parent"))
    has_name = doc.xref_get_key(xref, "T")[0] != "null"
    field_xref = xref if parent is None or has_name else parent
    kids = _xrefs_of(doc.xref_get_key(field_xref, "Kids")) if field_xref != xref else [xref]

    value = f"/{on_state}" if checked else "/Off"
    for kid in kids:
        # Les autres boutons du groupe s'éteignent, sauf ceux qui partagent
        # le même état (cases en double).
        kid_on = kid == xref or _on_state(doc, kid) == on_state
        doc.xref_set_key(kid, "AS", value if kid_on else "/Off")
    doc.xref_set_key(field_xref, "V", value)


def _button_state(doc: pymupdf.Document, xref: int) -> str:
    kind, value = doc.xref_get_key(xref, "AS")
    return value.lstrip("/") if kind == "name" else "Off"


def _on_state(doc: pymupdf.Document, xref: int) -> str | None:
    """Nom de l'état « coché » d'un bouton, lu dans ses apparences."""
    kind, value = doc.xref_get_key(xref, "AP/N")
    if kind == "xref":
        ref = _xref_of((kind, value))
        if doc.xref_is_stream(ref):
            return None
        value = doc.xref_object(ref, compressed=True)
    elif kind != "dict":
        return None
    states = re.findall(r"/([^\s/<>\[\]()]+)\s*\d+\s+\d+\s+R", value)
    return next((s for s in states if s != "Off"), None)


def _xref_of(entry: tuple[str, str]) -> int | None:
    kind, value = entry
    return int(value.split()[0]) if kind == "xref" else None


def _xrefs_of(entry: tuple[str, str]) -> list[int]:
    return [int(n) for n in re.findall(r"(\d+)\s+\d+\s+R", entry[1])]


# --------------------------------------------------------------------------
# Coches dans des cases imprimées (sans champ de formulaire)
# --------------------------------------------------------------------------

CHECK_MARK_SUBJECT = "Coche"
_BOX_GLYPHS = set("☐□❏❑❒▢◻⬜☑☒")


def find_boxes(doc: pymupdf.Document, page_number: int) -> list[tuple[float, float, float, float]]:
    """Repère les petits carrés dessinés (ou caractères « ☐ ») d'une page,
    qui servent souvent de cases à cocher dans les PDF imprimables."""
    page = doc[page_number]
    rects = []
    for drawing in page.get_drawings():
        rects.append(drawing["rect"])
        for item in drawing["items"]:
            if item[0] == "re":
                rects.append(item[1])
            elif item[0] == "qu":
                rects.append(item[1].rect)
    for line in _text_lines(page):
        for span in line["spans"]:
            for char in span["chars"]:
                if char["c"] in _BOX_GLYPHS:
                    x0, _, x1, _ = char["bbox"]
                    baseline = char["origin"][1]
                    rects.append(pymupdf.Rect(x0, baseline - (x1 - x0), x1, baseline))
    boxes = {tuple(round(v, 2) for v in (r * page.rotation_matrix).normalize())
             for r in rects if _looks_like_box(r)}
    return sorted(boxes)


def box_at(boxes: Iterable[Sequence[float]], x: float, y: float, tolerance: float = 2) -> tuple | None:
    """Renvoie la plus petite case contenant le point (x, y)."""
    point = pymupdf.Point(x, y)
    hits = [b for b in boxes
            if (pymupdf.Rect(b) + (-tolerance, -tolerance, tolerance, tolerance)).contains(point)]
    return min(hits, key=lambda b: pymupdf.Rect(b).get_area(), default=None)


def add_check_mark(
    doc: pymupdf.Document,
    page_number: int,
    rect: Sequence[float],
    color: Color = BLACK,
) -> None:
    """Dessine une coche ✓ dans le rectangle donné (sous forme d'annotation,
    ce qui permet de la retirer plus tard)."""
    page = doc[page_number]
    r = pymupdf.Rect(rect)
    shape = [(0.18, 0.52), (0.42, 0.78), (0.84, 0.2)]
    points = [tuple(pymupdf.Point(r.x0 + fx * r.width, r.y0 + fy * r.height) * page.derotation_matrix)
              for fx, fy in shape]
    annot = page.add_ink_annot([points])
    annot.set_border(width=max(0.8, min(r.width, r.height) * 0.12))
    annot.set_colors(stroke=color)
    annot.set_info(subject=CHECK_MARK_SUBJECT)
    annot.set_flags(pymupdf.PDF_ANNOT_IS_PRINT)
    annot.update()


def toggle_check_mark(
    doc: pymupdf.Document,
    page_number: int,
    rect: Sequence[float],
    color: Color = BLACK,
) -> bool:
    """Coche la case `rect`, ou retire la coche si elle y est déjà.
    Renvoie True si la case est maintenant cochée."""
    page = doc[page_number]
    target = pymupdf.Rect(rect)
    existing = [annot.xref for annot in page.annots(types=[pymupdf.PDF_ANNOT_INK])
                if annot.info.get("subject") == CHECK_MARK_SUBJECT
                and target.contains(_center(annot.rect * page.rotation_matrix))]
    for xref in existing:
        page.delete_annot(page.load_annot(xref))
    if existing:
        return False
    add_check_mark(doc, page_number, target, color)
    return True


def _looks_like_box(r: pymupdf.Rect) -> bool:
    return 4 <= r.width <= 40 and 4 <= r.height <= 40 and 0.7 <= r.width / r.height <= 1.4


def _center(r: pymupdf.Rect) -> pymupdf.Point:
    return pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
