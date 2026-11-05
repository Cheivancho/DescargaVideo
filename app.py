"""Descargador de YouTube con interfaz oscura (tkinter + yt-dlp).

- Detecta todas las resoluciones realmente disponibles del video.
- Descarga una, varias o todas; soporta playlists y audio MP3.
- Panel derecho con miniatura y características del video.
Requiere: yt-dlp, Pillow y ffmpeg (en el PATH o junto al ejecutable).
"""
import io
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
import urllib.request
from tkinter import filedialog, messagebox, ttk

import updater

updater.prepare_ytdlp()  # actualiza yt-dlp si hay versión nueva (debe ir antes de importarlo)

import yt_dlp  # noqa: E402
from PIL import Image, ImageOps, ImageTk  # noqa: E402

# Permite usar el ffmpeg.exe que esté junto al ejecutable
_APP_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
os.environ["PATH"] = _APP_DIR + os.pathsep + os.environ.get("PATH", "")

_RES_DIR = getattr(sys, "_MEIPASS", _APP_DIR)

OUT_FORMATS = {
    "H.264 + AAC (MP4, ligero y compatible)": "h264",
    "ProRes 422 HQ (MOV, para Media Encoder / edición)": "prores",
    "HAP (MOV, para Resolume)": "hap",
}

PLAYLIST_HEIGHTS = [2160, 1440, 1080, 720, 480, 360, 240, 144]

# Paleta
BG = "#121216"
PANEL = "#1b1b22"
FIELD = "#24242d"
CORAL = "#F22E62"
CORAL_DIM = "#a51f43"
CORAL_SOFT = "#f77a99"
MUTED = "#a0607a"
FONT = "Segoe UI"

THUMB_W, THUMB_H = 320, 180


def fmt_num(n):
    if n is None:
        return "—"
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= div:
            return f"{n / div:.1f}{unit}".replace(".0", "")
    return str(n)


def fmt_date(s):
    return f"{s[6:8]}/{s[4:6]}/{s[0:4]}" if s and len(s) == 8 else "—"


def fmt_dur(sec):
    if not sec:
        return "—"
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Descargador de YouTube")
        self.geometry("1020x640")
        self.minsize(960, 640)
        self.configure(bg=BG)
        try:
            self.iconbitmap(os.path.join(_RES_DIR, "icon.ico"))
        except Exception:  # noqa: BLE001
            pass
        self.q = queue.Queue()
        self.is_playlist = False
        self.res_vars = {}
        self.busy = False
        self._out_fmt = "h264"
        self.cancel = False
        self.thumb_img = None
        self.out_dir = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Videos", "YouTube"))
        self._styles()
        self._build()
        self.after(100, self._poll)
        self.after(1200, lambda: threading.Thread(target=self._check_update_worker, daemon=True).start())

    # ---------- Estilos ----------
    def _styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TEntry", fieldbackground=FIELD, foreground=CORAL, insertcolor=CORAL,
                    bordercolor=CORAL_DIM, lightcolor=FIELD, darkcolor=FIELD, padding=8)
        s.map("TEntry", bordercolor=[("focus", CORAL)])
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

    def _label(self, parent, text="", size=10, bold=False, color=CORAL, bg=BG, **kw):
        return tk.Label(parent, text=text, bg=bg, fg=color, font=(FONT, size, "bold" if bold else "normal"), **kw)

    # ---------- UI ----------
    def _build(self):
        # Cabecera
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=24, pady=(20, 8))
        self._label(head, "▶  Descargador de YouTube", 18, True).pack(side="left")
        self._label(head, f"v{updater.VERSION}", 9, False, MUTED).pack(side="left", padx=(10, 0), pady=(8, 0))

        # Barra de URL
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=24, pady=(4, 14))
        self.url = ttk.Entry(bar, font=(FONT, 11))
        self.url.pack(side="left", fill="x", expand=True, ipady=3)
        self.url.bind("<Return>", lambda e: self.analyze())
        self.btn_an = self._btn(bar, "Analizar", self.analyze)
        self.btn_an.pack(side="left", padx=(10, 0))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        body.columnconfigure(0, weight=1, uniform="c")
        body.columnconfigure(1, weight=1, uniform="c")
        body.rowconfigure(0, weight=1)

        # ----- Panel izquierdo: opciones -----
        left = tk.Frame(body, bg=PANEL)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        inner = tk.Frame(left, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=20, pady=18)

        self._label(inner, "RESOLUCIONES", 9, True, CORAL_SOFT, PANEL).pack(anchor="w")
        row = tk.Frame(inner, bg=PANEL)
        row.pack(fill="x", pady=(6, 8))
        self._btn(row, "Todas", lambda: self._set_all(True)).pack(side="left")
        self._btn(row, "Ninguna", lambda: self._set_all(False)).pack(side="left", padx=6)

        self.res_frame = tk.Frame(inner, bg=PANEL)
        self.res_frame.pack(fill="x")
        self.res_hint = self._label(self.res_frame, "Analiza un enlace para ver\nlas resoluciones disponibles.",
                                    10, False, MUTED, PANEL, justify="left")
        self.res_hint.pack(anchor="w", pady=10)

        tk.Frame(inner, bg=CORAL_DIM, height=1).pack(fill="x", pady=16)

        self._label(inner, "FORMATO DE SALIDA", 9, True, CORAL_SOFT, PANEL).pack(anchor="w")
        self.fmt_var = tk.StringVar(value=next(iter(OUT_FORMATS)))
        ttk.Combobox(inner, textvariable=self.fmt_var, values=list(OUT_FORMATS), state="readonly",
                     font=(FONT, 10)).pack(fill="x", pady=(6, 0))
        self._label(inner, "ProRes y HAP generan archivos muy pesados (varios GB por minuto en 4K).",
                    8, False, MUTED, PANEL).pack(anchor="w", pady=(4, 0))

        tk.Frame(inner, bg=CORAL_DIM, height=1).pack(fill="x", pady=16)

        self._label(inner, "EXTRAS", 9, True, CORAL_SOFT, PANEL).pack(anchor="w")
        self.audio_var = tk.BooleanVar(value=False)
        tk.Checkbutton(inner, text="  Descargar también solo audio (MP3)", variable=self.audio_var,
                       bg=PANEL, fg=CORAL, activebackground=PANEL, activeforeground=CORAL_SOFT,
                       selectcolor=FIELD, font=(FONT, 10), bd=0, highlightthickness=0,
                       cursor="hand2").pack(anchor="w", pady=8)

        tk.Frame(inner, bg=CORAL_DIM, height=1).pack(fill="x", pady=10)

        self._label(inner, "CARPETA DE DESTINO", 9, True, CORAL_SOFT, PANEL).pack(anchor="w", pady=(0, 6))
        dest = tk.Frame(inner, bg=PANEL)
        dest.pack(fill="x")
        ttk.Entry(dest, textvariable=self.out_dir).pack(side="left", fill="x", expand=True)
        self._btn(dest, "…", self._browse).pack(side="left", padx=(8, 0))

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
        self.btn_cancel = self._btn(acts, "Cancelar", self._cancel)
        self.btn_cancel.config(state="disabled", pady=14)
        self.btn_cancel.pack(side="left", padx=(8, 0))
        self._update_dl_style()

        self.status = tk.StringVar(value="Pega un enlace y pulsa Analizar.")
        tk.Label(rin, textvariable=self.status, bg=PANEL, fg=CORAL_SOFT, font=(FONT, 9),
                 wraplength=380, justify="left", anchor="w").pack(side="bottom", fill="x", pady=(0, 8))
        self.bar = ttk.Progressbar(rin, maximum=100, style="Coral.Horizontal.TProgressbar")
        self.bar.pack(side="bottom", fill="x", pady=(0, 6))

        # Contenedor de tamaño fijo: la miniatura nunca se encoge ni depende del largo del título
        self.thumb_box = tk.Frame(rin, bg=FIELD, height=THUMB_H)
        self.thumb_box.pack(fill="x")
        self.thumb_box.pack_propagate(False)
        self.thumb = tk.Label(self.thumb_box, bg=FIELD, fg=MUTED, text="Vista previa", font=(FONT, 11), bd=0)
        self.thumb.place(relx=0.5, rely=0.5, anchor="center")
        self.dur_badge = self._label(self.thumb, "", 9, True, "white", "#000000", padx=6, pady=1)

        self.title_lbl = self._label(rin, "Sin video", 12, True, CORAL, PANEL, wraplength=360, justify="left",
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

    def _update_dl_style(self):
        if str(self.btn_dl["state"]) == "disabled":
            self.btn_dl.config(bg=FIELD)
        else:
            self.btn_dl.config(bg=CORAL)

    def _set_dl(self, enabled):
        self.btn_dl.config(state="normal" if enabled else "disabled")
        self._update_dl_style()

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.out_dir.get())
        if d:
            self.out_dir.set(d)

    def _set_all(self, v):
        for var in self.res_vars.values():
            var.set(v)

    def _show_resolutions(self, heights):
        for w in self.res_frame.winfo_children():
            w.destroy()
        self.res_vars = {}
        if not heights:
            self._label(self.res_frame, "No se encontraron resoluciones.", 10, False, MUTED, PANEL).pack(anchor="w")
            return
        for i, h in enumerate(heights):
            var = tk.BooleanVar(value=(i == 0))
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
    def analyze(self):
        url = self.url.get().strip()
        if not url or self.busy:
            return
        self.busy = True
        self.btn_an.config(state="disabled")
        self._set_dl(False)
        self.status.set("Analizando…")
        threading.Thread(target=self._analyze_worker, args=(url,), daemon=True).start()

    def _analyze_worker(self, url):
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": "in_playlist"}) as ydl:
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
            self.q.put(("analyzed", info, is_pl, heights, data, fps))
        except Exception as e:  # noqa: BLE001
            self.q.put(("error", str(e)))

    def _apply_info(self, info, is_pl, heights, data, fps):
        self.is_playlist = is_pl
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
        self._show_resolutions(heights)
        self.status.set("Playlist: se usará la mejor calidad hasta la resolución elegida."
                        if is_pl else f"{len(heights)} resoluciones disponibles. Elige y descarga.")

    def _set_thumbnail(self, data):
        """Muestra la miniatura recortada a 16:9; si no hay o falla, vuelve al marcador."""
        try:
            if not data:
                raise ValueError("sin miniatura")
            img = ImageOps.fit(Image.open(io.BytesIO(data)).convert("RGB"), (THUMB_W, THUMB_H))
            self.thumb_img = ImageTk.PhotoImage(img)
            self.thumb.config(image=self.thumb_img, text="", width=THUMB_W, height=THUMB_H)
        except Exception:  # noqa: BLE001
            self.thumb_img = None
            self.thumb.config(image="", text="Sin vista previa", width=0, height=0)
            self.dur_badge.place_forget()

    # ---------- Descarga ----------
    def download(self):
        if self.busy:
            return
        heights = [h for h, v in self.res_vars.items() if v.get()]
        want_audio = self.audio_var.get()
        if not heights and not want_audio:
            messagebox.showwarning("Nada seleccionado", "Marca al menos una resolución o el audio MP3.")
            return
        self._out_fmt = OUT_FORMATS[self.fmt_var.get()]
        os.makedirs(self.out_dir.get(), exist_ok=True)
        self.busy = True
        self.cancel = False
        self._set_dl(False)
        self.btn_an.config(state="disabled")
        self.btn_cancel.config(state="normal")
        threading.Thread(target=self._download_worker,
                         args=(self.url.get().strip(), heights, want_audio), daemon=True).start()

    def _cancel(self):
        self.cancel = True
        self.status.set("Cancelando…")

    def _hook(self, d):
        if self.cancel:
            raise yt_dlp.utils.DownloadCancelled("Cancelado por el usuario")
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                self.q.put(("progress", d["downloaded_bytes"] * 100 / total,
                            f"Descargando… {d.get('_percent_str', '').strip()}  {d.get('_speed_str', '').strip()}  "
                            f"ETA {d.get('_eta_str', '').strip()}"))
        elif d["status"] == "finished":
            self.q.put(("progress", 100, "Procesando con ffmpeg…"))

    def _ensure_compatible(self, path):
        """Convierte el video descargado al formato de salida elegido.

        H.264: solo recodifica lo necesario (video VP9/AV1 y/o audio Opus).
        ProRes / HAP: recodifica siempre, genera un .mov y borra el .mp4 intermedio.
        """
        if not path or not path.lower().endswith(".mp4") or not os.path.isfile(path):
            return
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        kind = self._out_fmt
        if kind == "h264":
            try:
                info = subprocess.run(["ffmpeg", "-hide_banner", "-i", path], capture_output=True,
                                      text=True, encoding="utf-8", errors="replace",
                                      creationflags=flags).stderr
            except OSError:
                return
            vid = re.search(r"Stream #.*Video: (\w+)", info)
            aud = re.search(r"Stream #.*Audio: (\w+)", info)
            v_ok = bool(vid) and vid.group(1) == "h264"
            a_ok = (not aud) or aud.group(1) == "aac"
            if v_ok and a_ok:
                return
            dest = path[:-4] + ".compat.mp4"
            vcodec = ["-c:v", "copy"] if v_ok else ["-c:v", "libx264", "-crf", "17", "-preset", "medium",
                                                     "-pix_fmt", "yuv420p"]
            acodec = ["-c:a", "copy"] if a_ok else ["-c:a", "aac", "-b:a", "320k"]
            extra = ["-movflags", "+faststart"]
            label = "H.264 + AAC"
        else:
            dest = path[:-4] + ".mov"
            if kind == "prores":
                vcodec = ["-c:v", "prores_ks", "-profile:v", "3", "-vendor", "apl0",
                          "-pix_fmt", "yuv422p10le"]
                label = "ProRes 422 HQ"
            else:
                vcodec = ["-c:v", "hap", "-format", "hap"]
                label = "HAP"
            acodec = ["-c:a", "pcm_s16le"]
            extra = []
        self.q.put(("status", f"Convirtiendo a {label} (puede tardar)…"))
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", path, "-map", "0:v:0", "-map", "0:a?"]
        cmd += vcodec + acodec + extra + [dest]
        if subprocess.run(cmd, creationflags=flags).returncode != 0:
            if os.path.exists(dest):
                os.remove(dest)
            self.q.put(("status", f"No se pudo convertir a {label}; se conserva el MP4 original."))
            return
        if kind == "h264":
            os.replace(dest, path)
        else:
            os.remove(path)

    def _download_worker(self, url, heights, want_audio):
        out = self.out_dir.get()
        base = {"quiet": True, "no_warnings": True, "progress_hooks": [self._hook],
                "ignoreerrors": False, "noplaylist": not self.is_playlist}
        vbase = {**base, "post_hooks": [self._ensure_compatible]}
        jobs = []
        for h in heights:
            if self.is_playlist:
                fmt = (f"bestvideo[height<={h}][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
                       f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best")
                tmpl = "%(playlist_title)s/%(playlist_index)03d - %(title)s [" + str(h) + "p].%(ext)s"
            else:
                fmt = (f"bestvideo[height={h}][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
                       f"bestvideo[height={h}]+bestaudio/best[height={h}]")
                tmpl = "%(title)s [" + str(h) + "p].%(ext)s"
            jobs.append((f"{h}p", {**vbase, "format": fmt, "merge_output_format": "mp4",
                                   "outtmpl": os.path.join(out, tmpl)}))
        if want_audio:
            tmpl = ("%(playlist_title)s/%(playlist_index)03d - %(title)s.%(ext)s"
                    if self.is_playlist else "%(title)s.%(ext)s")
            jobs.append(("MP3", {**base, "format": "bestaudio/best", "outtmpl": os.path.join(out, tmpl),
                                 "postprocessors": [{"key": "FFmpegExtractAudio",
                                                     "preferredcodec": "mp3", "preferredquality": "320"}]}))
        failed = []
        try:
            for i, (label, opts) in enumerate(jobs, 1):
                self.q.put(("status", f"[{i}/{len(jobs)}] Iniciando {label}…"))
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])
                except yt_dlp.utils.DownloadCancelled:
                    raise
                except Exception as e:  # noqa: BLE001
                    failed.append(f"{label}: {str(e)[:120]}")
            msg = "✔ Descarga completada en: " + out
            if failed:
                msg += "\nFallaron: " + "; ".join(failed)
            self.q.put(("done", msg))
        except yt_dlp.utils.DownloadCancelled:
            self.q.put(("done", "Descarga cancelada."))
        except Exception as e:  # noqa: BLE001
            self.q.put(("done", f"Error: {e}"))

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
            dlg.iconbitmap(os.path.join(_RES_DIR, "icon.ico"))
        except Exception:  # noqa: BLE001
            pass
        w, h = 460, 330
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
                    self._set_dl(True)
                elif kind == "app_update":
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
                    self.status.set("Error: " + msg[1][:300])
                elif kind == "progress":
                    self.bar["value"] = msg[1]
                    self.status.set(msg[2])
                elif kind == "status":
                    self.status.set(msg[1])
                elif kind == "done":
                    self.busy = False
                    self.bar["value"] = 0
                    self.btn_an.config(state="normal")
                    self._set_dl(True)
                    self.btn_cancel.config(state="disabled")
                    self.status.set(msg[1])
        except queue.Empty:
            pass
        self.after(100, self._poll)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":  # diagnóstico: escribe info a un archivo y sale
        import yt_dlp.extractor.youtube as _yt
        with open(sys.argv[2], "w", encoding="utf-8") as _f:
            _f.write("app=%s\nyt_dlp=%s\nfile=%s\nextractor=%s\n" % (
                updater.VERSION, yt_dlp.version.__version__, yt_dlp.__file__, _yt.__file__))
        sys.exit(0)
    App().mainloop()
