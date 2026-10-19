"""Interface graphique (Tkinter) de l'éditeur PDF."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

import pymupdf

from . import core

PDF_TYPES = [("Documents PDF", "*.pdf"), ("Tous les fichiers", "*.*")]
IMAGE_TYPES = [("Images", "*.png *.jpg *.jpeg"), ("Tous les fichiers", "*.*")]
MAX_UNDO = 30
DEFAULT_SIGNATURE_SIZE = (180, 70)  # en points, pour un simple clic
ZOOM_LEVELS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0)

MODES = {
    "texte": "Cliquez sur la page pour ajouter du texte.",
    "modifier": "Cliquez sur un texte existant pour le modifier.",
    "signature": "Cliquez ou tracez un rectangle pour placer votre signature.",
}


class TextDialog(tk.Toplevel):
    """Fenêtre de saisie d'un texte sur plusieurs lignes."""

    def __init__(self, parent, title: str, initial: str = ""):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.result: str | None = None

        self.text = tk.Text(self, width=50, height=6, wrap="word", undo=True)
        self.text.insert("1.0", initial)
        self.text.tag_add("sel", "1.0", "end-1c")
        self.text.pack(fill="both", expand=True, padx=8, pady=8)

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(buttons, text="Annuler", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Valider", command=self._ok).pack(side="right", padx=4)
        ttk.Label(buttons, text="Ctrl+Entrée pour valider").pack(side="left")

        self.bind("<Control-Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.text.focus_set()
        self.grab_set()

    def _ok(self):
        self.result = self.text.get("1.0", "end-1c")
        self.destroy()

    @classmethod
    def ask(cls, parent, title: str, initial: str = "") -> str | None:
        dialog = cls(parent, title, initial)
        parent.wait_window(dialog)
        return dialog.result


class SignaturePad(tk.Toplevel):
    """Zone de dessin de la signature, ou import d'une image."""

    WIDTH, HEIGHT = 520, 200

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Votre signature")
        self.transient(parent)
        self.result: tuple[str, object] | None = None
        self.strokes: list[list[tuple[float, float]]] = []

        ttk.Label(self, text="Signez dans le cadre avec la souris :").pack(anchor="w", padx=8, pady=(8, 0))
        self.canvas = tk.Canvas(self, width=self.WIDTH, height=self.HEIGHT, bg="white",
                                highlightthickness=1, highlightbackground="#999", cursor="pencil")
        self.canvas.pack(padx=8, pady=8)
        self.canvas.bind("<ButtonPress-1>", self._start)
        self.canvas.bind("<B1-Motion>", self._draw)

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(buttons, text="Effacer", command=self._clear).pack(side="left")
        ttk.Button(buttons, text="Importer une image…", command=self._import).pack(side="left", padx=4)
        ttk.Button(buttons, text="Annuler", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Valider", command=self._ok).pack(side="right", padx=4)
        self.grab_set()

    def _start(self, event):
        self.strokes.append([(event.x, event.y)])
        self.canvas.create_oval(event.x - 1, event.y - 1, event.x + 1, event.y + 1, fill="#0d1a73", outline="")

    def _draw(self, event):
        if not self.strokes:
            return
        last = self.strokes[-1][-1]
        self.strokes[-1].append((event.x, event.y))
        self.canvas.create_line(*last, event.x, event.y, fill="#0d1a73", width=2.5,
                                capstyle="round", smooth=True)

    def _clear(self):
        self.strokes.clear()
        self.canvas.delete("all")

    def _import(self):
        path = filedialog.askopenfilename(parent=self, title="Image de signature", filetypes=IMAGE_TYPES)
        if path:
            self.result = ("image", Path(path).read_bytes())
            self.destroy()

    def _ok(self):
        if not self.strokes:
            messagebox.showinfo("Signature", "Dessinez d'abord votre signature.", parent=self)
            return
        self.result = ("strokes", self.strokes)
        self.destroy()

    @classmethod
    def ask(cls, parent):
        pad = cls(parent)
        parent.wait_window(pad)
        return pad.result


class PdfEditorApp:
    def __init__(self, root: tk.Tk, path: str | None = None):
        self.root = root
        self.doc: pymupdf.Document | None = None
        self.path: Path | None = None
        self.page_number = 0
        self.zoom = 1.5
        self.modified = False
        self.history: list[bytes] = []
        self.signature: tuple[str, object] | None = None
        self.color: core.Color = core.BLACK

        self.mode = tk.StringVar(value="texte")
        self.fontsize = tk.IntVar(value=12)
        self.status = tk.StringVar()

        self._photo: tk.PhotoImage | None = None
        self._spans: list[core.TextSpan] | None = None
        self._drag_start: tuple[float, float] | None = None

        self._build_ui()
        self._update_title()
        self._set_mode_hint()
        if path:
            self.load(path)

    # ---------------------------------------------------------------- UI --

    def _build_ui(self):
        root = self.root
        root.geometry("1000x800")
        root.protocol("WM_DELETE_WINDOW", self.quit)

        bar = ttk.Frame(root, padding=4)
        bar.pack(fill="x")
        for label, command in (("Ouvrir…", self.open_dialog),
                               ("Enregistrer", self.save),
                               ("Enregistrer sous…", self.save_as),
                               ("Fusionner des PDF…", self.merge_dialog),
                               ("Annuler", self.undo)):
            ttk.Button(bar, text=label, command=command).pack(side="left", padx=2)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(bar, text="◀", width=3, command=lambda: self.go_to(self.page_number - 1)).pack(side="left")
        self.page_label = ttk.Label(bar, width=14, anchor="center")
        self.page_label.pack(side="left")
        ttk.Button(bar, text="▶", width=3, command=lambda: self.go_to(self.page_number + 1)).pack(side="left")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(bar, text="−", width=3, command=lambda: self.change_zoom(-1)).pack(side="left")
        ttk.Button(bar, text="+", width=3, command=lambda: self.change_zoom(+1)).pack(side="left")

        tools = ttk.Frame(root, padding=(4, 0, 4, 4))
        tools.pack(fill="x")
        ttk.Label(tools, text="Outil :").pack(side="left")
        for value, label in (("texte", "Ajouter du texte"),
                             ("modifier", "Modifier le texte"),
                             ("signature", "Signer")):
            ttk.Radiobutton(tools, text=label, value=value, variable=self.mode,
                            command=self._set_mode_hint).pack(side="left", padx=4)
        ttk.Separator(tools, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Label(tools, text="Taille :").pack(side="left")
        ttk.Spinbox(tools, from_=4, to=96, width=4, textvariable=self.fontsize).pack(side="left", padx=2)
        self.color_button = tk.Button(tools, text="  Couleur  ", command=self.choose_color,
                                      fg="white", bg="#000000", activebackground="#000000")
        self.color_button.pack(side="left", padx=6)
        ttk.Button(tools, text="Changer de signature…", command=self.choose_signature).pack(side="left", padx=2)

        ttk.Label(root, textvariable=self.status, relief="sunken", padding=(6, 2)).pack(fill="x", side="bottom")

        area = ttk.Frame(root)
        area.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(area, bg="#6b6b6b", highlightthickness=0)
        vbar = ttk.Scrollbar(area, orient="vertical", command=self.canvas.yview)
        hbar = ttk.Scrollbar(area, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        vbar.pack(side="right", fill="y")
        hbar.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

        root.bind("<Control-o>", lambda e: self.open_dialog())
        root.bind("<Control-s>", lambda e: self.save())
        root.bind("<Control-z>", lambda e: self.undo())
        root.bind("<Prior>", lambda e: self.go_to(self.page_number - 1))
        root.bind("<Next>", lambda e: self.go_to(self.page_number + 1))

    def _set_mode_hint(self):
        self.canvas.delete("hover")
        self.status.set(MODES[self.mode.get()])
        self.canvas.configure(cursor="xterm" if self.mode.get() != "signature" else "crosshair")

    def _update_title(self):
        name = self.path.name if self.path else "Sans titre"
        self.root.title(f"{'*' if self.modified else ''}{name} — Éditeur PDF")

    # ---------------------------------------------------------- fichiers --

    def open_dialog(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(title="Ouvrir un PDF", filetypes=PDF_TYPES)
        if path:
            self.load(path)

    def load(self, path: str | Path):
        try:
            doc = core.open_pdf(path)
        except Exception as exc:  # fichier illisible, protégé, etc.
            messagebox.showerror("Ouverture impossible", str(exc))
            return
        if doc.needs_pass:
            messagebox.showerror("Ouverture impossible", "Ce PDF est protégé par un mot de passe.")
            return
        self.doc, self.path = doc, Path(path)
        self.page_number, self.history, self.modified = 0, [], False
        self.render()
        self._update_title()

    def save(self) -> bool:
        if self.doc is None:
            return False
        if self.path is None:
            return self.save_as()
        return self._write(self.path)

    def save_as(self) -> bool:
        if self.doc is None:
            return False
        path = filedialog.asksaveasfilename(
            title="Enregistrer sous", defaultextension=".pdf", filetypes=PDF_TYPES,
            initialfile=self.path.name if self.path else "document.pdf")
        return bool(path) and self._write(Path(path))

    def _write(self, path: Path) -> bool:
        try:
            core.save_pdf(self.doc, path)
        except Exception as exc:
            messagebox.showerror("Enregistrement impossible", str(exc))
            return False
        self.path, self.modified = path, False
        self._update_title()
        self.status.set(f"Enregistré : {path}")
        return True

    def merge_dialog(self):
        paths = filedialog.askopenfilenames(title="PDF à ajouter à la fin", filetypes=PDF_TYPES)
        if not paths:
            return
        if self.doc is None:
            self.doc, self.path, self.history = pymupdf.open(), None, []
        else:
            self._snapshot()
        added = 0
        try:
            for path in paths:
                added += core.append_pdf(self.doc, path)
        except Exception as exc:
            messagebox.showerror("Fusion impossible", str(exc))
        self._changed()
        self.status.set(f"{added} page(s) ajoutée(s) à la fin du document.")

    def _confirm_discard(self) -> bool:
        if not self.modified:
            return True
        answer = messagebox.askyesnocancel("Modifications non enregistrées",
                                           "Enregistrer les modifications avant de continuer ?")
        if answer is None:
            return False
        return self.save() if answer else True

    def quit(self):
        if self._confirm_discard():
            self.root.destroy()

    # ---------------------------------------------------------- affichage --

    def render(self):
        self.canvas.delete("all")
        self._spans = None
        if self.doc is None or self.doc.page_count == 0:
            self.page_label.configure(text="")
            return
        self.page_number = max(0, min(self.page_number, self.doc.page_count - 1))
        page = self.doc[self.page_number]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(self.zoom, self.zoom), alpha=False)
        self._photo = tk.PhotoImage(data=pix.tobytes("ppm"))
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self.canvas.configure(scrollregion=(0, 0, pix.width, pix.height))
        self.page_label.configure(text=f"Page {self.page_number + 1} / {self.doc.page_count}")

    def go_to(self, number: int):
        if self.doc and 0 <= number < self.doc.page_count and number != self.page_number:
            self.page_number = number
            self.render()
            self.canvas.yview_moveto(0)

    def change_zoom(self, step: int):
        levels = list(ZOOM_LEVELS)
        current = min(range(len(levels)), key=lambda i: abs(levels[i] - self.zoom))
        self.zoom = levels[max(0, min(len(levels) - 1, current + step))]
        self.render()
        self.status.set(f"Zoom : {int(self.zoom * 100)} %")

    def _page_point(self, event) -> tuple[float, float]:
        return self.canvas.canvasx(event.x) / self.zoom, self.canvas.canvasy(event.y) / self.zoom

    def _screen_rect(self, rect) -> tuple[float, ...]:
        return tuple(v * self.zoom for v in rect)

    def _current_spans(self) -> list[core.TextSpan]:
        if self._spans is None:
            self._spans = core.get_text_spans(self.doc, self.page_number)
        return self._spans

    # -------------------------------------------------------- historique --

    def _snapshot(self):
        self.history.append(self.doc.tobytes())
        del self.history[:-MAX_UNDO]

    def _changed(self):
        self.modified = True
        self.render()
        self._update_title()

    def undo(self):
        if not self.history:
            self.status.set("Rien à annuler.")
            return
        self.doc = pymupdf.open(stream=self.history.pop(), filetype="pdf")
        self._changed()
        self.status.set("Dernière modification annulée.")

    # ------------------------------------------------------------ souris --

    def on_motion(self, event):
        self.canvas.delete("hover")
        if self.doc is None or self.mode.get() != "modifier":
            return
        span = core.find_span(self._current_spans(), *self._page_point(event))
        if span:
            self.canvas.create_rectangle(*self._screen_rect(span.bbox), outline="#1a73e8",
                                         width=2, tags="hover")

    def on_press(self, event):
        if self.doc is None or self.doc.page_count == 0:
            return
        x, y = self._page_point(event)
        mode = self.mode.get()
        if mode == "texte":
            self.add_text_at(x, y)
        elif mode == "modifier":
            span = core.find_span(self._current_spans(), x, y)
            if span:
                self.edit(span)
        else:
            self._drag_start = (x, y)

    def on_drag(self, event):
        if self._drag_start is None:
            return
        self.canvas.delete("drag")
        x, y = self._page_point(event)
        self.canvas.create_rectangle(*self._screen_rect((*self._drag_start, x, y)),
                                     outline="#1a73e8", dash=(4, 2), tags="drag")

    def on_release(self, event):
        if self._drag_start is None:
            return
        self.canvas.delete("drag")
        x0, y0 = self._drag_start
        x1, y1 = self._page_point(event)
        self._drag_start = None
        rect = pymupdf.Rect(x0, y0, x1, y1).normalize()
        if rect.width < 15 or rect.height < 10:  # simple clic : taille par défaut
            w, h = DEFAULT_SIGNATURE_SIZE
            rect = pymupdf.Rect(x0, y0, x0 + w, y0 + h)
        self.sign(rect)

    # ----------------------------------------------------------- actions --

    def add_text_at(self, x: float, y: float):
        text = TextDialog.ask(self.root, "Ajouter du texte")
        if not text or not text.strip():
            return
        self._apply(core.add_text, self.doc, self.page_number, x, y, text,
                    fontsize=self._fontsize(), color=self.color)

    def edit(self, span: core.TextSpan):
        new_text = TextDialog.ask(self.root, "Modifier le texte", span.text)
        if new_text is None or new_text == span.text:
            return
        self._apply(core.edit_span, self.doc, span, new_text.replace("\n", " "))

    def sign(self, rect: pymupdf.Rect):
        if self.signature is None and not self.choose_signature():
            return
        kind, data = self.signature
        if kind == "image":
            self._apply(core.add_signature_image, self.doc, self.page_number, rect, data)
        else:
            self._apply(core.add_drawn_signature, self.doc, self.page_number, data, rect)

    def choose_signature(self) -> bool:
        result = SignaturePad.ask(self.root)
        if result:
            self.signature = result
            self.mode.set("signature")
            self._set_mode_hint()
        return result is not None

    def choose_color(self):
        _, hex_color = colorchooser.askcolor(title="Couleur du texte")
        if hex_color:
            self.color = core.parse_color(hex_color)
            self.color_button.configure(bg=hex_color, activebackground=hex_color)

    def _fontsize(self) -> int:
        try:
            return max(1, int(self.fontsize.get()))
        except (tk.TclError, ValueError):
            return 12

    def _apply(self, func, *args, **kwargs):
        self._snapshot()
        try:
            func(*args, **kwargs)
        except Exception as exc:
            # On revient à l'état d'avant, au cas où l'action a échoué à mi-chemin.
            self.doc = pymupdf.open(stream=self.history.pop(), filetype="pdf")
            self.render()
            messagebox.showerror("Erreur", str(exc))
            return
        self._changed()


def run(path: str | None = None):
    root = tk.Tk()
    PdfEditorApp(root, path)
    root.mainloop()
