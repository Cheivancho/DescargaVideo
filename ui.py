"""Interfaz gráfica (tkinter): ventana, estilos, widgets y cola de eventos."""
import ctypes
import io
import logging
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import traceback
import urllib.request
from tkinter import filedialog, messagebox, simpledialog, ttk

import yt_dlp
from PIL import Image, ImageOps, ImageTk

import updater
from config import (
    DEFAULT_SETTINGS,
    FACTORY_PRESETS,
    PRESET_KEYS,
    RES_DIR,
    load_presets,
    load_settings,
    normalize_preset,
    pick_heights,
    save_presets,
)
from convert import cached_gpu, detect_gpu_encoders
from downloader import (
    Downloader,
    diagnose_formats,
    find_js_runtimes,
    friendly_error,
    has_video_and_list,
    youtube_link,
)
from formats import (
    AUDIO_FORMATS,
    AUDIO_QUALITIES,
    COOKIE_BROWSERS,
    FPS_CHOICES,
    GPU_TABLE,
    OUT_FORMATS,
    PLAYLIST_HEIGHTS,
    SCALE_MODES,
    SCALE_PRESETS,
    SUBS_MODES,
    parse_langs,
    register_gpu_formats,
    resolve_scale,
    validate_trim,
)
from util import fmt_date, fmt_dur, fmt_num, short_title

log = logging.getLogger("descargador")


# Paleta
BG = "#121216"
PANEL = "#1b1b22"
FIELD = "#24242d"
CORAL = "#F22E62"
CORAL_DIM = "#a51f43"
CORAL_SOFT = "#f77a99"
MUTED = "#a0607a"
FONT = "Segoe UI"
THUMB_W, THUMB_H = 320, 180  # en píxeles a 96 DPI; se escalan con el DPI de la pantalla


def enable_dpi_awareness() -> None:
    """Evita el escalado borroso de Windows en pantallas con DPI alto."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # por monitor
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.ui = max(self.winfo_fpixels("1i") / 96, 1.0)  # factor de escala por DPI
        self.thumb_w, self.thumb_h = self.px(THUMB_W), self.px(THUMB_H)
        self.title("Descargador de YouTube")
        self.geometry(f"{self.px(1060)}x{self.px(740)}")
        self.minsize(self.px(1000), self.px(700))
        self.configure(bg=BG)
        try:
            self.iconbitmap(os.path.join(RES_DIR, "icon.ico"))
        except Exception:  # noqa: BLE001
            pass
        self.q = queue.Queue()
        self.dl = Downloader(self.q.put, find_js_runtimes())
        self.is_playlist = False
        self.analyzed_url = None  # URL realmente analizada: la descarga usa esta, no el campo de texto
        self.analyzed_info = None  # info de un video individual, reutilizable mientras no caduque
        self.analyzed_at = 0.0
        self.analyzed_duration = None
        self.pending_heights = None  # resoluciones pedidas por un preset (se aplican al analizar)
        self.queue_items = []  # cola de descargas: ítems {url, spec, ...}
        self._running_queue = False
        self.playlist_choice = None  # "video" | "list" | None (el enlace no era ambiguo)
        self.res_vars = {}
        self.busy = False
        self.thumb_img = None
        register_gpu_formats(cached_gpu())  # opciones GPU ya comprobadas en un arranque anterior (sin ejecutar ffmpeg)
        self.settings = load_settings()
        self._saved_fmt, self._fmt_restored = self.settings["fmt"], False
        # copia para los hilos de descarga (no se leen variables tk fuera del hilo de la interfaz)
        self.dl.cookie_browser = self.settings["cookies"]
        self.out_dir = tk.StringVar(value=self.settings["out_dir"])
        self._restore_geometry()
        self._styles()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<FocusIn>", self._on_focus_in)
        self.after(300, self._paste_clipboard_link)
        self.after(100, self._poll)
        self.after(1200, lambda: threading.Thread(target=self._check_update_worker, daemon=True).start())
        # La consulta/descarga de yt-dlp va en segundo plano y DESPUÉS de mostrar la ventana
        self.after(2500, lambda: threading.Thread(target=self._engine_update_worker, daemon=True).start())
        self.after(1500, lambda: threading.Thread(target=self._gpu_worker, daemon=True).start())

    def _restore_geometry(self) -> None:
        m = re.fullmatch(r"(\d+)x(\d+)", self.settings["geometry"])
        if not m:
            return
        w = min(max(int(m[1]), self.px(1000)), self.winfo_screenwidth())
        h = min(max(int(m[2]), self.px(700)), self.winfo_screenheight())
        self.geometry(f"{w}x{h}")

    def _save_settings(self) -> None:
        self.settings.update({k: var.get() for k, var in self.v.items() if k in DEFAULT_SETTINGS})
        self.settings.update(out_dir=self.out_dir.get(), fmt=OUT_FORMATS.get(self.fmt_var.get(), "h264"),
                             preset=self.preset_var.get(),
                             geometry=f"{self.winfo_width()}x{self.winfo_height()}")
        updater.update_state(settings=self.settings)

    def _on_close(self) -> None:
        try:
            self._save_settings()
        except Exception:  # noqa: BLE001
            log.warning("No se pudieron guardar los ajustes", exc_info=True)
        self.destroy()

    def _paste_clipboard_link(self) -> None:
        """Si el campo está vacío y el portapapeles tiene un enlace de YouTube, lo pega (sin analizar)."""
        if self.url_var.get().strip() or self.busy:
            return
        try:
            link = youtube_link(self.clipboard_get())
        except tk.TclError:  # portapapeles vacío o con algo que no es texto
            return
        if link:
            self.url_var.set(link)
            self.status.set("Enlace pegado desde el portapapeles. Pulsa Analizar.")

    def _on_focus_in(self, event) -> None:
        if event.widget is self:
            self._paste_clipboard_link()

    def px(self, n: int) -> int:
        """Píxeles a 96 DPI -> píxeles reales de esta pantalla."""
        return int(round(n * getattr(self, "ui", 1.0)))

    # ---------- Estilos ----------
    def _styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TEntry", fieldbackground=FIELD, foreground=CORAL, insertcolor=CORAL,
                    bordercolor=CORAL_DIM, lightcolor=FIELD, darkcolor=FIELD, padding=8)
        s.map("TEntry", bordercolor=[("focus", CORAL)])
        s.configure("Dark.TNotebook", background=PANEL, borderwidth=0, tabmargins=(0, 0, 0, 6), bordercolor=PANEL,
                    lightcolor=PANEL, darkcolor=PANEL)
        s.configure("Dark.TNotebook.Tab", lightcolor=FIELD, bordercolor=FIELD)
        s.configure("Dark.TNotebook.Tab", background=FIELD, foreground=CORAL_SOFT, padding=(11, 6), borderwidth=0,
                    font=(FONT, 10, "bold"))
        s.map("Dark.TNotebook.Tab", background=[("selected", CORAL_DIM)], foreground=[("selected", "white")])
        s.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=CORAL, arrowcolor=CORAL,
                    bordercolor=CORAL_DIM, lightcolor=FIELD, darkcolor=FIELD, padding=4)
        s.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", CORAL)])
        self.option_add("*TCombobox*Listbox.background", FIELD)
        self.option_add("*TCombobox*Listbox.foreground", CORAL)
        self.option_add("*TCombobox*Listbox.selectBackground", CORAL_DIM)
        s.configure("Coral.Horizontal.TProgressbar", troughcolor=FIELD, background=CORAL,
                    bordercolor=PANEL, lightcolor=CORAL, darkcolor=CORAL, thickness=8)

    def _btn(self, parent, text, cmd, solid=False, **kw):
        b = tk.Button(parent, text=text, command=cmd, relief="flat", bd=0, cursor="hand2",
                      font=(FONT, 10, "bold"),
                      bg=CORAL if solid else FIELD, fg=BG if solid else CORAL,
                      activebackground=CORAL_SOFT if solid else CORAL_DIM,
                      activeforeground=BG if solid else "white",
                      disabledforeground="#6b4757", padx=14, pady=7, **kw)
        return b

    def _tab(self, name):
        """Pestaña del panel izquierdo; devuelve el marco interior donde colocar los controles."""
        outer = tk.Frame(self.tabs, bg=PANEL)
        self.tabs.add(outer, text=f"  {name}  ")
        inner = tk.Frame(outer, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=4, pady=6)
        return inner

    def _check(self, parent, text, var, **kw):
        return tk.Checkbutton(parent, text="  " + text, variable=var, bg=PANEL, fg=CORAL, activebackground=PANEL,
                              activeforeground=CORAL_SOFT, selectcolor=FIELD, font=(FONT, 10), bd=0,
                              highlightthickness=0, cursor="hand2", **kw)

    # ---------- Presets ----------
    def _preset_names(self):
        return list(FACTORY_PRESETS) + [n for n in load_presets() if n not in FACTORY_PRESETS]

    def _current_preset(self) -> dict:
        p = {k: self.v[k].get() for k in PRESET_KEYS if k in self.v}
        p["fmt"] = OUT_FORMATS[self.fmt_var.get()]
        p["heights"] = [h for h, var in self.res_vars.items() if var.get()]
        return normalize_preset(p)

    def _apply_preset(self, name):
        raw = FACTORY_PRESETS.get(name) or load_presets().get(name)
        if raw is None:
            return
        p = normalize_preset(raw)
        for k in PRESET_KEYS:
            if k == "fmt":
                self.fmt_var.set(next((lbl for lbl, key in OUT_FORMATS.items() if key == p["fmt"]),
                                      next(iter(OUT_FORMATS))))  # GPU no disponible: H.264
            else:
                self.v[k].set(p[k])
        self.pending_heights = p["heights"]
        if self.res_vars:
            sel = set(pick_heights(list(self.res_vars), p["heights"]))
            for h, var in self.res_vars.items():
                var.set(h in sel)
            self._refresh_chips()
        self.settings["preset"] = name
        self.status.set(f"Preset «{name}» aplicado." + ("" if self.res_vars else " Analiza un enlace para elegir "
                                                                                   "las resoluciones."))

    def _save_preset(self):
        name = simpledialog.askstring("Guardar preset", "Nombre del preset:", parent=self)
        name = (name or "").strip()[:40]
        if not name:
            return
        if name in FACTORY_PRESETS:
            messagebox.showinfo("Preset de fábrica", "Ese nombre es de un preset de fábrica. Elige otro nombre.")
            return
        presets = load_presets()
        presets[name] = self._current_preset()
        try:
            save_presets(presets)
        except OSError as e:
            messagebox.showerror("Presets", f"No se pudo guardar: {e}")
            return
        self.preset_box["values"] = self._preset_names()
        self.preset_var.set(name)
        self.settings["preset"] = name
        self.status.set(f"Preset «{name}» guardado.")

    def _delete_preset(self):
        name = self.preset_var.get()
        if not name:
            return
        if name in FACTORY_PRESETS:
            messagebox.showinfo("Preset de fábrica", "Los presets de fábrica no se pueden borrar.")
            return
        if not messagebox.askyesno("Borrar preset", f"¿Borrar el preset «{name}»?"):
            return
        presets = load_presets()
        presets.pop(name, None)
        try:
            save_presets(presets)
        except OSError as e:
            messagebox.showerror("Presets", f"No se pudo borrar: {e}")
            return
        self.preset_box["values"] = self._preset_names()
        self.preset_var.set("")
        self.settings["preset"] = ""

    def _sync_scale(self):
        custom = self.v["scale_preset"].get() == "Personalizada"
        self.scale_custom_entry.config(state="normal" if custom else "disabled")

    def _sync_audio_quality(self):
        has_q = AUDIO_FORMATS.get(self.v["audio_fmt"].get(), ("", "", False))[2]
        self.audio_q_box.config(state="readonly" if has_q else "disabled")

    def _label(self, parent, text="", size=10, bold=False, color=CORAL, bg=BG, **kw):
        return tk.Label(parent, text=text, bg=bg, fg=color, font=(FONT, size, "bold" if bold else "normal"), **kw)

    # ---------- UI ----------
    def _build(self):
        # Cabecera
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=24, pady=(20, 8))
        self._label(head, "▶  Descargador de YouTube", 18, True).pack(side="left")
        self._label(head, f"v{updater.VERSION}", 9, False, MUTED).pack(side="left", padx=(10, 0), pady=(8, 0))
        self.btn_help = self._btn(head, "Ayuda ▾", self._show_help_menu)
        self.btn_help.config(pady=3, padx=10)
        self.btn_help.pack(side="right")
        self.engine_lbl = self._label(head, "", 9, False, MUTED)
        self.engine_lbl.pack(side="right", padx=(0, 12), pady=(2, 0))
        self.help_menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=CORAL, activebackground=CORAL_DIM,
                                 activeforeground="white", font=(FONT, 10), bd=0)
        self.help_menu.add_command(label="Abrir log", command=self._open_log)
        self.help_menu.add_command(label="Acerca de…", command=self._about)
        self.help_menu.add_separator()
        self.help_menu.add_command(label="Buscar actualizaciones ahora", command=self._check_updates_now)
        self.help_menu.add_command(label="Restaurar motor incluido", command=self._reset_engine)
        self.help_menu.add_command(label="Detectar la GPU de nuevo", command=self._redetect_gpu)

        # Barra de URL
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=24, pady=(4, 14))
        self.url_var = tk.StringVar()
        self.url_var.trace_add("write", self._on_url_edit)
        self.url = ttk.Entry(bar, font=(FONT, 11), textvariable=self.url_var)
        self.url.pack(side="left", fill="x", expand=True, ipady=3)
        self.url.bind("<Return>", lambda e: self.analyze())
        self.btn_an = self._btn(bar, "Analizar", self.analyze)
        self.btn_an.pack(side="left", padx=(10, 0))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        body.columnconfigure(0, weight=1, uniform="c")
        body.columnconfigure(1, weight=1, uniform="c")
        body.rowconfigure(0, weight=1)

        # ----- Panel izquierdo: opciones (pestañas) -----
        left = tk.Frame(body, bg=PANEL)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        inner = tk.Frame(left, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=16, pady=14)

        # Destino: se empaqueta primero (side="bottom") para que SIEMPRE sea visible
        dest_box = tk.Frame(inner, bg=PANEL)
        dest_box.pack(side="bottom", fill="x", pady=(10, 0))
        self._label(dest_box, "CARPETA DE DESTINO", 9, True, CORAL_SOFT, PANEL).pack(anchor="w", pady=(0, 6))
        dest = tk.Frame(dest_box, bg=PANEL)
        dest.pack(fill="x")
        ttk.Entry(dest, textvariable=self.out_dir).pack(side="left", fill="x", expand=True)
        self._btn(dest, "…", self._browse).pack(side="left", padx=(8, 0))

        prow = tk.Frame(inner, bg=PANEL)
        prow.pack(side="top", fill="x", pady=(0, 8))
        self._label(prow, "PRESET", 9, True, CORAL_SOFT, PANEL).pack(side="left")
        self.preset_var = tk.StringVar(value=self.settings["preset"])
        self.preset_box = ttk.Combobox(prow, textvariable=self.preset_var, state="readonly", font=(FONT, 10),
                                       values=self._preset_names())
        self.preset_box.pack(side="left", fill="x", expand=True, padx=8)
        self.preset_box.bind("<<ComboboxSelected>>", lambda e: self._apply_preset(self.preset_var.get()))
        self._btn(prow, "Guardar", self._save_preset).pack(side="left")
        self._btn(prow, "Borrar", self._delete_preset).pack(side="left", padx=(6, 0))

        self.tabs = ttk.Notebook(inner, style="Dark.TNotebook")
        self.tabs.pack(fill="both", expand=True)
        tab_video = self._tab("Video")
        tab_scale = self._tab("Escala/corte")
        tab_extra = self._tab("Extras")
        tab_queue = self._tab("Cola")

        # --- Pestaña Video ---
        self._label(tab_video, "RESOLUCIONES", 9, True, CORAL_SOFT, PANEL).pack(anchor="w")
        row = tk.Frame(tab_video, bg=PANEL)
        row.pack(fill="x", pady=(6, 8))
        self._btn(row, "Todas", lambda: self._set_all(True)).pack(side="left")
        self._btn(row, "Ninguna", lambda: self._set_all(False)).pack(side="left", padx=6)

        self.res_frame = tk.Frame(tab_video, bg=PANEL)
        self.res_frame.pack(fill="x")
        self.res_hint = self._label(self.res_frame, "Analiza un enlace para ver\nlas resoluciones disponibles.",
                                    10, False, MUTED, PANEL, justify="left")
        self.res_hint.pack(anchor="w", pady=10)

        tk.Frame(tab_video, bg=CORAL_DIM, height=1).pack(fill="x", pady=12)

        self._label(tab_video, "FORMATO DE SALIDA", 9, True, CORAL_SOFT, PANEL).pack(anchor="w")
        self.fmt_var = tk.StringVar(value=next((k for k, v in OUT_FORMATS.items() if v == self.settings["fmt"]),
                                               next(iter(OUT_FORMATS))))
        self.fmt_box = ttk.Combobox(tab_video, textvariable=self.fmt_var, values=list(OUT_FORMATS), state="readonly",
                                    font=(FONT, 10))
        self.fmt_box.pack(fill="x", pady=(6, 0))
        self._label(tab_video, "ProRes y HAP generan archivos muy pesados (varios GB por minuto en 4K).",
                    8, False, MUTED, PANEL, wraplength=self.px(380), justify="left").pack(anchor="w", pady=(4, 0))

        # --- Pestaña Extras ---
        s = self.settings
        self.v = {
            "audio": tk.BooleanVar(value=s["audio"]), "audio_fmt": tk.StringVar(value=s["audio_fmt"]),
            "audio_q": tk.StringVar(value=s["audio_q"]), "subs": tk.BooleanVar(value=s["subs"]),
            "subs_langs": tk.StringVar(value=s["subs_langs"]), "subs_mode": tk.StringVar(value=s["subs_mode"]),
            "embed": tk.BooleanVar(value=s["embed"]), "fps": tk.StringVar(value=s["fps"]),
            "scale_preset": tk.StringVar(value=s["scale_preset"]),
            "scale_custom": tk.StringVar(value=s["scale_custom"]),
            "scale_mode": tk.StringVar(value=s["scale_mode"]), "cookies": tk.StringVar(value=s["cookies"]),
            "trim_start": tk.StringVar(),
            "trim_end": tk.StringVar(), "trim_exact": tk.BooleanVar(value=False),
        }
        self.audio_var = self.v["audio"]

        # --- Video: FPS ---
        tk.Frame(tab_video, bg=CORAL_DIM, height=1).pack(fill="x", pady=12)
        frow = tk.Frame(tab_video, bg=PANEL)
        frow.pack(fill="x")
        self._label(frow, "FPS MÁXIMOS", 9, True, CORAL_SOFT, PANEL).pack(side="left")
        ttk.Combobox(frow, textvariable=self.v["fps"], values=FPS_CHOICES, state="readonly", width=9,
                     font=(FONT, 10)).pack(side="left", padx=10)
        self._label(tab_video, "Limita los cuadros por segundo (se elige un formato de 30 o 60 si existe).",
                    8, False, MUTED, PANEL, wraplength=self.px(380), justify="left").pack(anchor="w", pady=(4, 0))

        # --- Escala y corte ---
        self._label(tab_scale, "RESOLUCIÓN EXACTA DE SALIDA", 9, True, CORAL_SOFT, PANEL).pack(anchor="w")
        r1 = tk.Frame(tab_scale, bg=PANEL)
        r1.pack(fill="x", pady=(6, 4))
        ttk.Combobox(r1, textvariable=self.v["scale_preset"], values=SCALE_PRESETS, state="readonly", width=14,
                     font=(FONT, 10)).pack(side="left")
        self.scale_custom_entry = ttk.Entry(r1, textvariable=self.v["scale_custom"], width=11)
        self.scale_custom_entry.pack(side="left", padx=8)
        r2 = tk.Frame(tab_scale, bg=PANEL)
        r2.pack(fill="x", pady=(0, 4))
        self._label(r2, "Modo", 9, False, MUTED, PANEL).pack(side="left")
        ttk.Combobox(r2, textvariable=self.v["scale_mode"], values=list(SCALE_MODES), state="readonly", width=20,
                     font=(FONT, 10)).pack(side="left", padx=8)
        self.v["scale_preset"].trace_add("write", lambda *_: self._sync_scale())
        self._sync_scale()
        self._label(tab_scale, "Re-codifica el video (con «Original» se usa H.264). HAP exige múltiplos de 4: "
                    "se ajusta solo.", 8, False, MUTED, PANEL, wraplength=self.px(380), justify="left").pack(anchor="w")

        tk.Frame(tab_scale, bg=CORAL_DIM, height=1).pack(fill="x", pady=12)
        self._label(tab_scale, "RECORTAR TRAMO", 9, True, CORAL_SOFT, PANEL).pack(anchor="w")
        t1 = tk.Frame(tab_scale, bg=PANEL)
        t1.pack(fill="x", pady=(6, 4))
        self._label(t1, "Inicio", 9, False, MUTED, PANEL).pack(side="left")
        ttk.Entry(t1, textvariable=self.v["trim_start"], width=9).pack(side="left", padx=(6, 14))
        self._label(t1, "Fin", 9, False, MUTED, PANEL).pack(side="left")
        ttk.Entry(t1, textvariable=self.v["trim_end"], width=9).pack(side="left", padx=6)
        self._check(tab_scale, "Corte exacto (re-codifica)", self.v["trim_exact"]).pack(anchor="w", pady=(2, 0))
        self._label(tab_scale, "Formato mm:ss u hh:mm:ss. Vacío = sin recorte (Fin vacío = hasta el final). "
                    "El nombre del archivo indica el tramo.", 8, False, MUTED, PANEL, wraplength=self.px(380),
                    justify="left").pack(anchor="w")

        self._label(tab_extra, "AUDIO", 9, True, CORAL_SOFT, PANEL).pack(anchor="w")
        self._check(tab_extra, "Descargar también solo audio", self.v["audio"]).pack(anchor="w", pady=(6, 2))
        arow = tk.Frame(tab_extra, bg=PANEL)
        arow.pack(fill="x", pady=(0, 4))
        self._label(arow, "Formato", 9, False, MUTED, PANEL).pack(side="left")
        ttk.Combobox(arow, textvariable=self.v["audio_fmt"], values=list(AUDIO_FORMATS), state="readonly", width=7,
                     font=(FONT, 10)).pack(side="left", padx=(6, 12))
        self._label(arow, "Calidad (kbps)", 9, False, MUTED, PANEL).pack(side="left")
        self.audio_q_box = ttk.Combobox(arow, textvariable=self.v["audio_q"], values=AUDIO_QUALITIES, width=5,
                                        state="readonly", font=(FONT, 10))
        self.audio_q_box.pack(side="left", padx=6)
        self.v["audio_fmt"].trace_add("write", lambda *_: self._sync_audio_quality())
        self._sync_audio_quality()

        tk.Frame(tab_extra, bg=CORAL_DIM, height=1).pack(fill="x", pady=10)
        self._label(tab_extra, "SUBTÍTULOS", 9, True, CORAL_SOFT, PANEL).pack(anchor="w")
        self._check(tab_extra, "Descargar subtítulos", self.v["subs"]).pack(anchor="w", pady=(6, 2))
        srow = tk.Frame(tab_extra, bg=PANEL)
        srow.pack(fill="x", pady=(0, 4))
        self._label(srow, "Idiomas", 9, False, MUTED, PANEL).pack(side="left")
        ttk.Entry(srow, textvariable=self.v["subs_langs"], width=10).pack(side="left", padx=(6, 12))
        ttk.Combobox(srow, textvariable=self.v["subs_mode"], values=SUBS_MODES, state="readonly", width=16,
                     font=(FONT, 10)).pack(side="left")
        self._label(tab_extra, "Incrustar solo funciona en MP4; en MOV se guarda el .srt aparte.", 8, False, MUTED,
                    PANEL, wraplength=self.px(380), justify="left").pack(anchor="w")

        tk.Frame(tab_extra, bg=CORAL_DIM, height=1).pack(fill="x", pady=10)
        self._label(tab_extra, "MINIATURA Y METADATOS", 9, True, CORAL_SOFT, PANEL).pack(anchor="w")
        self._check(tab_extra, "Incrustar miniatura y metadatos", self.v["embed"]).pack(anchor="w", pady=(6, 2))
        self._label(tab_extra, "Solo MP4, MP3 y M4A (en MOV, Opus, WAV y FLAC se ignora la miniatura).", 8, False,
                    MUTED, PANEL, wraplength=self.px(380), justify="left").pack(anchor="w")

        tk.Frame(tab_extra, bg=CORAL_DIM, height=1).pack(fill="x", pady=8)
        crow = tk.Frame(tab_extra, bg=PANEL)
        crow.pack(fill="x")
        self._label(crow, "COOKIES DEL NAVEGADOR", 9, True, CORAL_SOFT, PANEL).pack(side="left")
        ttk.Combobox(crow, textvariable=self.v["cookies"], values=COOKIE_BROWSERS, state="readonly", width=10,
                     font=(FONT, 10)).pack(side="left", padx=10)
        self.v["cookies"].trace_add("write", lambda *_: setattr(self.dl, "cookie_browser", self.v["cookies"].get()))
        self._label(tab_extra, "Si YouTube pide iniciar sesión. Firefox suele ser lo más fiable; en Chrome/Edge "
                    "recientes puede fallar la lectura.", 8, False, MUTED, PANEL, wraplength=self.px(380),
                    justify="left").pack(anchor="w", pady=(4, 0))

        # --- Cola ---
        self._label(tab_queue, "COLA DE DESCARGAS", 9, True, CORAL_SOFT, PANEL).pack(anchor="w")
        self._label(tab_queue, "Configura un video y pulsa «+ Cola». DESCARGAR procesa toda la cola.", 8, False, MUTED,
                    PANEL, wraplength=self.px(380), justify="left").pack(anchor="w", pady=(2, 6))
        qrow = tk.Frame(tab_queue, bg=PANEL)
        qrow.pack(side="bottom", fill="x", pady=(6, 0))
        self._btn(qrow, "Quitar seleccionado", self._queue_remove).pack(side="left")
        self._btn(qrow, "Vaciar", self._queue_clear).pack(side="left", padx=6)
        self.queue_list = tk.Listbox(tab_queue, bg=FIELD, fg=CORAL, selectbackground=CORAL_DIM,
                                     selectforeground="white", relief="flat", highlightthickness=0,
                                     font=(FONT, 9), activestyle="none", selectmode="extended")
        self.queue_list.pack(fill="both", expand=True)

        # ----- Panel derecho: preview -----
        right = tk.Frame(body, bg=PANEL)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        rin = tk.Frame(right, bg=PANEL)
        rin.pack(fill="both", expand=True, padx=20, pady=14)

        # Zona inferior: se empaqueta primero con side="bottom" para que SIEMPRE sea visible
        acts = tk.Frame(rin, bg=PANEL)
        acts.pack(side="bottom", fill="x")
        self.btn_dl = tk.Button(acts, text="⬇   DESCARGAR", command=self.download, relief="flat", bd=0,
                                cursor="hand2", font=(FONT, 14, "bold"), bg=CORAL, fg=BG,
                                activebackground=CORAL_SOFT, activeforeground=BG,
                                disabledforeground="#6b4757", pady=12, state="disabled")
        self.btn_dl.pack(side="left", fill="x", expand=True)
        self.btn_queue = self._btn(acts, "+ Cola", self._add_to_queue)
        self.btn_queue.config(state="disabled", pady=14)
        self.btn_queue.pack(side="left", padx=(8, 0))
        self.btn_pause = self._btn(acts, "Pausar", self._toggle_pause)
        self.btn_pause.config(state="disabled", pady=14)
        self.btn_pause.pack(side="left", padx=(8, 0))
        self.btn_cancel = self._btn(acts, "Cancelar", self._cancel)
        self.btn_cancel.config(state="disabled", pady=14)
        self.btn_cancel.pack(side="left", padx=(8, 0))
        self._update_dl_style()

        self.result_row = tk.Frame(rin, bg=PANEL)  # «Abrir carpeta» / «Copiar error»: solo cuando aplican
        self.result_row.pack(side="bottom", fill="x", pady=(0, 6))
        self.btn_open = self._btn(self.result_row, "📂  Abrir carpeta", self._open_folder)
        self.btn_copyerr = self._btn(self.result_row, "Copiar error", self._copy_error)

        self.status = tk.StringVar(value="Pega un enlace y pulsa Analizar.")
        tk.Label(rin, textvariable=self.status, bg=PANEL, fg=CORAL_SOFT, font=(FONT, 9),
                 wraplength=self.px(380), justify="left", anchor="w").pack(side="bottom", fill="x", pady=(0, 8))
        self.bar = ttk.Progressbar(rin, maximum=100, style="Coral.Horizontal.TProgressbar")
        self.bar.pack(side="bottom", fill="x", pady=(0, 6))

        # Contenedor de tamaño fijo: la miniatura nunca se encoge ni depende del largo del título
        self.thumb_box = tk.Frame(rin, bg=FIELD, height=self.thumb_h)
        self.thumb_box.pack(fill="x")
        self.thumb_box.pack_propagate(False)
        self.thumb = tk.Label(self.thumb_box, bg=FIELD, fg=MUTED, text="Vista previa", font=(FONT, 11), bd=0)
        self.thumb.place(relx=0.5, rely=0.5, anchor="center")
        self.dur_badge = self._label(self.thumb, "", 9, True, "white", "#000000", padx=6, pady=1)

        self.title_lbl = self._label(rin, "Sin video", 12, True, CORAL, PANEL, wraplength=self.px(360), justify="left",
                                     anchor="w")
        self.title_lbl.pack(anchor="w", pady=(8, 2), fill="x")
        self.chan_lbl = self._label(rin, "", 10, False, CORAL_SOFT, PANEL, anchor="w")
        self.chan_lbl.pack(fill="x")

        self.meta = {}
        grid = tk.Frame(rin, bg=PANEL)
        grid.pack(fill="x", pady=(8, 4))
        grid.columnconfigure((0, 1), weight=1, uniform="m")
        for i, key in enumerate(["Duración", "Vistas", "Publicado", "Likes", "Mejor calidad", "Resoluciones"]):
            cell = tk.Frame(grid, bg=PANEL)
            cell.grid(row=i // 2, column=i % 2, sticky="w", pady=2)
            self._label(cell, key.upper() + "  ", 8, True, MUTED, PANEL).pack(side="left")
            v = self._label(cell, "—", 10, True, CORAL, PANEL)
            v.pack(side="left")
            self.meta[key] = v

    def _show_help_menu(self) -> None:
        self.help_menu.tk_popup(self.btn_help.winfo_rootx(), self.btn_help.winfo_rooty() + self.btn_help.winfo_height())

    def _open_log(self) -> None:
        path = os.path.join(updater.DATA_DIR, "log.txt")
        if os.path.isfile(path):
            os.startfile(path)
        else:
            messagebox.showinfo("Log", "Todavía no hay registro (log.txt).")

    def _about(self) -> None:
        pend = updater.pending_update_version()
        text = f"Descargador de YouTube v{updater.VERSION}\nyt-dlp {yt_dlp.version.__version__}"
        if pend:
            text += f"\n(motor {pend} listo; se aplica al reiniciar)"
        text += f"\nMotor JavaScript: {', '.join(self.dl.js_runtimes) or 'ninguno'}"
        text += f"\nDatos: {updater.DATA_DIR}" + ("  (modo portable)" if updater.IS_PORTABLE else "")
        messagebox.showinfo("Acerca de", text)

    def _check_updates_now(self) -> None:
        self.status.set("Buscando actualizaciones…")

        def work():
            try:
                upd = updater.check_app_update()
                v = updater.background_ytdlp_update(force=True)
                if v:
                    self.q.put(("engine", v))
                if upd:
                    self.q.put(("app_update", upd))
                elif v:
                    self.q.put(("msgbox", "Actualizaciones", f"Motor yt-dlp {v} descargado (se aplica al reiniciar)."))
                else:
                    self.q.put(("msgbox", "Actualizaciones", "Todo está al día."))
            except Exception as e:  # noqa: BLE001
                log.warning("Búsqueda manual de actualizaciones fallida", exc_info=True)
                self.q.put(("msgbox", "Actualizaciones", f"No se pudo comprobar: {e}"))
        threading.Thread(target=work, daemon=True).start()

    def _redetect_gpu(self) -> None:
        self.status.set("Probando encoders de GPU…")
        threading.Thread(target=self._gpu_worker, args=(True,), daemon=True).start()

    def _reset_engine(self) -> None:
        if messagebox.askyesno("Restaurar motor", "Se borrará el yt-dlp descargado y se volverá al incluido en la "
                               "app.\nSe aplica al reiniciar. ¿Continuar?"):
            updater.reset_ytdlp_engine()
            self.engine_lbl.config(text="Motor restaurado (se aplica al reiniciar)")

    def _open_folder(self) -> None:
        path = self.out_dir.get()
        if os.path.isdir(path):
            os.startfile(path)

    def _copy_error(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.dl.last_error)
        self.status.set("Error copiado al portapapeles.")

    def _show_result_buttons(self, ok: bool, has_error: bool) -> None:
        for b in (self.btn_open, self.btn_copyerr):
            b.pack_forget()
        if ok:
            self.btn_open.pack(side="left")
        if has_error:
            self.btn_copyerr.pack(side="left", padx=(8 if ok else 0, 0))

    def _update_dl_style(self):
        if str(self.btn_dl["state"]) == "disabled":
            self.btn_dl.config(bg=FIELD)
        else:
            self.btn_dl.config(bg=CORAL)

    def _set_dl(self, enabled):
        self.btn_dl.config(state="normal" if enabled else "disabled")
        self._update_dl_style()

    def _refresh_dl(self):
        """DESCARGAR: activo si no hay trabajo en curso y hay algo que descargar (URL analizada o cola)."""
        n = len(self.queue_items)
        self.btn_dl.config(text=f"⬇   DESCARGAR COLA ({n})" if n else "⬇   DESCARGAR")
        self._set_dl(not self.busy and (n > 0 or self._url_matches()))
        self.btn_queue.config(state="normal" if (not self.busy and self._url_matches()) else "disabled")

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.out_dir.get())
        if d:
            self.out_dir.set(d)

    def _set_all(self, v):
        for var in self.res_vars.values():
            var.set(v)

    def _show_resolutions(self, heights, hint=None):
        for w in self.res_frame.winfo_children():
            w.destroy()
        self.res_vars = {}
        if not heights:
            self._label(self.res_frame, "No se encontraron resoluciones.\nRevisa el mensaje de estado.", 10, False,
                        MUTED, PANEL, justify="left").pack(anchor="w")
            return
        sel = set(pick_heights(heights, self.pending_heights)) if self.pending_heights is not None else {heights[0]}
        self.pending_heights = None  # un preset solo afecta al análisis siguiente
        for i, h in enumerate(heights):
            var = tk.BooleanVar(value=(h in sel))
            self.res_vars[h] = var
            label = f"{h}p"
            if h >= 4320:
                label += " 8K"
            elif h >= 2160:
                label += " 4K"
            elif h >= 1080:
                label += " HD"
            tk.Checkbutton(self.res_frame, text=label, variable=var, indicatoron=False,
                           bg=FIELD, fg=CORAL, selectcolor=CORAL, activebackground=CORAL_DIM,
                           activeforeground="white", font=(FONT, 10, "bold"), relief="flat", bd=0,
                           highlightthickness=0, cursor="hand2", width=9, pady=7,
                           command=self._refresh_chips).grid(row=i // 3, column=i % 3, padx=4, pady=4, sticky="w")
        self._refresh_chips()

    def _refresh_chips(self):
        # El texto de un chip seleccionado pasa a oscuro para contrastar con el fondo coral
        for w in self.res_frame.winfo_children():
            if isinstance(w, tk.Checkbutton):
                sel = w.getvar(str(w.cget("variable")))
                w.config(fg=BG if str(sel) in ("1", "True") else CORAL)

    # ---------- Análisis ----------
    def _url_matches(self) -> bool:
        return self.analyzed_url is not None and self.url_var.get().strip() == self.analyzed_url

    def _on_url_edit(self, *_) -> None:
        """Si se edita la URL después de analizar, DESCARGAR queda bloqueado hasta volver a analizar."""
        if self.analyzed_url is None or self.busy:
            return
        if not self._url_matches():
            self.status.set("La URL cambió. Vuelve a pulsar Analizar." + (
                "  (DESCARGAR procesará la cola.)" if self.queue_items else ""))
        self._refresh_dl()

    def _ask_playlist_choice(self):
        """¿Solo este video o toda la lista? Devuelve "video", "list" o None (cancelar)."""
        result = {"v": None}
        dlg = tk.Toplevel(self, bg=PANEL)
        dlg.title("Enlace con lista")
        dlg.resizable(False, False)
        dlg.transient(self)
        try:
            dlg.iconbitmap(os.path.join(RES_DIR, "icon.ico"))
        except Exception:  # noqa: BLE001
            pass
        box = tk.Frame(dlg, bg=PANEL)
        box.pack(padx=24, pady=20)
        self._label(box, "Este enlace es de un video dentro de una lista.", 11, True, CORAL, PANEL).pack(anchor="w")
        self._label(box, "¿Descargar solo este video o toda la lista?", 10, False, CORAL_SOFT, PANEL
                    ).pack(anchor="w", pady=(4, 14))
        row = tk.Frame(box, bg=PANEL)
        row.pack(fill="x")

        def pick(v):
            result["v"] = v
            dlg.destroy()
        self._btn(row, "Solo este video", lambda: pick("video"), solid=True).pack(side="left")
        self._btn(row, "Toda la lista", lambda: pick("list")).pack(side="left", padx=8)
        self._btn(row, "Cancelar", lambda: pick(None)).pack(side="left")
        dlg.protocol("WM_DELETE_WINDOW", lambda: pick(None))
        dlg.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - dlg.winfo_reqwidth()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - dlg.winfo_reqheight()) // 2
        dlg.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dlg.grab_set()
        self.wait_window(dlg)
        return result["v"]

    def analyze(self) -> None:
        url = self.url_var.get().strip()
        if not url or self.busy:
            return
        choice = None
        if has_video_and_list(url):
            choice = self._ask_playlist_choice()
            if choice is None:
                return
        self.busy = True
        self.analyzed_url = None
        self.btn_an.config(state="disabled")
        self._set_dl(False)
        self.status.set("Analizando…")
        threading.Thread(target=self._analyze_worker, args=(url, choice), daemon=True).start()

    def _analyze_worker(self, url, choice):
        try:
            self.dl.ytlog.last_warning = None
            opts = {**self.dl.ydl_base(), "extract_flat": "in_playlist", "noplaylist": choice == "video"}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            is_pl = info.get("_type") == "playlist"
            if is_pl:
                heights = PLAYLIST_HEIGHTS
                entries = [e for e in (info.get("entries") or []) if e]
                thumb_url = info.get("thumbnail") or next(
                    (t["url"] for e in entries for t in (e.get("thumbnails") or [])[-1:]), None)
            else:
                heights = sorted(
                    {f["height"] for f in info.get("formats", [])
                     if f.get("vcodec") not in (None, "none") and f.get("height")}, reverse=True)
                thumb_url = info.get("thumbnail")
            data = None
            if thumb_url:
                try:
                    req = urllib.request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
                    data = urllib.request.urlopen(req, timeout=15).read()
                except Exception:  # noqa: BLE001
                    data = None
            fps = max((f.get("fps") or 0 for f in info.get("formats", []) or []), default=0)
            self.q.put(("analyzed", url, choice, info, is_pl, heights, data, fps))
        except Exception as e:  # noqa: BLE001
            log.exception("Error al analizar %s", url)
            self.dl.last_error = f"Al analizar {url}\n{traceback.format_exc()}"
            self.q.put(("error", friendly_error(str(e), self.dl.cookie_browser)))

    def _apply_info(self, url, choice, info, is_pl, heights, data, fps):
        self.is_playlist = is_pl
        self.analyzed_url = url
        self.playlist_choice = choice
        self.analyzed_info = None if is_pl else info
        self.analyzed_at = time.time()
        self.analyzed_duration = None if is_pl else info.get("duration")
        title = info.get("title") or "Sin título"
        self.title_lbl.config(text=title if len(title) <= 80 else title[:79].rstrip() + "…")
        if is_pl:
            n = len(info.get("entries") or [])
            self.chan_lbl.config(text=info.get("uploader") or info.get("channel") or "Playlist")
            vals = {"Duración": f"{n} videos", "Vistas": "—", "Publicado": "—",
                    "Mejor calidad": "Hasta " + f"{max(heights)}p", "Resoluciones": "Playlist", "Likes": "—"}
            self.dur_badge.place_forget()
        else:
            self.chan_lbl.config(text=info.get("uploader") or info.get("channel") or "")
            best = f"{max(heights)}p" + (f" · {int(fps)}fps" if fps else "") if heights else "—"
            vals = {"Duración": fmt_dur(info.get("duration")), "Vistas": fmt_num(info.get("view_count")),
                    "Publicado": fmt_date(info.get("upload_date")), "Mejor calidad": best,
                    "Resoluciones": str(len(heights)), "Likes": fmt_num(info.get("like_count"))}
            self.dur_badge.config(text=fmt_dur(info.get("duration")))
            self.dur_badge.place(relx=1.0, rely=1.0, x=-8, y=-8, anchor="se")
        for k, v in vals.items():
            self.meta[k].config(text=v)
        self._set_thumbnail(data)
        hint = None if is_pl else diagnose_formats(heights, self.dl.ytlog.last_warning, bool(self.dl.js_runtimes))
        self._show_resolutions(heights, hint)
        if is_pl:
            self.status.set("Playlist: se usará la mejor calidad hasta la resolución elegida.")
        else:
            self.status.set(hint or f"{len(heights)} resoluciones disponibles. Elige y descarga.")

    def _set_thumbnail(self, data):
        """Muestra la miniatura recortada a 16:9; si no hay o falla, vuelve al marcador."""
        try:
            if not data:
                raise ValueError("sin miniatura")
            img = ImageOps.fit(Image.open(io.BytesIO(data)).convert("RGB"), (self.thumb_w, self.thumb_h))
            self.thumb_img = ImageTk.PhotoImage(img)
            self.thumb.config(image=self.thumb_img, text="", width=self.thumb_w, height=self.thumb_h)
        except Exception:  # noqa: BLE001
            self.thumb_img = None
            self.thumb.config(image="", text="Sin vista previa", width=0, height=0)
            self.dur_badge.place_forget()

    # ---------- Descarga ----------
    def _collect_spec(self) -> dict:
        """Lee la interfaz y devuelve las opciones del trabajo (un dict simple, apto para la cola y los presets)."""
        v = {k: var.get() for k, var in self.v.items()}
        kind = OUT_FORMATS[self.fmt_var.get()]
        scale, notes = resolve_scale(v["scale_preset"], v["scale_custom"], v["scale_mode"], kind)
        if scale and kind == "original":
            kind = "h264"
            notes.append("Con escala, el formato «Original» se convierte a H.264.")
        trim = validate_trim(v["trim_start"], v["trim_end"], self.analyzed_duration, v["trim_exact"])
        return {
            "scale": scale, "trim": trim, "notes": notes,
            "fps": int(v["fps"]) if str(v["fps"]).isdigit() else None,
            "out_dir": self.out_dir.get(),
            "kind": kind,
            "heights": [h for h, var in self.res_vars.items() if var.get()],
            "audio": bool(v["audio"]), "audio_fmt": v["audio_fmt"], "audio_q": v["audio_q"],
            "subs": bool(v["subs"]), "subs_langs": parse_langs(v["subs_langs"]),
            "subs_mode": "embed" if str(v["subs_mode"]).startswith("Incrustar") else "srt",
            "embed": bool(v["embed"]),
        }

    def _current_item(self):
        """Ítem de descarga con lo configurado ahora, o None (avisando al usuario) si no se puede."""
        if not self._url_matches():
            self.status.set("La URL cambió. Vuelve a pulsar Analizar.")
            self._refresh_dl()
            return None
        try:
            spec = self._collect_spec()
        except ValueError as e:
            messagebox.showwarning("Revisa las opciones", str(e))
            return None
        if not spec["heights"] and not spec["audio"]:
            messagebox.showwarning("Nada seleccionado", "Marca al menos una resolución o el audio.")
            return None
        os.makedirs(spec["out_dir"], exist_ok=True)
        return {"url": self.analyzed_url, "is_playlist": self.is_playlist, "info": self.analyzed_info,
                "analyzed_at": self.analyzed_at, "title": self.title_lbl.cget("text"), "spec": spec}

    def download(self) -> None:
        if self.busy:
            return
        if self.queue_items:  # con cola, DESCARGAR procesa la cola
            self._start_download(list(self.queue_items), from_queue=True)
            return
        item = self._current_item()
        if item:
            self._start_download([item])

    # ---------- Cola ----------
    @staticmethod
    def _queue_text(it):
        sp = it["spec"]
        what = [f"{h}p" for h in sp["heights"]] + ([sp["audio_fmt"]] if sp["audio"] else [])
        return f"{short_title(it['title'], 34)} · {', '.join(what)} · {sp['kind']}"

    def _refresh_queue(self):
        self.queue_list.delete(0, "end")
        for it in self.queue_items:
            self.queue_list.insert("end", self._queue_text(it))
        self._refresh_dl()

    def _add_to_queue(self):
        if self.busy:
            return
        item = self._current_item()
        if item:
            self.queue_items.append(item)
            self._refresh_queue()
            self.status.set(f"Añadido a la cola ({len(self.queue_items)}). Puedes analizar otro enlace.")

    def _queue_remove(self):
        if self.busy:
            return
        for i in sorted(self.queue_list.curselection(), reverse=True):
            del self.queue_items[i]
        self._refresh_queue()

    def _queue_clear(self):
        if not self.busy:
            self.queue_items.clear()
            self._refresh_queue()

    # ---------- Pausa ----------
    def _toggle_pause(self):
        if not self.busy:
            return
        self.dl.paused = not self.dl.paused
        self.btn_pause.config(text="Reanudar" if self.dl.paused else "Pausar")
        if self.dl.paused:
            self.status.set("Pausando… (se detiene en cuanto llegue el siguiente bloque de datos)")

    def _start_download(self, items, from_queue=False):
        self.busy = True
        self.dl.cancel = False
        self.dl.paused = False
        self._running_queue = from_queue
        self.dl.last_error = ""
        self._show_result_buttons(False, False)
        self._save_settings()
        self._refresh_dl()
        self.btn_an.config(state="disabled")
        self.btn_pause.config(state="normal", text="Pausar")
        self.btn_cancel.config(state="normal")
        threading.Thread(target=self.dl.run, args=(items,), daemon=True).start()

    def _cancel(self):
        self.dl.cancel = True
        self.status.set("Cancelando…")

    # ---------- GPU ----------
    def _gpu_worker(self, force=False):
        try:
            self.q.put(("gpu", detect_gpu_encoders(force), force))
        except Exception:  # noqa: BLE001
            log.warning("No se pudo detectar la GPU", exc_info=True)

    def _apply_gpu(self, gpu, announce=False):
        added = register_gpu_formats(gpu)
        self.fmt_box.config(values=list(OUT_FORMATS))
        if OUT_FORMATS.get(self.fmt_var.get()) is None:  # la opción elegida (GPU) ya no existe
            self.fmt_var.set(next(iter(OUT_FORMATS)))
        elif self._saved_fmt in GPU_TABLE and not self._fmt_restored:  # ajuste guardado de GPU, ya detectada
            lbl = next((k for k, v in OUT_FORMATS.items() if v == self._saved_fmt), None)
            if lbl:
                self.fmt_var.set(lbl)
        self._fmt_restored = True
        if announce:
            self.status.set("GPU detectada: " + ", ".join(gpu.values()) if gpu else
                            "No se encontró ningún encoder de GPU que funcione.")
        elif added:
            log.info("Encoders GPU disponibles: %s", ", ".join(gpu.values()))

    # ---------- Motor yt-dlp en segundo plano ----------
    def _engine_update_worker(self):
        try:
            v = updater.background_ytdlp_update()
            if v:
                self.q.put(("engine", v))
        except Exception:  # noqa: BLE001
            log.warning("Fallo al actualizar el motor", exc_info=True)

    # ---------- Actualización de la app ----------
    def _check_update_worker(self):
        try:
            upd = updater.check_app_update()
            if upd:
                self.q.put(("app_update", upd))
        except Exception:  # noqa: BLE001
            pass  # sin internet: se ignora en silencio

    def _show_update_dialog(self, upd):
        dlg = tk.Toplevel(self, bg=PANEL)
        dlg.title("Actualización disponible")
        dlg.resizable(False, False)
        dlg.transient(self)
        try:
            dlg.iconbitmap(os.path.join(RES_DIR, "icon.ico"))
        except Exception:  # noqa: BLE001
            pass
        w, h = self.px(460), self.px(330)
        x = self.winfo_rootx() + (self.winfo_width() - w) // 2
        y = self.winfo_rooty() + (self.winfo_height() - h) // 2
        dlg.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")
        box = tk.Frame(dlg, bg=PANEL)
        box.pack(fill="both", expand=True, padx=24, pady=20)
        self._label(box, "¡Hay una nueva versión!", 15, True, CORAL, PANEL).pack(anchor="w")
        self._label(box, f"Versión instalada: {updater.VERSION}      Nueva: {upd['version']}", 10, False,
                    CORAL_SOFT, PANEL).pack(anchor="w", pady=(4, 10))
        notes = tk.Text(box, height=7, bg=FIELD, fg=CORAL, relief="flat", font=(FONT, 9), wrap="word",
                        highlightthickness=0, padx=8, pady=8)
        notes.insert("1.0", upd["notes"] or "Mejoras y correcciones.")
        notes.config(state="disabled")
        notes.pack(fill="x")
        bar = ttk.Progressbar(box, maximum=100, style="Coral.Horizontal.TProgressbar")
        msg = tk.StringVar(value="La app se cerrará y se reabrirá sola al terminar.")
        tk.Label(box, textvariable=msg, bg=PANEL, fg=CORAL_SOFT, font=(FONT, 9)).pack(anchor="w", pady=(10, 0))
        row = tk.Frame(box, bg=PANEL)
        row.pack(side="bottom", fill="x")
        bar.pack(side="bottom", fill="x", pady=(0, 10))

        def start():
            btn_ok.config(state="disabled")
            btn_later.config(state="disabled")
            msg.set("Descargando actualización…")

            def work():
                try:
                    path = updater.download_installer(upd, lambda p: self.q.put(("upd_progress", bar, p)))
                    self.q.put(("upd_run", path))
                except Exception as e:  # noqa: BLE001
                    self.q.put(("upd_fail", dlg, msg, btn_ok, btn_later, str(e)))
            threading.Thread(target=work, daemon=True).start()

        btn_ok = tk.Button(row, text="Actualizar ahora", command=start, relief="flat", bd=0, cursor="hand2",
                           font=(FONT, 11, "bold"), bg=CORAL, fg=BG, activebackground=CORAL_SOFT,
                           activeforeground=BG, disabledforeground="#6b4757", padx=16, pady=9)
        btn_ok.pack(side="left", fill="x", expand=True)
        btn_later = self._btn(row, "Más tarde", dlg.destroy)
        btn_later.config(pady=11)
        btn_later.pack(side="left", padx=(8, 0))
        dlg.grab_set()

    # ---------- Cola de eventos ----------
    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "analyzed":
                    self._apply_info(*msg[1:])
                    self.busy = False
                    self.btn_an.config(state="normal")
                    self._refresh_dl()
                elif kind == "gpu":
                    self._apply_gpu(msg[1], msg[2])
                elif kind == "engine":
                    self.engine_lbl.config(text="Motor actualizado (se aplica al reiniciar)")
                elif kind == "app_update":
                    if updater.IS_PORTABLE:  # el instalador no sirve para la versión portable
                        self.engine_lbl.config(text=f"Nueva versión {msg[1]['version']}: descarga el .zip portable")
                    else:
                        self._show_update_dialog(msg[1])
                elif kind == "upd_progress":
                    msg[1]["value"] = msg[2]
                elif kind == "upd_run":
                    updater.run_installer(msg[1])
                    self.destroy()
                    return
                elif kind == "upd_fail":
                    _, dlg, m, b1, b2, err = msg
                    m.set("No se pudo actualizar: " + err[:120])
                    b1.config(state="normal", text="Reintentar")
                    b2.config(state="normal")
                elif kind == "error":
                    self.busy = False
                    self.btn_an.config(state="normal")
                    self._refresh_dl()
                    self.status.set("Error: " + msg[1][:300])
                    self._show_result_buttons(False, True)
                elif kind == "progress":
                    self.bar["value"] = msg[1]
                    self.status.set(msg[2])
                elif kind == "status":
                    self.status.set(msg[1])
                elif kind == "msgbox":
                    messagebox.showinfo(msg[1], msg[2])
                elif kind == "done":
                    self.busy = False
                    self.bar["value"] = 0
                    self.btn_an.config(state="normal")
                    self.btn_cancel.config(state="disabled")
                    self.btn_pause.config(state="disabled", text="Pausar")
                    self.dl.paused = False
                    if self._running_queue and not self.dl.cancel:  # cola terminada: quedan solo los que fallaron
                        self.queue_items[:] = [it for it in self.queue_items
                                               if any(it is f for f in self.dl.failed_items)]
                        self._refresh_queue()
                    self._running_queue = False
                    self._refresh_dl()
                    self.status.set(msg[1])
                    self._show_result_buttons(msg[2], bool(self.dl.last_error))
        except queue.Empty:
            pass
        except Exception:  # noqa: BLE001  un mensaje con error no debe detener para siempre la cola de eventos
            log.exception("Error al procesar un evento de la interfaz")
            self.busy = False
            self.btn_an.config(state="normal")
            self._refresh_dl()
            self.status.set("Error interno (ver el log).")
        self.after(100, self._poll)
