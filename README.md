# Éditeur PDF (Python)

Un éditeur PDF simple, avec une interface graphique et une ligne de commande :

- **ajouter du texte** n'importe où sur une page (taille et couleur au choix, plusieurs lignes possibles) ;
- **signer** : dessiner sa signature à la souris ou importer une image ;
- **fusionner** plusieurs PDF ;
- **modifier le texte existant** : cliquer sur un texte pour le réécrire, ou rechercher/remplacer dans tout le document ;
- **remplir les formulaires** : cocher des cases, choisir un bouton radio, remplir les champs texte, ou ajouter une coche ✓ dans une case simplement imprimée.

Basé sur [PyMuPDF](https://pymupdf.readthedocs.io/) pour le PDF et Tkinter (fourni avec Python) pour l'interface.

## Application Windows (.exe)

Téléchargez **[EditeurPDF.exe](https://github.com/alexisblush66-bot/Git-Repo-/releases/download/editeur-pdf/EditeurPDF.exe)** puis double-cliquez dessus : rien d'autre à installer.

- Au premier lancement, Windows peut afficher « Windows a protégé votre ordinateur » (l'application n'est pas signée par un éditeur connu) : cliquez sur **Informations complémentaires**, puis **Exécuter quand même**.
- Le démarrage prend quelques secondes.
- Vous pouvez aussi faire glisser un PDF sur `EditeurPDF.exe` pour l'ouvrir directement.

Le fichier est fabriqué automatiquement par GitHub (onglet *Actions*, « Application Windows ») à chaque mise à jour du code.

## Installation (version Python)

Python 3.10 ou plus récent est nécessaire.

```bash
pip install -r requirements.txt
```

> Sous Linux, Tkinter s'installe parfois à part : `sudo apt install python3-tk`.

## Interface graphique

```bash
python -m pdf_editor                 # ouvre l'éditeur
python -m pdf_editor contrat.pdf     # ouvre directement un fichier
```

Choisissez un **outil** dans la deuxième barre :

| Outil | Utilisation |
|---|---|
| **Ajouter du texte** | Cliquez à l'endroit voulu, tapez le texte, puis validez (Ctrl+Entrée). La taille et la couleur se règlent dans la barre d'outils. |
| **Modifier le texte** | Le texte sous la souris est encadré en bleu. Cliquez dessus pour le corriger. |
| **Cocher une case** | Cliquez sur une case imprimée (☐ ou petit carré, encadré en vert au survol) pour y mettre une coche ✓ ; recliquez pour la retirer. Ailleurs, la coche est placée là où vous cliquez (taille réglable). |
| **Signer** | Au premier usage, dessinez votre signature (ou importez une image PNG). Ensuite, cliquez sur la page pour la poser, ou tracez un rectangle pour choisir sa taille. |

- **Formulaires** : les vrais champs de formulaire (encadrés en vert au survol) réagissent quel que soit l'outil choisi, sauf Signer : un clic coche ou décoche une case, sélectionne un bouton radio, ou ouvre la saisie d'un champ texte ou d'une liste.
- **Fusionner des PDF…** ajoute les pages d'autres PDF à la fin du document ouvert (sans document ouvert, crée un nouveau document).
- **Annuler** (Ctrl+Z) revient en arrière, jusqu'à 30 étapes.
- **Enregistrer** (Ctrl+S) écrase le fichier ouvert ; **Enregistrer sous…** crée une copie.
- Page précédente/suivante : boutons ◀ ▶ ou touches Page préc./Page suiv. ; zoom : boutons − +.

## Ligne de commande

Les positions sont en points (1 point = 1/72 de pouce ; une page A4 mesure 595 × 842 points), mesurées depuis le coin supérieur gauche. Les pages sont numérotées à partir de 1.

```bash
# Ajouter du texte
python -m pdf_editor texte entree.pdf sortie.pdf --page 1 --x 72 --y 700 \
    --texte "Lu et approuvé\nle 19/10/2026" --taille 11 --couleur "#000080"

# Signer avec une image
python -m pdf_editor signer entree.pdf sortie.pdf --page 2 --image signature.png --rect 350 700 550 780

# Fusionner
python -m pdf_editor fusionner resultat.pdf partie1.pdf partie2.pdf annexe.pdf

# Remplacer du texte (dans tout le document, ou --page N)
python -m pdf_editor remplacer entree.pdf sortie.pdf --ancien "750 euros" --nouveau "820 euros"
```

Le fichier de sortie peut être le même que le fichier d'entrée.

## Utilisation depuis Python

```python
from pdf_editor import open_pdf, add_text, replace_text, add_signature_image, save_pdf

doc = open_pdf("contrat.pdf")
add_text(doc, 0, 72, 700, "Lu et approuvé")          # page 0 = première page
replace_text(doc, "Dupont", "Martin")
add_signature_image(doc, 0, (350, 700, 550, 780), "signature.png")
save_pdf(doc, "contrat-signe.pdf")
```

## Limites à connaître

- **Modification du texte existant** : un PDF ne contient pas de paragraphes, seulement des caractères placés à des positions précises. L'éditeur efface l'ancien texte et écrit le nouveau au même endroit, avec la même taille et la même couleur, mais dans la **police standard la plus proche** (Helvetica, Times ou Courier, en gras/italique si besoin) : les polices intégrées aux PDF ne contiennent souvent que les lettres déjà utilisées. Si le nouveau texte est plus long, il peut chevaucher la suite de la ligne. La recherche se fait ligne par ligne.
- Les **PDF scannés** (images) ne contiennent pas de texte modifiable.
- Les polices standard couvrent l'alphabet latin (accents français compris), pas les autres écritures.
- La **signature** est une signature visuelle (comme une signature manuscrite scannée), pas une signature électronique certifiée (eIDAS).
- Les PDF protégés par mot de passe ne sont pas pris en charge.

## Tests

```bash
pip install pytest
python -m pytest
```
