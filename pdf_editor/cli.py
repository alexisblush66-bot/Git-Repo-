"""Ligne de commande de l'éditeur PDF.

Sans argument (ou avec un simple nom de fichier), lance l'interface
graphique. Les numéros de page sont comptés à partir de 1.
"""

from __future__ import annotations

import argparse
import sys

from . import core

COMMANDS = ("texte", "signer", "fusionner", "remplacer")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pdf_editor",
        description="Éditeur PDF : ajouter du texte, signer, fusionner, "
                    "modifier le texte existant. Sans commande, ouvre "
                    "l'interface graphique.",
    )
    sub = parser.add_subparsers(dest="commande", required=True)

    p = sub.add_parser("texte", help="ajouter du texte sur une page")
    _add_io(p)
    p.add_argument("--page", type=int, default=1, help="numéro de page (défaut : 1)")
    p.add_argument("--x", type=float, required=True, help="position horizontale en points")
    p.add_argument("--y", type=float, required=True, help="position verticale en points (depuis le haut)")
    p.add_argument("--texte", required=True, help="texte à ajouter (\\n pour un retour à la ligne)")
    p.add_argument("--taille", type=float, default=12, help="taille de police (défaut : 12)")
    p.add_argument("--couleur", default="#000000", help="couleur #RRGGBB (défaut : noir)")

    p = sub.add_parser("signer", help="apposer une image de signature")
    _add_io(p)
    p.add_argument("--page", type=int, default=1, help="numéro de page (défaut : 1)")
    p.add_argument("--image", required=True, help="image de la signature (PNG avec transparence conseillé)")
    p.add_argument("--rect", type=float, nargs=4, required=True,
                   metavar=("X0", "Y0", "X1", "Y1"), help="zone de la signature en points")

    p = sub.add_parser("fusionner", help="fusionner plusieurs PDF")
    p.add_argument("sortie", help="PDF à créer")
    p.add_argument("entrees", nargs="+", help="PDF à fusionner, dans l'ordre")

    p = sub.add_parser("remplacer", help="remplacer du texte existant")
    _add_io(p)
    p.add_argument("--ancien", required=True, help="texte à rechercher")
    p.add_argument("--nouveau", required=True, help="texte de remplacement (vide pour supprimer)")
    p.add_argument("--page", type=int, help="limiter à une page (défaut : toutes)")

    return parser


def _add_io(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("entree", help="PDF source")
    parser.add_argument("sortie", help="PDF résultat (peut être identique à la source)")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or (argv[0] not in COMMANDS and not argv[0].startswith("-")):
        from .gui import run  # import tardif : la CLI fonctionne sans Tkinter
        run(argv[0] if argv else None)
        return 0

    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except (OSError, ValueError, IndexError, RuntimeError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace) -> int:
    if args.commande == "fusionner":
        doc = core.merge_pdfs(args.entrees, args.sortie)
        print(f"{doc.page_count} pages écrites dans {args.sortie}")
        return 0

    doc = core.open_pdf(args.entree)
    if args.page is not None and not 1 <= args.page <= doc.page_count:
        raise ValueError(f"La page {args.page} n'existe pas (le document a {doc.page_count} pages).")
    page = None if args.page is None else args.page - 1

    if args.commande == "texte":
        core.add_text(doc, page, args.x, args.y, args.texte.replace("\\n", "\n"),
                      fontsize=args.taille, color=core.parse_color(args.couleur))
    elif args.commande == "signer":
        core.add_signature_image(doc, page, args.rect, args.image)
    elif args.commande == "remplacer":
        count = core.replace_text(doc, args.ancien, args.nouveau, page)
        print(f"{count} remplacement(s) effectué(s)")
        if count == 0:
            return 1

    core.save_pdf(doc, args.sortie)
    print(f"Enregistré : {args.sortie}")
    return 0
