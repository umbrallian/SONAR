"""
SONAR - an all-in-one music player (dark navy, rounded, Napster-inspired).

  * Search YouTube / SoundCloud (or paste any link yt-dlp supports) and stream
    the result right inside the app
  * Download any track as MP3 or FLAC into a folder YOU choose (Settings)
  * Library of everything you've saved, with filter, shuffle, delete, reveal
  * Queue, playlists, shuffle / repeat, seek + volume
  * Download manager with live progress

Install:
    pip install -r requirements.txt
    + VLC media player  (https://www.videolan.org)   -> playback
    + FFmpeg on PATH    (https://ffmpeg.org)         -> MP3 / FLAC conversion

Only download music you have the rights to, and respect each service's terms.
"""

import os
import sys
import json
import queue
import random
import shutil
import threading
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
import yt_dlp

try:
    import vlc
except Exception:  # python-vlc missing or VLC not installed
    vlc = None

try:
    import mutagen
except Exception:
    mutagen = None

# ----------------------------------------------------------------- settings
APP_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(APP_DIR, "sonar_settings.json")
PLAYLIST_FILE = os.path.join(APP_DIR, "sonar_playlists.json")
AUDIO_EXT = (".mp3", ".flac", ".m4a", ".wav", ".ogg", ".opus", ".aac", ".wma")
MAX_CARDS = 150

DEFAULTS = {
    "download_dir": os.path.join(APP_DIR, "SONGS"),
    "default_format": "mp3",
    "mp3_quality": "320",
    "artist_folders": False,
    "embed_art": True,
    "volume": 80,
    "shuffle": False,
    "repeat": 0,  # 0 off, 1 all, 2 one
    "source": "Both",
}

BG = "#060b1c"
SIDEBAR = "#0a1330"
PANEL = "#0e1a3d"
CARD = "#12214a"
CARD_ALT = "#1c3068"
ACCENT = "#3d7bff"
ACCENT_HOVER = "#5a90ff"
TEXT = "#e8eefc"
MUTED = "#8a9bc4"
GOOD = "#3ddc97"
BAD = "#ff6b7a"
BADGE = {"YouTube": "#ff4d5e", "SoundCloud": "#ff8a3d", "Local": "#3ddc97"}
FONT = "Segoe UI"

NAV = [
    ("search", "🔍  Search"),
    ("queue", "🎶  Queue"),
    ("library", "💽  Library"),
    ("playlists", "📜  Playlists"),
    ("downloads", "⬇  Downloads"),
    ("settings", "⚙  Settings"),
]


# ------------------------------------------------------------------ helpers
def load_json(path, fallback):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def fmt_time(seconds):
    if not seconds or seconds < 0:
        return "--:--"
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def to_track(entry, source):
    url = entry.get("webpage_url") or entry.get("url")
    if not url:
        return None
    return {
        "title": entry.get("title") or "Unknown title",
        "uploader": entry.get("uploader") or entry.get("channel") or "",
        "duration": entry.get("duration"),
        "url": url,
        "source": source,
        "local": False,
    }


def search_online(query, source, n=12):
    """Return a list of track dicts for a text query or a pasted URL."""
    base = {"quiet": True, "extract_flat": True, "skip_download": True, "noplaylist": True}

    if query.lower().startswith("http"):
        with yt_dlp.YoutubeDL({**base, "extract_flat": "in_playlist", "noplaylist": False}) as y:
            info = y.extract_info(query, download=False)
        label = (info.get("extractor_key") or "Web").replace("Soundcloud", "SoundCloud")
        entries = info.get("entries") or [info]
        tracks = [to_track(e, label) for e in entries if e]
        return [t for t in tracks if t]

    prefixes = {"YouTube": "ytsearch", "SoundCloud": "scsearch"}
    wanted = list(prefixes) if source == "Both" else [source]
    per_source = {}
    errors = []
    for name in wanted:
        try:
            with yt_dlp.YoutubeDL(base) as y:
                info = y.extract_info(f"{prefixes[name]}{n}:{query}", download=False)
            tracks = [to_track(e, name) for e in (info.get("entries") or []) if e]
            per_source[name] = [t for t in tracks if t]
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            per_source[name] = []

    merged = []  # interleave so "Both" mixes the sources
    longest = max((len(v) for v in per_source.values()), default=0)
    for i in range(longest):
        for name in wanted:
            if i < len(per_source[name]):
                merged.append(per_source[name][i])
    if not merged and errors:
        raise RuntimeError("; ".join(errors))
    return merged


def resolve_stream(url):
    """Get a direct audio stream URL for a page URL."""
    opts = {"quiet": True, "format": "bestaudio/best", "noplaylist": True}
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=False)
    return info["url"]


def local_track(path, root):
    title = os.path.splitext(os.path.basename(path))[0]
    artist = ""
    duration = None
    if mutagen:
        try:
            m = mutagen.File(path, easy=True)
            if m is not None:
                if getattr(m, "info", None) and getattr(m.info, "length", None):
                    duration = m.info.length
                t = m.get("title")
                a = m.get("artist")
                if t:
                    title = t[0]
                if a:
                    artist = a[0]
        except Exception:
            pass
    if not artist:
        rel = os.path.relpath(os.path.dirname(path), root)
        artist = "" if rel == "." else os.path.basename(rel)
    return {
        "title": title,
        "uploader": artist or os.path.splitext(path)[1][1:].upper(),
        "duration": duration,
        "url": path,
        "source": "Local",
        "local": True,
    }


def scan_library(root):
    tracks = []
    if not os.path.isdir(root):
        return tracks
    for folder, _dirs, files in os.walk(root):
        for name in sorted(files):
            if name.lower().endswith(AUDIO_EXT):
                tracks.append(local_track(os.path.join(folder, name), root))
    tracks.sort(key=lambda t: (t["uploader"].lower(), t["title"].lower()))
    return tracks


def open_folder(path):
    try:
        os.makedirs(path, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def reveal_file(path):
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
    except Exception:
        pass


# ---------------------------------------------------------------------- app
class SonarApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("SONAR")
        self.geometry("1180x780")
        self.minsize(960, 640)
        self.configure(fg_color=BG)

        self.settings = {**DEFAULTS, **load_json(SETTINGS_FILE, {})}
        self.playlists = load_json(PLAYLIST_FILE, {})
        os.makedirs(self.settings["download_dir"], exist_ok=True)

        self.results = []
        self.library_all = []
        self.library_view = []
        self.queue = []
        self.index = -1
        self.history = []
        self.played = set()
        self.current = None
        self.seeking = False
        self.ended_handled = True
        self.play_token = 0
        self.view_name = "search"
        self.open_playlist = None
        self.shuffle = bool(self.settings["shuffle"])
        self.repeat = int(self.settings["repeat"])
        self.cards = []
        self.dl_widgets = {}
        self.downloads = []
        self.dl_counter = 0
        self.dl_slots = threading.Semaphore(2)
        self.uiq = queue.Queue()

        self.vlc_instance = None
        self.player = None
        if vlc:
            try:
                self.vlc_instance = vlc.Instance("--no-video", "--quiet")
                self.player = self.vlc_instance.media_player_new()
            except Exception:
                self.player = None

        self._build_layout()
        self._sync_mode_buttons()
        self.show_view("search")
        if not self.player:
            self.set_status("Playback needs VLC installed (and python-vlc). Search & downloads still work.")

        self.bind("<space>", self._space)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(60, self._pump)
        self.after(500, self._tick)

    # ----------------------------------------------------- thread plumbing
    def ui(self, fn):
        """Run fn on the main thread (safe to call from worker threads)."""
        self.uiq.put(fn)

    def _pump(self):
        try:
            while True:
                fn = self.uiq.get_nowait()
                try:
                    fn()
                except Exception as exc:
                    print("ui error:", exc)
        except queue.Empty:
            pass
        self.after(60, self._pump)

    def _space(self, _event):
        w = self.focus_get()
        if w is not None and "entry" in str(w).lower():
            return
        self.toggle_pause()

    def _on_close(self):
        self.settings["volume"] = int(self.volume.get())
        self.settings["shuffle"] = self.shuffle
        self.settings["repeat"] = self.repeat
        self.save_settings()
        try:
            if self.player:
                self.player.stop()
        except Exception:
            pass
        self.destroy()

    def save_settings(self):
        save_json(SETTINGS_FILE, self.settings)

    def _set(self, key, value):
        self.settings[key] = value
        self.save_settings()

    # ------------------------------------------------------------- layout
    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ---- sidebar
        side = ctk.CTkFrame(self, fg_color=SIDEBAR, corner_radius=26, width=220)
        side.grid(row=0, column=0, sticky="nsw", padx=(14, 7), pady=(14, 7))
        side.grid_propagate(False)

        ctk.CTkLabel(side, text="SONAR", font=(FONT, 28, "bold"), text_color=TEXT).pack(anchor="w", padx=24, pady=(26, 0))
        ctk.CTkLabel(side, text="stream  ·  save  ·  play", font=(FONT, 12), text_color=MUTED).pack(anchor="w", padx=24, pady=(0, 20))

        self.nav = {}
        for key, label in NAV:
            b = ctk.CTkButton(
                side, text=label, anchor="w", height=42, corner_radius=21,
                font=(FONT, 14, "bold"), fg_color="transparent", hover_color=CARD,
                text_color=TEXT, command=lambda k=key: self.show_view(k),
            )
            b.pack(fill="x", padx=14, pady=2)
            self.nav[key] = b

        ctk.CTkButton(
            side, text="📂  Open music folder", height=40, corner_radius=20, font=(FONT, 13),
            fg_color=CARD, hover_color=CARD_ALT, text_color=TEXT,
            command=lambda: open_folder(self.settings["download_dir"]),
        ).pack(side="bottom", fill="x", padx=14, pady=16)

        # ---- main panel
        main = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=26)
        main.grid(row=0, column=1, sticky="nsew", padx=(7, 14), pady=(14, 7))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(3, weight=1)

        header = ctk.CTkFrame(main, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=22, pady=(22, 6))
        header.grid_columnconfigure(0, weight=1)

        self.entry = ctk.CTkEntry(
            header, height=46, corner_radius=23, border_width=0, fg_color=CARD,
            text_color=TEXT, placeholder_text="Search songs, artists, or paste a link…",
            placeholder_text_color=MUTED, font=(FONT, 15),
        )
        self.entry.grid(row=0, column=0, sticky="ew")
        self.entry.bind("<Return>", lambda e: self.do_search())

        ctk.CTkButton(
            header, text="Search", width=100, height=46, corner_radius=23, font=(FONT, 15, "bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self.do_search,
        ).grid(row=0, column=1, padx=(10, 0))

        self.source = ctk.CTkSegmentedButton(
            header, values=["YouTube", "SoundCloud", "Both"], height=34, corner_radius=17,
            fg_color=CARD, selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
            unselected_color=CARD, unselected_hover_color=CARD_ALT, font=(FONT, 13, "bold"),
            command=lambda v: self._set("source", v),
        )
        self.source.set(self.settings["source"])
        self.source.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))

        self.status = ctk.CTkLabel(main, text="", font=(FONT, 12), text_color=MUTED, anchor="w")
        self.status.grid(row=1, column=0, sticky="ew", padx=26, pady=(2, 2))

        self.toolbar = ctk.CTkFrame(main, fg_color="transparent")
        self.toolbar.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 4))

        self.list_area = ctk.CTkScrollableFrame(
            main, fg_color="transparent", scrollbar_button_color=CARD_ALT,
            scrollbar_button_hover_color=ACCENT,
        )
        self.list_area.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 14))
        self.list_area.grid_columnconfigure(0, weight=1)

        # ---- player bar
        bar = ctk.CTkFrame(self, fg_color=SIDEBAR, corner_radius=30, height=100)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=14, pady=(7, 14))
        bar.grid_columnconfigure(1, weight=1)
        bar.grid_propagate(False)

        info = ctk.CTkFrame(bar, fg_color="transparent", width=280)
        info.grid(row=0, column=0, sticky="nsw", padx=(26, 10), pady=14)
        info.grid_propagate(False)
        self.now_title = ctk.CTkLabel(info, text="Nothing playing", font=(FONT, 14, "bold"), text_color=TEXT,
                                      anchor="w", wraplength=260, justify="left")
        self.now_title.pack(anchor="w", pady=(10, 0))
        self.now_sub = ctk.CTkLabel(info, text="Search for a song to start", font=(FONT, 12), text_color=MUTED, anchor="w")
        self.now_sub.pack(anchor="w")

        mid = ctk.CTkFrame(bar, fg_color="transparent")
        mid.grid(row=0, column=1, sticky="nsew", pady=10)
        mid.grid_columnconfigure(0, weight=1)

        ctrl = ctk.CTkFrame(mid, fg_color="transparent")
        ctrl.grid(row=0, column=0)
        btn_kw = dict(width=40, height=40, corner_radius=20, font=(FONT, 15), fg_color=CARD,
                      hover_color=CARD_ALT, text_color=TEXT)
        self.shuffle_btn = ctk.CTkButton(ctrl, text="🔀", command=self.toggle_shuffle, **btn_kw)
        self.shuffle_btn.pack(side="left", padx=5)
        ctk.CTkButton(ctrl, text="⏮", command=self.prev_track, **btn_kw).pack(side="left", padx=5)
        self.play_btn = ctk.CTkButton(ctrl, text="▶", command=self.toggle_pause, width=52, height=52, corner_radius=26,
                                      font=(FONT, 20), fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="white")
        self.play_btn.pack(side="left", padx=5)
        ctk.CTkButton(ctrl, text="⏭", command=lambda: self.next_track(), **btn_kw).pack(side="left", padx=5)
        self.repeat_btn = ctk.CTkButton(ctrl, text="🔁", command=self.cycle_repeat, **btn_kw)
        self.repeat_btn.pack(side="left", padx=5)

        prog = ctk.CTkFrame(mid, fg_color="transparent")
        prog.grid(row=1, column=0, sticky="ew", padx=10)
        prog.grid_columnconfigure(1, weight=1)
        self.t_now = ctk.CTkLabel(prog, text="0:00", font=(FONT, 11), text_color=MUTED, width=40)
        self.t_now.grid(row=0, column=0)
        self.seek = ctk.CTkSlider(prog, from_=0, to=1, height=14, progress_color=ACCENT, button_color=TEXT,
                                  button_hover_color="white", fg_color=CARD)
        self.seek.set(0)
        self.seek.grid(row=0, column=1, sticky="ew", padx=6)
        self.seek.bind("<ButtonPress-1>", lambda e: setattr(self, "seeking", True))
        self.seek.bind("<ButtonRelease-1>", self._seek_release)
        self.t_total = ctk.CTkLabel(prog, text="0:00", font=(FONT, 11), text_color=MUTED, width=40)
        self.t_total.grid(row=0, column=2)

        vol = ctk.CTkFrame(bar, fg_color="transparent")
        vol.grid(row=0, column=2, sticky="e", padx=(10, 28))
        ctk.CTkLabel(vol, text="🔊", font=(FONT, 16), text_color=MUTED).pack(side="left", padx=(0, 6))
        self.volume = ctk.CTkSlider(vol, from_=0, to=100, width=110, height=14, progress_color=ACCENT,
                                    button_color=TEXT, fg_color=CARD, command=self._set_volume)
        self.volume.set(self.settings["volume"])
        self.volume.pack(side="left")

    # -------------------------------------------------------------- views
    def show_view(self, name):
        self.view_name = name
        self._update_nav()
        for w in self.toolbar.winfo_children():
            w.destroy()
        self.dl_widgets = {}
        getattr(self, f"_view_{name}")()

    def _update_nav(self):
        active = sum(1 for d in self.downloads if d["state"] in ("Queued", "Downloading", "Converting"))
        for key, label in NAV:
            text = label
            if key == "queue" and self.queue:
                text += f"  ({len(self.queue)})"
            if key == "downloads" and active:
                text += f"  ({active})"
            self.nav[key].configure(text=text, fg_color=CARD if key == self.view_name else "transparent")

    def _tb(self, text, cmd, width=120, primary=False):
        b = ctk.CTkButton(
            self.toolbar, text=text, width=width, height=34, corner_radius=17, font=(FONT, 12, "bold"),
            fg_color=ACCENT if primary else CARD, hover_color=ACCENT_HOVER if primary else CARD_ALT,
            text_color="white" if primary else TEXT, command=cmd,
        )
        b.pack(side="left", padx=(0, 8))
        return b

    def set_status(self, text):
        self.status.configure(text=text)

    def _render(self, tracks, empty_text, mode):
        for w in self.list_area.winfo_children():
            w.destroy()
        self.cards = []
        if not tracks:
            ctk.CTkLabel(self.list_area, text=empty_text, font=(FONT, 14), text_color=MUTED, justify="center").pack(pady=80)
            return
        for i, t in enumerate(tracks[:MAX_CARDS]):
            self._make_card(i, t, tracks, mode)
        if len(tracks) > MAX_CARDS:
            ctk.CTkLabel(self.list_area, text=f"Showing the first {MAX_CARDS} of {len(tracks)} - use the filter to narrow it down.",
                         font=(FONT, 12), text_color=MUTED).pack(pady=14)

    def _make_card(self, i, t, tracks, mode):
        playing = self.current is not None and self.current.get("url") == t["url"]
        card = ctk.CTkFrame(self.list_area, fg_color=CARD_ALT if playing else CARD, corner_radius=20)
        card.pack(fill="x", padx=8, pady=5)
        card.grid_columnconfigure(1, weight=1)
        self.cards.append((card, t["url"]))

        ctk.CTkLabel(
            card, text=t["source"], font=(FONT, 11, "bold"), text_color="white",
            fg_color=BADGE.get(t["source"], ACCENT), corner_radius=10, width=82, height=24,
        ).grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=14)

        ctk.CTkLabel(card, text=t["title"], font=(FONT, 14, "bold"), text_color=TEXT, anchor="w",
                     wraplength=300, justify="left").grid(row=0, column=1, sticky="w", pady=(12, 0))
        sub = "  ·  ".join(x for x in (t["uploader"], fmt_time(t["duration"]) if t["duration"] else "") if x)
        ctk.CTkLabel(card, text=sub, font=(FONT, 12), text_color=MUTED, anchor="w").grid(row=1, column=1, sticky="w", pady=(0, 12))

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=0, column=2, rowspan=2, padx=12)
        small = dict(height=34, corner_radius=17, font=(FONT, 12, "bold"))

        def btn(text, cmd, width, color=PANEL, hover=ACCENT):
            ctk.CTkButton(actions, text=text, width=width, fg_color=color, hover_color=hover,
                          command=cmd, **small).pack(side="left", padx=3)

        btn("▶ Play", lambda: self.play_from_list(tracks, i), 70, ACCENT, ACCENT_HOVER)
        if mode in ("search", "library", "playlist"):
            btn("Queue", lambda: self.add_to_queue(t), 62)
        if mode != "playlist":
            btn("♡", lambda: self._playlist_menu(t), 36)
        if mode == "queue":
            btn("✕", lambda: self.remove_from_queue(i), 36)
        if mode == "playlist":
            btn("✕", lambda: self.remove_from_playlist(i), 36)
        if t["local"]:
            if mode == "library":
                btn("📂", lambda: reveal_file(t["url"]), 40)
                btn("🗑", lambda: self.delete_local(t), 40)
        else:
            btn("MP3", lambda: self.download(t, "mp3"), 52)
            btn("FLAC", lambda: self.download(t, "flac"), 56)

    def _refresh_highlight(self):
        url = self.current.get("url") if self.current else None
        for card, curl in self.cards:
            try:
                card.configure(fg_color=CARD_ALT if curl == url else CARD)
            except Exception:
                pass

    # ---- search view
    def _view_search(self):
        if self.results:
            self._tb("▶ Play all", lambda: self.play_all(self.results), 100, True)
            fmt = self.settings["default_format"].upper()
            self._tb(f"⬇ Save all ({fmt})", self.save_all_results, 150)
        self._render(self.results, "Search for something to see results here.\nTip: you can also paste a YouTube / SoundCloud link.", "search")

    def do_search(self):
        q = self.entry.get().strip()
        if not q:
            return
        src = self.source.get()
        self.show_view("search")
        self.set_status("Searching…")

        def run():
            try:
                res = search_online(q, src)
                self.ui(lambda: self._search_done(res))
            except Exception as exc:
                msg = str(exc)[:160]
                self.ui(lambda: self.set_status(f"Search failed: {msg}"))

        threading.Thread(target=run, daemon=True).start()

    def _search_done(self, res):
        self.results = res
        self.set_status(f"{len(res)} results")
        if self.view_name == "search":
            self.show_view("search")
            self.set_status(f"{len(res)} results")

    def save_all_results(self):
        n = len(self.results)
        fmt = self.settings["default_format"]
        if n > 5 and not messagebox.askyesno("Save all", f"Download all {n} results as {fmt.upper()}?"):
            return
        for t in self.results:
            self.download(t, fmt)

    # ---- queue view
    def _view_queue(self):
        if self.queue:
            self._tb("Clear queue", self.clear_queue, 110)
            self._tb("💾 Save as playlist", self.save_queue_as_playlist, 160)
        self._render(self.queue, "Your queue is empty. Play a result or hit “Queue” on a song.", "queue")

    def add_to_queue(self, t):
        self.queue.append(t)
        self._update_nav()
        self.set_status(f"Added to queue: {t['title']}")

    def remove_from_queue(self, i):
        if 0 <= i < len(self.queue):
            del self.queue[i]
            if i <= self.index:
                self.index -= 1
            self.history.clear()
            self.played.clear()
            self.show_view("queue")

    def clear_queue(self):
        self.queue = []
        self.index = -1
        self.history.clear()
        self.played.clear()
        self.show_view("queue")

    def save_queue_as_playlist(self):
        name = ctk.CTkInputDialog(text="Name this playlist:", title="Save playlist").get_input()
        if name and name.strip():
            self.playlists[name.strip()] = [dict(t) for t in self.queue]
            save_json(PLAYLIST_FILE, self.playlists)
            self.set_status(f"Saved playlist “{name.strip()}” ({len(self.queue)} songs)")

    # ---- library view
    def _view_library(self):
        self.lib_entry = ctk.CTkEntry(
            self.toolbar, width=240, height=34, corner_radius=17, border_width=0, fg_color=CARD,
            text_color=TEXT, placeholder_text="Filter library…", placeholder_text_color=MUTED, font=(FONT, 13),
        )
        self.lib_entry.pack(side="left", padx=(0, 8))
        self.lib_entry.bind("<KeyRelease>", lambda e: self._render_library())
        self._tb("▶ Play all", lambda: self.play_all(self.library_view), 100, True)
        self._tb("🔀 Shuffle", lambda: self.play_all(self.library_view, shuffle=True), 100)
        self._tb("↻ Refresh", self._scan_library_async, 90)
        self._render_library()
        self._scan_library_async()

    def _scan_library_async(self):
        folder = self.settings["download_dir"]
        self.set_status("Scanning library…")

        def run():
            tracks = scan_library(folder)
            self.ui(lambda: self._library_loaded(tracks, folder))

        threading.Thread(target=run, daemon=True).start()

    def _library_loaded(self, tracks, folder):
        self.library_all = tracks
        if self.view_name == "library":
            self.set_status(f"{len(tracks)} songs in {folder}")
            self._render_library()

    def _render_library(self):
        q = ""
        try:
            q = self.lib_entry.get().strip().lower()
        except Exception:
            pass
        tracks = self.library_all
        if q:
            tracks = [t for t in tracks if q in t["title"].lower() or q in t["uploader"].lower()]
        self.library_view = tracks
        self._render(tracks, f"No songs yet. Hit MP3 or FLAC on any search result\nand it will land in:\n{self.settings['download_dir']}", "library")

    def delete_local(self, t):
        if not messagebox.askyesno("Delete song", f"Permanently delete this file?\n\n{t['url']}"):
            return
        try:
            if self.current and self.current.get("url") == t["url"] and self.player:
                self.player.stop()
            os.remove(t["url"])
        except Exception as exc:
            self.set_status(f"Couldn't delete: {exc}")
            return
        self.library_all = [x for x in self.library_all if x["url"] != t["url"]]
        self.set_status(f"Deleted {t['title']}")
        self._render_library()

    # ---- playlists
    def _view_playlists(self):
        if self.open_playlist and self.open_playlist in self.playlists:
            name = self.open_playlist
            tracks = self.playlists[name]
            self._tb("← Back", self._close_playlist, 80)
            self._tb("▶ Play all", lambda: self.play_all(tracks), 100, True)
            self._tb("🔀 Shuffle", lambda: self.play_all(tracks, shuffle=True), 100)
            self._tb("🗑 Delete playlist", lambda: self.delete_playlist(name), 150)
            self.set_status(f"{name} · {len(tracks)} songs")
            self._render(tracks, "This playlist is empty. Hit ♡ on any song to add it.", "playlist")
            return

        self.open_playlist = None
        self._tb("＋ New playlist", self.new_playlist, 130, True)
        for w in self.list_area.winfo_children():
            w.destroy()
        self.cards = []
        if not self.playlists:
            ctk.CTkLabel(self.list_area, text="No playlists yet.\nCreate one, or hit ♡ on any song.",
                         font=(FONT, 14), text_color=MUTED, justify="center").pack(pady=80)
            return
        for name, tracks in self.playlists.items():
            card = ctk.CTkFrame(self.list_area, fg_color=CARD, corner_radius=20)
            card.pack(fill="x", padx=8, pady=5)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=name, font=(FONT, 15, "bold"), text_color=TEXT, anchor="w").grid(
                row=0, column=0, sticky="w", padx=20, pady=(14, 0))
            ctk.CTkLabel(card, text=f"{len(tracks)} songs", font=(FONT, 12), text_color=MUTED, anchor="w").grid(
                row=1, column=0, sticky="w", padx=20, pady=(0, 14))
            acts = ctk.CTkFrame(card, fg_color="transparent")
            acts.grid(row=0, column=1, rowspan=2, padx=12)
            small = dict(height=34, corner_radius=17, font=(FONT, 12, "bold"))
            ctk.CTkButton(acts, text="Open", width=64, fg_color=PANEL, hover_color=ACCENT,
                          command=lambda n=name: self._open_playlist(n), **small).pack(side="left", padx=3)
            ctk.CTkButton(acts, text="▶ Play", width=70, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                          command=lambda tr=tracks: self.play_all(tr), **small).pack(side="left", padx=3)
            ctk.CTkButton(acts, text="+ Queue", width=70, fg_color=PANEL, hover_color=ACCENT,
                          command=lambda tr=tracks: self._queue_many(tr), **small).pack(side="left", padx=3)

    def _open_playlist(self, name):
        self.open_playlist = name
        self.show_view("playlists")

    def _close_playlist(self):
        self.open_playlist = None
        self.show_view("playlists")

    def _queue_many(self, tracks):
        self.queue.extend(tracks)
        self._update_nav()
        self.set_status(f"Added {len(tracks)} songs to the queue")

    def new_playlist(self):
        name = ctk.CTkInputDialog(text="Playlist name:", title="New playlist").get_input()
        if name and name.strip() and name.strip() not in self.playlists:
            self.playlists[name.strip()] = []
            save_json(PLAYLIST_FILE, self.playlists)
            self.show_view("playlists")

    def delete_playlist(self, name):
        if messagebox.askyesno("Delete playlist", f"Delete playlist “{name}”? (Songs on disk are not touched.)"):
            self.playlists.pop(name, None)
            save_json(PLAYLIST_FILE, self.playlists)
            self.open_playlist = None
            self.show_view("playlists")

    def remove_from_playlist(self, i):
        tracks = self.playlists.get(self.open_playlist, [])
        if 0 <= i < len(tracks):
            del tracks[i]
            save_json(PLAYLIST_FILE, self.playlists)
            self.show_view("playlists")

    def add_to_playlist(self, name, t):
        lst = self.playlists.setdefault(name, [])
        if any(x["url"] == t["url"] for x in lst):
            self.set_status(f"Already in “{name}”")
            return
        lst.append(dict(t))
        save_json(PLAYLIST_FILE, self.playlists)
        self.set_status(f"Added to “{name}”: {t['title']}")

    def _playlist_menu(self, t):
        m = tk.Menu(self, tearoff=0, bg=CARD, fg=TEXT, activebackground=ACCENT,
                    activeforeground="white", bd=0, font=(FONT, 11))
        for name in self.playlists:
            m.add_command(label=name, command=lambda n=name: self.add_to_playlist(n, t))
        if self.playlists:
            m.add_separator()
        m.add_command(label="＋ New playlist…", command=lambda: self._new_playlist_with(t))
        try:
            m.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            m.grab_release()

    def _new_playlist_with(self, t):
        name = ctk.CTkInputDialog(text="Playlist name:", title="New playlist").get_input()
        if name and name.strip():
            self.add_to_playlist(name.strip(), t)

    # ---- downloads view
    def _view_downloads(self):
        self._tb("Clear finished", self.clear_finished_downloads, 120)
        self._tb("📂 Open folder", lambda: open_folder(self.settings["download_dir"]), 120)
        for w in self.list_area.winfo_children():
            w.destroy()
        self.cards = []
        self.set_status(f"Saving to: {self.settings['download_dir']}")
        if not self.downloads:
            ctk.CTkLabel(self.list_area, text="No downloads yet.\nHit MP3 or FLAC on any song to save it.",
                         font=(FONT, 14), text_color=MUTED, justify="center").pack(pady=80)
            return
        for dl in reversed(self.downloads):
            card = ctk.CTkFrame(self.list_area, fg_color=CARD, corner_radius=20)
            card.pack(fill="x", padx=8, pady=5)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=dl["title"], font=(FONT, 14, "bold"), text_color=TEXT, anchor="w",
                         wraplength=520, justify="left").grid(row=0, column=0, sticky="w", padx=20, pady=(12, 0))
            label = ctk.CTkLabel(card, text=self._dl_text(dl), font=(FONT, 12), text_color=MUTED, anchor="w")
            label.grid(row=1, column=0, sticky="w", padx=20)
            bar = ctk.CTkProgressBar(card, height=8, corner_radius=4, progress_color=ACCENT, fg_color=PANEL)
            bar.set(dl["pct"])
            bar.grid(row=2, column=0, sticky="ew", padx=20, pady=(6, 14))
            self.dl_widgets[dl["id"]] = {"label": label, "bar": bar}
            small = dict(height=34, corner_radius=17, font=(FONT, 12, "bold"))
            if dl["state"] == "Done" and dl["path"] and os.path.exists(dl["path"]):
                tr = local_track(dl["path"], self.settings["download_dir"])
                ctk.CTkButton(card, text="▶ Play", width=70, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                              command=lambda t=tr: self.play_from_list([t], 0), **small).grid(
                    row=0, column=1, rowspan=3, padx=(0, 6))
                ctk.CTkButton(card, text="📂", width=40, fg_color=PANEL, hover_color=ACCENT,
                              command=lambda p=dl["path"]: reveal_file(p), **small).grid(
                    row=0, column=2, rowspan=3, padx=(0, 14))
            elif dl["state"] == "Failed":
                ctk.CTkButton(card, text="↻ Retry", width=76, fg_color=PANEL, hover_color=ACCENT,
                              command=lambda d=dl: self.download(d["track"], d["fmt"]), **small).grid(
                    row=0, column=1, rowspan=3, padx=(0, 14))

    def clear_finished_downloads(self):
        self.downloads = [d for d in self.downloads if d["state"] in ("Queued", "Downloading", "Converting")]
        self.show_view("downloads")

    @staticmethod
    def _dl_text(dl):
        fmt = dl["fmt"].upper()
        if dl["state"] in ("Queued", "Downloading"):
            return f"{dl['state']}… {int(dl['pct'] * 100)}%  ·  {fmt}"
        if dl["state"] == "Converting":
            return f"Converting to {fmt}…"
        if dl["state"] == "Done":
            return f"Saved ✓  ·  {fmt}"
        return f"Failed: {dl['error'][:110]}"

    # ---- settings view
    def _view_settings(self):
        for w in self.list_area.winfo_children():
            w.destroy()
        self.cards = []
        self.set_status("")

        def group(title, sub=None):
            card = ctk.CTkFrame(self.list_area, fg_color=CARD, corner_radius=20)
            card.pack(fill="x", padx=8, pady=6)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=title, font=(FONT, 15, "bold"), text_color=TEXT, anchor="w").grid(
                row=0, column=0, sticky="w", padx=20, pady=(14, 0))
            lbl = None
            if sub is not None:
                lbl = ctk.CTkLabel(card, text=sub, font=(FONT, 12), text_color=MUTED, anchor="w",
                                   wraplength=480, justify="left")
                lbl.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 14))
            return card, lbl

        small = dict(height=34, corner_radius=17, font=(FONT, 12, "bold"))

        card, _ = group("Download folder", self.settings["download_dir"])
        box = ctk.CTkFrame(card, fg_color="transparent")
        box.grid(row=0, column=1, rowspan=2, padx=14)
        ctk.CTkButton(box, text="Change…", width=84, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self.choose_folder, **small).pack(side="left", padx=3)
        ctk.CTkButton(box, text="Open", width=64, fg_color=PANEL, hover_color=ACCENT,
                      command=lambda: open_folder(self.settings["download_dir"]), **small).pack(side="left", padx=3)

        card, _ = group("Default download format", "Used by “Save all”. The MP3 / FLAC buttons on each song always use their own format.")
        seg = ctk.CTkSegmentedButton(
            card, values=["MP3", "FLAC"], height=34, corner_radius=17, fg_color=PANEL, selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER, unselected_color=PANEL, unselected_hover_color=CARD_ALT,
            font=(FONT, 13, "bold"), command=lambda v: self._set("default_format", v.lower()),
        )
        seg.set(self.settings["default_format"].upper())
        seg.grid(row=0, column=1, rowspan=2, padx=20)

        card, _ = group("MP3 quality", "Bitrate in kbps. FLAC is lossless and ignores this.")
        ctk.CTkOptionMenu(
            card, values=["128", "192", "256", "320"], width=100, height=34, corner_radius=17,
            fg_color=PANEL, button_color=ACCENT, button_hover_color=ACCENT_HOVER, dropdown_fg_color=CARD,
            dropdown_hover_color=CARD_ALT, dropdown_text_color=TEXT, font=(FONT, 13),
            command=lambda v: self._set("mp3_quality", v),
        ).grid(row=0, column=1, rowspan=2, padx=20)
        # set current value
        for child in card.winfo_children():
            if isinstance(child, ctk.CTkOptionMenu):
                child.set(str(self.settings["mp3_quality"]))

        def switch(title, sub, key):
            c, _ = group(title, sub)
            sw = ctk.CTkSwitch(c, text="", progress_color=ACCENT, fg_color=PANEL, width=48,
                               command=lambda: self._set(key, bool(sw.get())))
            sw.grid(row=0, column=1, rowspan=2, padx=20)
            if self.settings[key]:
                sw.select()

        switch("Sort into artist folders", "Saves as  <folder>/<artist>/<title>.mp3  instead of one flat folder.", "artist_folders")
        switch("Embed cover art & tags", "Adds the thumbnail and title/artist info inside each saved file.", "embed_art")

        def ok(flag):
            return ("✓ found", GOOD) if flag else ("✗ missing", BAD)

        card, _ = group("Setup check")
        rows = [
            ("Playback (VLC + python-vlc)", self.player is not None),
            ("MP3 / FLAC conversion (FFmpeg)", shutil.which("ffmpeg") is not None),
            ("Tags & cover art (mutagen)", mutagen is not None),
        ]
        for r, (name, flag) in enumerate(rows, start=1):
            text, color = ok(flag)
            ctk.CTkLabel(card, text=name, font=(FONT, 13), text_color=TEXT, anchor="w").grid(
                row=r, column=0, sticky="w", padx=20, pady=(0, 6 if r < len(rows) else 14))
            ctk.CTkLabel(card, text=text, font=(FONT, 13, "bold"), text_color=color).grid(
                row=r, column=1, padx=20, pady=(0, 6 if r < len(rows) else 14))

    def choose_folder(self):
        d = filedialog.askdirectory(initialdir=self.settings["download_dir"], title="Choose download folder")
        if d:
            d = os.path.normpath(d)
            self._set("download_dir", d)
            self.library_all = []
            self.show_view("settings")
            self.set_status(f"Downloads and library now use: {d}")

    # ----------------------------------------------------------- playback
    def play_from_list(self, tracks, i):
        self.queue = list(tracks)
        self.index = i
        self.history.clear()
        self.played.clear()
        self._update_nav()
        self.play_track(self.queue[i])

    def play_all(self, tracks, shuffle=False):
        if not tracks:
            return
        i = 0
        if shuffle:
            self.shuffle = True
            self._sync_mode_buttons()
            i = random.randrange(len(tracks))
        self.play_from_list(tracks, i)

    def play_track(self, t):
        if not self.player:
            self.set_status("Install VLC + python-vlc to enable playback.")
            return
        if t["local"] and not os.path.exists(t["url"]):
            self.set_status("That file no longer exists on disk.")
            return
        self.current = t
        self.play_token += 1
        token = self.play_token
        self.ended_handled = True  # ignore stale 'Ended' until the new stream starts
        try:
            self.player.stop()
        except Exception:
            pass
        self.now_title.configure(text=t["title"])
        self.now_sub.configure(text=t["uploader"] or t["source"])
        self.seek.set(0)
        self.t_now.configure(text="0:00")
        self.t_total.configure(text=fmt_time(t["duration"]) if t.get("duration") else "0:00")
        self._refresh_highlight()
        self.set_status("Loading…" if t["local"] else "Loading stream…")

        def run():
            try:
                url = t["url"] if t["local"] else resolve_stream(t["url"])
                self.ui(lambda: self._start(url, token, t["local"]))
            except Exception as exc:
                msg = str(exc)[:160]
                self.ui(lambda: self.set_status(f"Couldn't stream: {msg}"))

        threading.Thread(target=run, daemon=True).start()

    def _start(self, url, token, local):
        if token != self.play_token:
            return  # a newer track was chosen while this one loaded
        media = self.vlc_instance.media_new_path(url) if local else self.vlc_instance.media_new(url)
        self.player.set_media(media)
        self.player.audio_set_volume(int(self.volume.get()))
        self.player.play()
        self.ended_handled = False
        self.play_btn.configure(text="⏸")
        self.set_status("Now playing")

    def toggle_pause(self):
        if not self.player or self.current is None:
            return
        if self.player.is_playing():
            self.player.pause()
            self.play_btn.configure(text="▶")
        else:
            self.player.play()
            self.play_btn.configure(text="⏸")

    def next_track(self, auto=False):
        if not self.queue:
            return
        if auto and self.repeat == 2 and self.current:
            self.play_track(self.current)
            return
        prev_index = self.index
        if self.shuffle and len(self.queue) > 1:
            if prev_index >= 0:
                self.played.add(prev_index)
            choices = [i for i in range(len(self.queue)) if i not in self.played and i != prev_index]
            if not choices:
                if self.repeat == 1:
                    self.played.clear()
                    choices = [i for i in range(len(self.queue)) if i != prev_index]
                else:
                    self._end_of_queue()
                    return
            self.index = random.choice(choices)
        elif self.index + 1 < len(self.queue):
            self.index += 1
        elif self.repeat == 1:
            self.index = 0
        else:
            self._end_of_queue()
            return
        if prev_index >= 0:
            self.history.append(prev_index)
            del self.history[:-200]
        self.play_track(self.queue[self.index])

    def _end_of_queue(self):
        try:
            if self.player:
                self.player.stop()
        except Exception:
            pass
        self.play_btn.configure(text="▶")
        self.set_status("End of queue")

    def prev_track(self):
        if not self.queue:
            return
        if self.player and self.player.get_time() > 4000:
            self.player.set_time(0)
            return
        if self.history:
            self.index = self.history.pop()
        else:
            self.index = max(0, self.index - 1)
        self.play_track(self.queue[self.index])

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle
        self.played.clear()
        self._sync_mode_buttons()

    def cycle_repeat(self):
        self.repeat = (self.repeat + 1) % 3
        self._sync_mode_buttons()

    def _sync_mode_buttons(self):
        self.shuffle_btn.configure(fg_color=ACCENT if self.shuffle else CARD)
        self.repeat_btn.configure(text="🔂" if self.repeat == 2 else "🔁",
                                  fg_color=ACCENT if self.repeat else CARD)

    def _set_volume(self, v):
        if self.player:
            self.player.audio_set_volume(int(v))

    def _seek_release(self, _event):
        if self.player and self.player.get_length() > 0:
            self.player.set_position(self.seek.get())
        self.seeking = False

    def _tick(self):
        try:
            if self.player and vlc:
                state = self.player.get_state()
                if state == vlc.State.Ended and not self.ended_handled:
                    self.ended_handled = True
                    self.next_track(auto=True)
                elif state == vlc.State.Error and not self.ended_handled:
                    self.ended_handled = True
                    self.set_status("Couldn't play that track - skipping")
                    self.next_track()
                elif state in (vlc.State.Playing, vlc.State.Paused):
                    length = self.player.get_length()
                    now = self.player.get_time()
                    if length > 0:
                        self.t_total.configure(text=fmt_time(length / 1000))
                        if not self.seeking:
                            self.seek.set(min(1, max(0, now / length)))
                            self.t_now.configure(text=fmt_time(now / 1000))
        except Exception:
            pass
        finally:
            self.after(500, self._tick)

    # ---------------------------------------------------------- downloads
    def download(self, t, fmt=None):
        if t.get("local"):
            return
        if not shutil.which("ffmpeg"):
            self.set_status("FFmpeg not found on PATH - install it to save MP3/FLAC.")
            return
        fmt = fmt or self.settings["default_format"]
        self.dl_counter += 1
        dl = {"id": self.dl_counter, "title": t["title"], "fmt": fmt, "state": "Queued",
              "pct": 0.0, "path": None, "error": "", "track": t}
        self.downloads.append(dl)
        self._update_nav()
        self.set_status(f"Queued {fmt.upper()} download: {t['title']}")
        if self.view_name == "downloads":
            self.show_view("downloads")
        snapshot = dict(self.settings)
        threading.Thread(target=self._download_worker, args=(t, dl, fmt, snapshot), daemon=True).start()

    def _download_worker(self, t, dl, fmt, s):
        with self.dl_slots:
            folder = s["download_dir"]
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception as exc:
                self.ui(lambda e=str(exc): self._dl_fail(dl, e))
                return
            parts = [folder] + (["%(uploader)s"] if s["artist_folders"] else []) + ["%(title)s.%(ext)s"]
            outtmpl = os.path.join(*parts)
            last = {"p": -1}

            def hook(d):
                if d["status"] == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    if total:
                        p = d.get("downloaded_bytes", 0) / total
                        if int(p * 100) != last["p"]:
                            last["p"] = int(p * 100)
                            self.ui(lambda p=p: self._dl_update(dl, "Downloading", p))
                elif d["status"] == "finished":
                    self.ui(lambda: self._dl_update(dl, "Converting", 1.0))

            self.ui(lambda: self._dl_update(dl, "Downloading", 0.0))
            attempts = [True, False] if s["embed_art"] else [False]
            last_err = ""
            for use_art in attempts:
                extract = {"key": "FFmpegExtractAudio", "preferredcodec": fmt}
                if fmt == "mp3":
                    extract["preferredquality"] = str(s["mp3_quality"])
                pps = []
                if use_art:
                    pps.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
                pps.append(extract)
                pps.append({"key": "FFmpegMetadata", "add_metadata": True})
                if use_art:
                    pps.append({"key": "EmbedThumbnail"})
                opts = {
                    "format": "bestaudio/best",
                    "outtmpl": outtmpl,
                    "noplaylist": True,
                    "quiet": True,
                    "no_warnings": True,
                    "writethumbnail": use_art,
                    "progress_hooks": [hook],
                    "postprocessors": pps,
                }
                try:
                    with yt_dlp.YoutubeDL(opts) as y:
                        info = y.extract_info(t["url"], download=True)
                    path = None
                    try:
                        path = info["requested_downloads"][0]["filepath"]
                    except Exception:
                        pass
                    self.ui(lambda p=path: self._dl_done(dl, p))
                    return
                except Exception as exc:
                    last_err = str(exc)
            self.ui(lambda e=last_err: self._dl_fail(dl, e))

    def _dl_update(self, dl, state=None, pct=None):
        if state is not None:
            dl["state"] = state
        if pct is not None:
            dl["pct"] = pct
        w = self.dl_widgets.get(dl["id"])
        if w and self.view_name == "downloads":
            try:
                w["label"].configure(text=self._dl_text(dl))
                w["bar"].set(dl["pct"])
            except Exception:
                pass
        self._update_nav()

    def _dl_done(self, dl, path):
        dl["state"] = "Done"
        dl["pct"] = 1.0
        dl["path"] = path
        self.set_status(f"Saved {dl['fmt'].upper()}: {dl['title']}")
        if self.view_name == "downloads":
            self.show_view("downloads")
        elif self.view_name == "library":
            self._scan_library_async()
        self._update_nav()

    def _dl_fail(self, dl, err):
        dl["state"] = "Failed"
        dl["error"] = err.replace("\n", " ")
        self.set_status(f"Download failed: {dl['title']}")
        if self.view_name == "downloads":
            self.show_view("downloads")
        self._update_nav()


if __name__ == "__main__":
    SonarApp().mainloop()
