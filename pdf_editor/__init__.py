"""Éditeur PDF : ajouter du texte, signer, fusionner, modifier le texte existant."""

from .core import (
    TextSpan,
    add_drawn_signature,
    add_signature_image,
    add_text,
    append_pdf,
    edit_span,
    get_text_spans,
    merge_pdfs,
    open_pdf,
    replace_text,
    save_pdf,
    span_at,
)

__all__ = [
    "TextSpan",
    "add_drawn_signature",
    "add_signature_image",
    "add_text",
    "append_pdf",
    "edit_span",
    "get_text_spans",
    "merge_pdfs",
    "open_pdf",
    "replace_text",
    "save_pdf",
    "span_at",
]
