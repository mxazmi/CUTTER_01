#!/usr/bin/env python3
"""
CUTTER_01 - Batch Video Cutter / Downloader v2.2

Requirements:
    yt-dlp      pip install yt-dlp  (or yt-dlp.exe next to this app / on PATH)
    ffmpeg      next to this app / on PATH (merging, cutting, MP3)
    deno        recommended: YouTube needs a JavaScript runtime for full speed
    psutil      optional, for the network speed meter (pip install psutil)

Tools are looked up in this order: app folder, app\\bin, app\\tools, then PATH.
"""
import copy
import csv
import ctypes
import importlib.util
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
from collections import deque
from tkinter import ttk, messagebox, filedialog

try:
    import psutil
except ImportError:
    psutil = None

try:
    import winsound
except ImportError:
    winsound = None

# ----------------------------------------------------------------------------
# THEME
# ----------------------------------------------------------------------------
APP_TITLE = "CUTTER_01 - Batch Video Cutter and Downloader"
APP_VERSION = "2.2"

BG_COLOR = "#121212"
PANEL_COLOR = "#1E1E1E"
BORDER_COLOR = "#3A3A3A"
TEXT_COLOR = "#F5F5F5"
ACCENT_RED = "#E32525"
ACCENT_DIM = "#707070"
WARNING_RED = "#FF4444"
WARN_YELLOW = "#FFB400"
GOOD_GREEN = "#4CD964"
TERMINAL_BG = "#050505"
SPLASH_RED = "#E2232A"

PIXEL_FONT = ("Courier New", 10, "bold")
PIXEL_FONT_SM = ("Courier New", 8, "bold")
PIXEL_FONT_LG = ("Courier New", 14, "bold")
PIXEL_FONT_XL = ("Courier New", 22, "bold")

STATUS_COLORS = {
    "IDLE": TEXT_COLOR,
    "QUEUED": ACCENT_DIM,
    "FETCHING": ACCENT_DIM,
    "READY": ACCENT_RED,
    "DOWNLOADING": ACCENT_RED,
    "PROCESSING": TEXT_COLOR,
    "COMPLETE": GOOD_GREEN,
    "SKIPPED": ACCENT_DIM,
    "CANCELLED": WARNING_RED,
    "ERROR": WARNING_RED,
}

# ----------------------------------------------------------------------------
# CONSTANTS
# ----------------------------------------------------------------------------
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DEFAULT_TEMPLATE = "%(title)s_%(id)s.%(ext)s"
FORMATS = ["mp4", "mkv"]
QUALITIES = ["Best (HDR/60fps)", "1080p", "720p", "480p", "Audio MP3 (320kbps)", "Audio Native (Opus/M4A)"]
AUDIO_QUALITIES = ("Audio MP3 (320kbps)", "Audio Native (Opus/M4A)")
CODECS = ["Any", "H.264 (AVC)", "VP9", "AV1"]
COLLISIONS = ["unique", "skip", "overwrite"]
BROWSERS = ["none", "chrome", "firefox", "edge", "brave"]
CUT_MODES = ["precise", "fast"]
CUT_ENCODERS = ["Auto", "CPU (x264)", "NVIDIA NVENC", "Intel QSV", "AMD AMF"]
CUT_PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium"]
HW_ENCODER_NAMES = {"NVIDIA NVENC": "h264_nvenc", "Intel QSV": "h264_qsv", "AMD AMF": "h264_amf"}
HW_ORDER = ["h264_nvenc", "h264_qsv", "h264_amf"]
MEDIA_EXTS = {".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".mov", ".opus", ".flv"}
MAX_LOG_LINES = 1500

# bytes/second -> display value
SPEED_UNITS = {
    "Mbps": 8 / 1e6,        # megabits (what ISPs and speed tests use)
    "MB/s": 1 / 1e6,        # megabytes (what browsers show)
    "MiB/s": 1 / 2 ** 20,   # mebibytes (what yt-dlp shows)
    "Mib/s": 8 / 2 ** 20,   # mebibits
    "Kbps": 8 / 1e3,
    "KB/s": 1 / 1e3,
    "KiB/s": 1 / 1024,
    "Gbps": 8 / 1e9,
}
SPEED_UNIT_NAMES = list(SPEED_UNITS)

PERMANENT_ERRORS = (
    "private video", "video unavailable", "this video is unavailable",
    "has been removed", "is not available", "members-only", "join this channel",
    "sign in to confirm", "confirm your age", "age-restricted",
    "unsupported url", "is not a valid url", "no video formats found",
    "requested format is not available", "copyright",
    "account associated with this video has been terminated",
    "ffmpeg is not installed", "ffmpeg not found", "ffprobe and ffmpeg not found",
    "http error 404", "no such option", "unrecognized arguments",
)

PCT_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")
SPEED_RE = re.compile(r"at\s+(?:~\s*)?([0-9.]+)\s?([KMGT]?)(i?)B/s")
ETA_RE = re.compile(r"ETA\s+(\S+)")
FFTIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
FFSPEED_RE = re.compile(r"speed=\s*([0-9.]+)x")
ARIA_PCT_RE = re.compile(r"^\[#\w+\s+\S+/\S+\((\d+)%\)")
ARIA_DL_RE = re.compile(r"DL:([0-9.]+)([KMGT]?)(i?)B")
ARIA_ETA_RE = re.compile(r"ETA:([0-9hms]+)")
FMT_COUNT_RE = re.compile(r"Downloading (\d+) format\(s\):\s*(\S+)")
DEST_RE = re.compile(r"^\[(download|ExtractAudio|VideoConvertor|VideoRemuxer)\]\s+Destination:\s*(.+)$")
MERGE_RE = re.compile(r'^\[Merger\]\s+Merging formats into "(.+)"')
EXISTS_RE = re.compile(r"^\[download\]\s+(.+?)\s+has already been downloaded")
NOISE_RE = re.compile(r"^\[[\w\-.:]+ @ 0x?[0-9a-fA-F]+\]")
KEEP_RE = re.compile(r"^Stream #\d+:\d+ -> #\d+:\d+")
URL_RE = re.compile(r"https?://\S+", re.I)
RANGE_SPLIT = re.compile(r"\s*(?:-|\u2013|\u2014|\bto\b)\s*", re.I)
GEOMETRY_RE = re.compile(r"^\d{3,4}x\d{3,4}$")

# Filled in by the background boot check
HW = {"checked": False, "encoders": []}
CAPS = {"js_runtimes": True}


def data_dir():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, "CUTTER_01")
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except OSError:
        return os.getcwd()

DATA_DIR = data_dir()
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
QUEUE_FILE = os.path.join(DATA_DIR, "queue.json")

def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)

def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ----------------------------------------------------------------------------
# SMALL HELPERS
# ----------------------------------------------------------------------------
def apply_dark_titlebar(window):
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        for attr in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def open_path(path):
    try:
        if not os.path.exists(path):
            return
        if os.name == "nt":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def reveal_file(path):
    """Open the folder and select the file (Windows), else just open the folder."""
    try:
        if os.name == "nt" and os.path.exists(path):
            subprocess.Popen(["explorer", "/select," + os.path.normpath(path)])
        else:
            open_path(os.path.dirname(path) if os.path.exists(path) else path)
    except Exception:
        pass


def sec_to_str(sec):
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h:
        return "%02d:%02d:%02d" % (h, m, s)
    return "%02d:%02d" % (m, s)

def sec_to_tag(sec):
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h:
        return "%dh%02dm%02ds" % (h, m, s)
    return "%02dm%02ds" % (m, s)


def parse_time(text):
    parts = text.strip().split(":")
    if not text.strip() or len(parts) > 3:
        raise ValueError("bad time")
    total = 0
    for p in parts:
        value = int(p)
        if value < 0:
            raise ValueError("negative")
        total = total * 60 + value
    return total

def parse_range(text):
    parts = RANGE_SPLIT.split(text.strip())
    if len(parts) != 2:
        raise ValueError("bad range")
    return parse_time(parts[0]), parse_time(parts[1])

def valid_url(text):
    return bool(re.match(r"^https?://\S+$", text or "", re.I))

def short(text, n=40):
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "\u2026"

def last_error(text):
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    for line in reversed(lines):
        if "ERROR" in line:
            return re.sub(r"^.*?ERROR:\s*", "", line)[:200]
    return lines[-1][:200] if lines else ""

def is_permanent(text):
    low = (text or "").lower()
    return any(p in low for p in PERMANENT_ERRORS)

def safe_template(template):
    t = (template or "").strip()
    if not t or ".." in t or os.path.isabs(t) or re.match(r"^[A-Za-z]:", t):
        return DEFAULT_TEMPLATE
    if "%(ext)s" not in t:
        t += ".%(ext)s"
    return t

def add_suffix(template, suffix):
    if template.endswith(".%(ext)s"):
        return template[:-8] + suffix + ".%(ext)s"
    return template + suffix

def media_exists(stem):
    folder, base = os.path.split(stem)
    try:
        names = os.listdir(folder or ".")
    except OSError:
        return False
    base = base.lower()
    for name in names:
        root, ext = os.path.splitext(name)
        if root.lower() == base and ext.lower() in MEDIA_EXTS:
            return True
    return False

def id_in_folder(folder, vid):
    try:
        return any(vid in name for name in os.listdir(folder))
    except OSError:
        return True  # unknown -> be safe and run the full check

def is_audio(quality):
    return quality in AUDIO_QUALITIES

def to_bytes(num, prefix, binary):
    base = 1024 if binary else 1000
    power = "KMGT".find(prefix) + 1 if prefix else 0
    return num * (base ** power)

def speed_from_match(m):
    try:
        return to_bytes(float(m.group(1)), m.group(2), m.group(3) == "i")
    except (ValueError, IndexError):
        return None

def format_speed(bytes_per_sec, unit):
    factor = SPEED_UNITS.get(unit, SPEED_UNITS["Mbps"])
    value = max(0.0, bytes_per_sec) * factor
    return ("%.1f %s" if value < 100 else "%.0f %s") % (value, unit)

def vtuple(text):
    return tuple(int(n) for n in re.findall(r"\d+", text or "")[:4])

def overall_pct(stage, count, pct):
    """Combine per-stream percentages (video then audio) into one smooth bar."""
    if count <= 1:
        return pct
    if count == 2:
        return pct * 0.9 if stage <= 0 else 90 + pct * 0.1
    return min(100.0, (min(stage, count - 1) + pct / 100.0) / count * 100.0)


# ----------------------------------------------------------------------------
# TOOL DISCOVERY
# ----------------------------------------------------------------------------
def find_tool(name):
    exe = name + (".exe" if os.name == "nt" else "")
    base = app_dir()
    for folder in (base, os.path.join(base, "bin"), os.path.join(base, "tools")):
        p = os.path.join(folder, exe)
        if os.path.isfile(p):
            return p
    return shutil.which(name)

def is_local_tool(path):
    try:
        return os.path.normcase(os.path.abspath(path)).startswith(os.path.normcase(app_dir()))
    except Exception:
        return False

def ytdlp_base():
    exe = find_tool("yt-dlp")
    if exe:
        return [exe]
    if not getattr(sys, "frozen", False) and importlib.util.find_spec("yt_dlp"):
        return [sys.executable, "-m", "yt_dlp"]
    return None

def tool_args():
    """Extra yt-dlp flags so bundled ffmpeg / a JS runtime are found."""
    args = []
    ff = find_tool("ffmpeg")
    if ff and is_local_tool(ff):
        args += ["--ffmpeg-location", os.path.dirname(ff)]
    if CAPS["js_runtimes"]:
        for name in ("deno", "node", "bun"):
            p = find_tool(name)
            if not p:
                continue
            on_path = shutil.which(name) is not None
            if name == "deno":
                if not on_path:           # yt-dlp already finds deno on PATH
                    args += ["--js-runtimes", "deno:" + p]
            else:
                args += ["--js-runtimes", name if on_path else "%s:%s" % (name, p)]
            break
    return args

def cookie_args(cfg):
    if cfg.browser and cfg.browser != "none":
        return ["--cookies-from-browser", cfg.browser]
    return []

def extra_args(cfg):
    args = []
    if cfg.proxy:
        args.extend(["--proxy", cfg.proxy])
    return args

def format_args(fmt, quality, codec):
    args = []
    if codec == "H.264 (AVC)":
        args.extend(["-S", "vcodec:avc"])
    elif codec == "VP9":
        args.extend(["-S", "vcodec:vp9"])
    elif codec == "AV1":
        args.extend(["-S", "vcodec:av01"])

    if quality == "Audio MP3 (320kbps)":
        return args + ["-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "320K"]
    if quality == "Audio Native (Opus/M4A)":
        return args + ["-f", "ba/b", "-x"]

    height = {"1080p": 1080, "720p": 720, "480p": 480}.get(quality)
    flt = "[height<=%d]" % height if height else ""
    if fmt == "mp4":
        sel = "bv*[ext=mp4]%s+ba[ext=m4a]/b[ext=mp4]%s/bv*%s+ba/b%s" % (flt, flt, flt, flt)
    else:
        sel = "bv*%s+ba/b%s" % (flt, flt)
    return args + ["-f", sel, "--merge-output-format", fmt]

def effective_codec(cfg, is_cut):
    """Precise cuts decode the source, so H.264 (cheap to decode) is preferred over AV1."""
    if (is_cut and cfg.cut_mode == "precise" and cfg.cut_h264
            and cfg.codec == "Any" and not is_audio(cfg.quality)):
        return "H.264 (AVC)"
    return cfg.codec

def pick_encoder(cfg, force_cpu=False):
    if force_cpu or cfg.cut_encoder == "CPU (x264)":
        return "libx264"
    avail = HW["encoders"]
    if cfg.cut_encoder == "Auto":
        return avail[0] if avail else "libx264"
    name = HW_ENCODER_NAMES.get(cfg.cut_encoder)
    return name if name in avail else "libx264"

def encoder_args(enc, cfg):
    crf = cfg.cut_crf
    if enc == "h264_nvenc":
        v = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(crf + 1), "-b:v", "0"]
    elif enc == "h264_qsv":
        v = ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", str(crf + 2)]
    elif enc == "h264_amf":
        q = str(crf + 2)
        v = ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp",
             "-qp_i", q, "-qp_p", q, "-qp_b", q]
    else:
        v = ["-c:v", "libx264", "-preset", cfg.cut_preset, "-crf", str(crf), "-pix_fmt", "yuv420p"]
    return v + ["-c:a", "aac", "-b:a", "192k"]


# ----------------------------------------------------------------------------
# PROCESS POOL
# ----------------------------------------------------------------------------
class ProcessPool:
    def __init__(self):
        self._lock = threading.Lock()
        self._procs = {}

    def register(self, proc, tag=None):
        with self._lock:
            self._procs[proc] = tag

    def unregister(self, proc):
        with self._lock:
            self._procs.pop(proc, None)

    @staticmethod
    def _kill_tree(proc):
        if proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, creationflags=NO_WINDOW)
            else:
                proc.terminate()
        except Exception:
            pass

    def kill(self, tag):
        with self._lock:
            targets = [p for p, t in self._procs.items() if t is tag]
        for p in targets:
            self._kill_tree(p)

    def kill_all(self):
        with self._lock:
            targets = list(self._procs)
        for p in targets:
            self._kill_tree(p)

    def run_capture(self, cmd, timeout=60, tag=None):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        self.register(proc, tag)
        try:
            out, err = proc.communicate(timeout=timeout)
            return proc.returncode, out, err
        except subprocess.TimeoutExpired:
            self._kill_tree(proc)
            try:
                proc.communicate(timeout=5)
            except Exception:
                pass
            return -1, "", "ERROR: timed out"
        finally:
            self.unregister(proc)


def fetch_meta(pool, url, cfg, tag=None):
    base = ytdlp_base()
    if not base:
        raise RuntimeError("yt-dlp not found (pip install yt-dlp)")
    cmd = base + [
        "--encoding", "utf-8", "--no-playlist", "--no-warnings",
        "--socket-timeout", "30", "--retries", "3", "--extractor-retries", "3",
        "--fragment-retries", "10", "--skip-download",
        "--print", "%(duration)s|||%(title)s|||%(id)s",
    ] + tool_args() + cookie_args(cfg) + extra_args(cfg) + [url]
    # Metadata extraction can take longer than a normal HTTP request (e.g. YouTube
    # player/API retries), so don't kill it after a single minute.
    rc, out, err = pool.run_capture(cmd, 120, tag)
    if rc != 0:
        raise RuntimeError(last_error(err) or "yt-dlp exit code %d" % rc)
    for line in out.splitlines():
        if "|||" in line:
            parts = line.split("|||")
            try:
                seconds = int(float(parts[0]))
            except ValueError:
                seconds = 0
            title = parts[1].strip() if len(parts) > 1 else ""
            vid = parts[2].strip() if len(parts) > 2 else ""
            return {"duration": max(0, seconds), "title": title or "UNKNOWN", "id": vid}
    raise RuntimeError("no metadata returned")


# ----------------------------------------------------------------------------
# DEPENDENCY INFO / UPDATE CHECK
# ----------------------------------------------------------------------------
def tool_info(pool, name):
    """Return (path or None, version string)."""
    if name == "yt-dlp":
        base = ytdlp_base()
        if not base:
            return None, ""
        path = base[0] if len(base) == 1 else "python -m yt_dlp"
        cmd = base + ["--version"]
    else:
        path = find_tool(name)
        if not path:
            return None, ""
        cmd = [path, "-version" if name == "ffmpeg" else "--version"]
    try:
        rc, out, err = pool.run_capture(cmd, 20)
    except OSError:
        return path, ""
    lines = [l.strip() for l in (out or err or "").splitlines() if l.strip()]
    if not lines:
        return path, ""
    first = lines[0]
    if name == "ffmpeg":
        m = re.search(r"version\s+(\S+)", first)
        raw = m.group(1) if m else first
        n = re.search(r"\d+(?:\.\d+)+", raw)
        return path, n.group(0) if n else raw
    if name == "deno":
        m = re.search(r"deno\s+(\S+)", first)
        return path, m.group(1) if m else first
    if name == "aria2c":
        m = re.search(r"version\s+(\S+)", first)
        return path, m.group(1) if m else first
    return path, first


def http_get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "CUTTER_01"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def latest_version(name):
    """Return (version, error)."""
    try:
        if name == "yt-dlp":
            data = json.loads(http_get("https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"))
            return str(data.get("tag_name", "")).lstrip("v"), ""
        if name == "deno":
            data = json.loads(http_get("https://api.github.com/repos/denoland/deno/releases/latest"))
            return str(data.get("tag_name", "")).lstrip("v"), ""
        if name == "ffmpeg":
            return http_get("https://www.gyan.dev/ffmpeg/builds/release-version").strip(), ""
    except Exception as e:
        return "", short(str(e), 60)
    return "", "unknown tool"

DOWNLOAD_PAGES = {
    "yt-dlp": "https://github.com/yt-dlp/yt-dlp/releases/latest",
    "deno": "https://github.com/denoland/deno/releases/latest",
    "ffmpeg": "https://www.gyan.dev/ffmpeg/builds/",
}

def update_command(name):
    """Command that installs/updates the tool, or None if it must be done by hand."""
    path = find_tool(name) if name != "yt-dlp" else None
    winget = shutil.which("winget")
    wg = ["--silent", "--accept-source-agreements", "--accept-package-agreements"]
    if name == "yt-dlp":
        base = ytdlp_base()
        if base and len(base) > 1:
            return [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"]
        if base:
            return base + ["-U"]
        return [winget, "install", "--id", "yt-dlp.yt-dlp", "-e"] + wg if winget else None
    if name == "deno":
        if path and (is_local_tool(path) or not winget):
            return [path, "upgrade"]
        if winget:
            return [winget, "upgrade" if path else "install", "--id", "DenoLand.Deno", "-e"] + wg
        return None
    if name == "ffmpeg":
        if path and is_local_tool(path):
            return None
        if winget:
            return [winget, "upgrade" if path else "install", "--id", "Gyan.FFmpeg", "-e"] + wg
        return None
    return None

def detect_hw_encoders(pool):
    ff = find_tool("ffmpeg")
    found = []
    if not ff:
        return found
    try:
        rc, out, err = pool.run_capture([ff, "-hide_banner", "-encoders"], 20)
    except OSError:
        return found
    for enc in HW_ORDER:
        if enc not in (out or ""):
            continue
        cmd = [ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
               "color=c=black:s=640x360:r=30:d=0.5", "-frames:v", "10",
               "-c:v", enc, "-f", "null", "-"]
        try:
            rc, _, _ = pool.run_capture(cmd, 20)
        except OSError:
            continue
        if rc == 0:
            found.append(enc)
    return found


# ----------------------------------------------------------------------------
# SETTINGS
# ----------------------------------------------------------------------------
class AppSettings:
    STR_KEYS = ("out_dir", "name_template", "rate_limit", "proxy", "geometry")
    CHOICES = {
        "format": FORMATS, "quality": QUALITIES, "codec": CODECS, "collision": COLLISIONS,
        "browser": BROWSERS, "cut_mode": CUT_MODES, "cut_encoder": CUT_ENCODERS,
        "cut_preset": CUT_PRESETS, "speed_unit": SPEED_UNIT_NAMES,
    }
    BOOL_KEYS = ("sound", "open_when_done", "save_thumb", "save_meta", "allow_playlist",
                 "cut_h264", "use_aria2c", "verbose_log", "auto_update_check")
    INT_KEYS = {"retries": (0, 10), "threads": (1, 16), "cut_crf": (10, 30)}

    def __init__(self):
        self.out_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        self.format = "mp4"
        self.quality = "Best (HDR/60fps)"
        self.codec = "Any"
        self.name_template = DEFAULT_TEMPLATE
        self.collision = "unique"
        self.retries = 3
        self.rate_limit = ""
        self.browser = "none"
        self.proxy = ""
        self.threads = 4
        self.sound = True
        self.open_when_done = False
        self.save_thumb = False
        self.save_meta = False
        self.allow_playlist = False
        # cutting
        self.cut_mode = "precise"
        self.cut_encoder = "Auto"
        self.cut_preset = "veryfast"
        self.cut_crf = 18
        self.cut_h264 = True
        # misc
        self.use_aria2c = False
        self.speed_unit = "Mbps"
        self.verbose_log = False
        self.auto_update_check = True
        self.geometry = ""
        self.load()

    def load(self):
        if not os.path.exists(SETTINGS_FILE):
            return
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for key in self.STR_KEYS:
            if isinstance(data.get(key), str):
                setattr(self, key, data[key])
        for key, choices in self.CHOICES.items():
            if data.get(key) in choices:
                setattr(self, key, data[key])
        for key in self.BOOL_KEYS:
            if isinstance(data.get(key), bool):
                setattr(self, key, data[key])
        for key, (lo, hi) in self.INT_KEYS.items():
            v = data.get(key)
            if isinstance(v, int) and not isinstance(v, bool):
                setattr(self, key, max(lo, min(hi, v)))
        self.name_template = safe_template(self.name_template)
        if not GEOMETRY_RE.match(self.geometry or ""):
            self.geometry = ""

    def save(self):
        keys = list(self.STR_KEYS) + list(self.CHOICES) + list(self.BOOL_KEYS) + list(self.INT_KEYS)
        data = {k: getattr(self, k) for k in keys}
        try:
            tmp = SETTINGS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, SETTINGS_FILE)
        except OSError:
            pass


# ----------------------------------------------------------------------------
# SPLASH
# ----------------------------------------------------------------------------
def build_logo():
    width = 121
    def bar(x0, x1, n):
        return [(" " * x0 + "#" * (x1 - x0)).ljust(width)] * n

    blank = [" " * width] * 8
    rows = (bar(28, 111, 8) + bar(10, 111, 3) + bar(10, 33, 8) + blank +
            bar(10, 33, 8) + bar(10, 111, 3) + bar(28, 111, 8))
    pad = [" " * width] * 6
    return "\n".join(pad + rows + pad)


class SplashScreen:
    def __init__(self, root, on_done):
        self.top = tk.Toplevel(root)
        self.top.overrideredirect(True)
        self.top.configure(bg=TERMINAL_BG, highlightbackground=SPLASH_RED, highlightthickness=2)
        w, h = 900, 550
        x = (self.top.winfo_screenwidth() - w) // 2
        y = (self.top.winfo_screenheight() - h) // 2
        self.top.geometry("%dx%d+%d+%d" % (w, h, x, y))

        content_frame = tk.Frame(self.top, bg=TERMINAL_BG)
        content_frame.pack(expand=True, fill="both")

        tk.Label(content_frame, text=build_logo(), font=("Courier New", 5, "bold"), bg=TERMINAL_BG,
                 fg=SPLASH_RED, justify="center").pack(expand=True)

        self.lbl_status = tk.Label(content_frame, text="INITIALIZING SYSTEM...", font=("Courier New", 8, "bold"),
                                   bg=TERMINAL_BG, fg=ACCENT_DIM)
        self.lbl_status.pack(side="bottom", pady=15)

        threading.Thread(target=self._boot_checks, args=(on_done,), daemon=True).start()

    def _boot_checks(self, on_done):
        time.sleep(0.25)
        checks = (
            ("yt-dlp", bool(ytdlp_base()), "WARNING: yt-dlp not found."),
            ("ffmpeg", bool(find_tool("ffmpeg")), "WARNING: ffmpeg not found."),
            ("JS runtime", bool(find_tool("deno") or find_tool("node") or find_tool("bun")),
             "WARNING: no JS runtime (deno) - YouTube may be slow."),
        )
        for name, ok, warn in checks:
            self.update_status("CHECKING: %s..." % name)
            time.sleep(0.2)
            self.update_status("%s found." % name if ok else warn)
            time.sleep(0.2)
        if not psutil:
            self.update_status("INFO: network monitor disabled (psutil missing).")
            time.sleep(0.2)
        self.update_status("SYSTEM READY.")
        time.sleep(0.3)
        try:
            self.top.after(0, lambda: (self.top.destroy(), on_done()))
        except Exception:
            pass

    def update_status(self, text):
        try:
            self.top.after(0, lambda: self.lbl_status.config(text=">> " + text))
        except Exception:
            pass


# ----------------------------------------------------------------------------
# JOB ROW
# ----------------------------------------------------------------------------
class JobItem:
    def __init__(self, app, parent):
        self.app = app
        self.parent = parent
        self.url = ""
        self.vid = ""
        self.title = "UNKNOWN"
        self.duration_sec = 0
        self.start_sec = 0
        self.end_sec = 0
        self.status = "IDLE"
        self.output_path = ""
        self.removed = False
        self.dragging = None
        self.canvas_w = 100
        self.canvas_h = 30
        self._suppress = False

        self._url_var = tk.StringVar()
        self._url_var.trace_add("write", self._on_url_type)
        self._type_timer = None

        self._build()

    def _build(self):
        self.frame = tk.Frame(self.parent, bg=PANEL_COLOR, highlightbackground=BORDER_COLOR, highlightthickness=1)
        self.frame.pack(fill="x", padx=10, pady=5)

        r1 = tk.Frame(self.frame, bg=PANEL_COLOR)
        r1.pack(fill="x", padx=10, pady=(10, 5))
        tk.Label(r1, text="URL:", font=PIXEL_FONT, bg=PANEL_COLOR, fg=TEXT_COLOR).pack(side="left")

        self.entry_url = tk.Entry(r1, font=PIXEL_FONT, bg=BG_COLOR, fg=TEXT_COLOR, insertbackground=ACCENT_RED,
                                  relief="flat", highlightbackground=BORDER_COLOR, highlightthickness=1,
                                  textvariable=self._url_var)
        self.entry_url.pack(side="left", fill="x", expand=True, padx=5)

        self.entry_url.bind("<Return>", lambda e: self.auto_fetch())
        self.entry_url.bind("<FocusOut>", lambda e: self.auto_fetch())

        for text, cmd, color in (("PASTE", self.paste_clipboard, TEXT_COLOR),
                                 (" X ", lambda: self.app.remove_job(self), WARNING_RED)):
            tk.Button(r1, text=text, font=PIXEL_FONT_SM, bg=BORDER_COLOR, fg=color, relief="flat",
                      command=cmd).pack(side="left", padx=2)

        r2 = tk.Frame(self.frame, bg=PANEL_COLOR)
        r2.pack(fill="x", padx=10, pady=2)
        self.lbl_title = tk.Label(r2, text="TITLE: PENDING", font=PIXEL_FONT, bg=PANEL_COLOR, fg=TEXT_COLOR, anchor="w")
        self.lbl_title.pack(side="left", fill="x", expand=True)

        self.lbl_status = tk.Label(r2, text="[IDLE]", font=PIXEL_FONT, bg=PANEL_COLOR, fg=TEXT_COLOR)
        self.lbl_status.pack(side="right")
        self.btn_show = tk.Button(r2, text="SHOW FILE", font=PIXEL_FONT_SM, bg=BORDER_COLOR, fg=GOOD_GREEN,
                                  relief="flat", command=self.reveal)

        r3 = tk.Frame(self.frame, bg=PANEL_COLOR)
        r3.pack(fill="x", padx=10, pady=5)
        tk.Label(r3, text="RANGE:", font=PIXEL_FONT, bg=PANEL_COLOR, fg=TEXT_COLOR).pack(side="left")
        self.entry_range = tk.Entry(r3, font=PIXEL_FONT, bg=BG_COLOR, fg=ACCENT_RED, insertbackground=ACCENT_RED,
                                    relief="flat", highlightbackground=BORDER_COLOR, highlightthickness=1,
                                    width=18, justify="center")
        self.entry_range.insert(0, "00:00 - 00:00")
        self.entry_range.pack(side="left", padx=10)
        self.entry_range.bind("<Return>", self.on_range_edit)
        self.entry_range.bind("<FocusOut>", self.on_range_edit)
        tk.Button(r3, text="FULL", font=PIXEL_FONT_SM, bg=BORDER_COLOR, fg=TEXT_COLOR, relief="flat",
                  command=self.reset_range).pack(side="left")
        self.lbl_info = tk.Label(r3, text="", font=PIXEL_FONT_SM, bg=PANEL_COLOR, fg=ACCENT_DIM)
        self.lbl_info.pack(side="right")

        self.canvas = tk.Canvas(self.frame, height=self.canvas_h, bg=BG_COLOR, highlightthickness=0)
        self.canvas.pack(fill="x", expand=True, pady=(0, 10), padx=10)
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        self.canvas.bind("<ButtonPress-1>", self.on_timeline_press)
        self.canvas.bind("<B1-Motion>", self.on_timeline_drag)
        self.canvas.bind("<ButtonRelease-1>", lambda e: setattr(self, "dragging", None))

    # --- url handling -------------------------------------------------------
    def set_url(self, url):
        """Set the URL without triggering the typing auto-fetch."""
        self._suppress = True
        try:
            self.entry_url.delete(0, tk.END)
            self.entry_url.insert(0, url)
        finally:
            self._suppress = False

    def _on_url_type(self, *args):
        if self._suppress:
            return
        if self._type_timer:
            self.frame.after_cancel(self._type_timer)
        self._type_timer = self.frame.after(1200, self.auto_fetch)

    def auto_fetch(self):
        url = self.entry_url.get().strip()
        if valid_url(url) and url != self.url and self.status not in ("FETCHING", "DOWNLOADING"):
            self.fetch()

    def set_status(self, code, detail=""):
        changed = code != self.status
        self.status = code
        text = code if not detail else "%s: %s" % (code, short(detail, 38))
        self.lbl_status.config(text="[" + text + "]", fg=STATUS_COLORS.get(code, TEXT_COLOR))
        if code != "COMPLETE":
            self.btn_show.pack_forget()
        if changed:
            self.app.ui(self.app.eval_btn_state)

    def show_output_button(self):
        if self.output_path:
            self.btn_show.pack(side="right", padx=8)

    def reveal(self):
        if self.output_path and os.path.exists(self.output_path):
            reveal_file(self.output_path)
        else:
            open_path(self.app.settings.out_dir)

    def set_title_label(self):
        if self.title == "UNKNOWN":
            self.lbl_title.config(text="TITLE: PENDING")
        else:
            self.lbl_title.config(text="TITLE: " + short(self.title, 70))

    def refresh_all(self):
        self.set_title_label()
        self.update_timeline_ui()

    def paste_clipboard(self):
        try:
            text = self.frame.clipboard_get()
        except tk.TclError:
            return
        urls = []
        for u in URL_RE.findall(text) or ([text.strip()] if text.strip() else []):
            if u not in urls:
                urls.append(u)
        if not urls:
            return

        if self._type_timer:
            self.frame.after_cancel(self._type_timer)

        self.set_url(urls[0])
        self.fetch()

        for extra in urls[1:]:
            self.app.add_job(url=extra, fetch=len(urls) <= 6)
        if len(urls) > 1:
            self.app.log(">> SYSTEM: Pasted %d URLs." % len(urls))

    def fetch(self):
        url = self.entry_url.get().strip()
        if not valid_url(url):
            self.set_status("ERROR", "NO VALID URL")
            return

        if self.url and url != self.url:       # a different video: forget the old one
            self.title, self.duration_sec, self.vid = "UNKNOWN", 0, ""
            self.start_sec = self.end_sec = 0
            self.refresh_all()
        self.url = url
        self.set_status("FETCHING")
        self.app.log(">> SYSTEM: Fetching metadata for " + short(url, 30))
        threading.Thread(target=self._t_fetch, args=(url,), daemon=True).start()

    def _t_fetch(self, url):
        try:
            with self.app.fetch_sem:
                if self.removed:
                    return
                meta = fetch_meta(self.app.pool, url, self.app.settings, tag=self)
            if self.removed:
                return
            self.absorb_meta(meta)
            self.app.ui(self._after_fetch)
        except Exception as e:
            if not self.removed:
                self.app.ui(self._fetch_failed, str(e))

    def absorb_meta(self, meta):
        self.title = meta["title"]
        self.duration_sec = meta["duration"]
        self.vid = meta.get("id", "")
        if self.duration_sec > 0:
            if self.end_sec <= 0 or self.end_sec > self.duration_sec:
                self.end_sec = self.duration_sec
            if self.start_sec >= self.end_sec:
                self.start_sec = 0

    def _after_fetch(self):
        self.refresh_all()
        self.set_status("READY", "" if self.duration_sec else "DURATION UNKNOWN")
        self.app.log(">> SYSTEM: Metadata acquired -> " + self.title)

    def _fetch_failed(self, msg):
        self.set_status("ERROR", msg)
        self.app.log(">> ERROR: " + (msg or "Failed to retrieve metadata."))
        if "sign in" in msg.lower():
            self.app.log(">> HINT: Try SETTINGS -> NETWORK -> COOKIES to use your browser login.")

    # --- range / timeline ---------------------------------------------------
    def is_cut(self):
        if self.end_sec <= self.start_sec:
            return False
        if self.duration_sec > 0:
            return self.start_sec > 0 or self.end_sec < self.duration_sec
        return True

    def reset_range(self):
        if self.duration_sec > 0:
            self.start_sec, self.end_sec = 0, self.duration_sec
        else:
            self.start_sec = self.end_sec = 0
        self.update_timeline_ui()

    def update_timeline_ui(self):
        self.draw_timeline()
        if self.end_sec > 0:
            text = "%s - %s" % (sec_to_str(self.start_sec), sec_to_str(self.end_sec))
            info = "CLIP: " + sec_to_str(self.end_sec - self.start_sec)
        else:
            text, info = "00:00 - 00:00", ""
        self.entry_range.delete(0, tk.END)
        self.entry_range.insert(0, text)
        self.lbl_info.config(text=info)

    def on_range_edit(self, event=None):
        try:
            s, e = parse_range(self.entry_range.get())
            if self.duration_sec > 0:
                e = min(e, self.duration_sec)
            if s < e:
                self.start_sec, self.end_sec = s, e
        except ValueError:
            pass
        self.update_timeline_ui()

    def on_canvas_resize(self, event):
        if event.width > 20:
            self.canvas_w = event.width
            self.draw_timeline()

    def _x(self, sec):
        return 10 + (sec / self.duration_sec) * (self.canvas_w - 20)

    def draw_timeline(self):
        c, mid = self.canvas, self.canvas_h // 2
        c.delete("all")
        c.create_line(10, mid, self.canvas_w - 10, mid, fill=BORDER_COLOR, width=4)
        if self.duration_sec <= 0:
            return
        x1, x2 = self._x(self.start_sec), self._x(self.end_sec)
        c.create_line(x1, mid, x2, mid, fill=ACCENT_DIM, width=4)
        for x in (x1, x2):
            c.create_rectangle(x - 4, 4, x + 4, self.canvas_h - 4, fill=ACCENT_RED, outline="")

    def on_timeline_press(self, event):
        if self.duration_sec <= 0:
            return
        d1 = abs(event.x - self._x(self.start_sec))
        d2 = abs(event.x - self._x(self.end_sec))
        if d1 < d2 and d1 < 15:
            self.dragging = "start"
        elif d2 <= d1 and d2 < 15:
            self.dragging = "end"

    def on_timeline_drag(self, event):
        if not self.dragging or self.duration_sec <= 0:
            return
        usable = self.canvas_w - 20
        x = max(10, min(event.x, self.canvas_w - 10))
        sec = int(((x - 10) / usable) * self.duration_sec)
        if self.dragging == "start":
            self.start_sec = min(max(0, sec), self.end_sec - 1)
        else:
            self.end_sec = max(min(self.duration_sec, sec), self.start_sec + 1)
        self.update_timeline_ui()


# ----------------------------------------------------------------------------
# DIALOGS
# ----------------------------------------------------------------------------
def make_modal(top, parent):
    top.transient(parent)
    apply_dark_titlebar(top)
    try:
        top.wait_visibility()
        top.grab_set()
    except tk.TclError:
        pass


class CsvGuideWindow:
    def __init__(self, parent):
        self.top = tk.Toplevel(parent)
        self.top.title("CSV_FORMAT_GUIDE")
        self.top.geometry("520x380")
        self.top.configure(bg=BG_COLOR)
        make_modal(self.top, parent)
        tk.Label(self.top, text="CSV BATCH TEMPLATE GUIDE", font=PIXEL_FONT_LG, bg=BG_COLOR, fg=ACCENT_RED).pack(pady=10)
        desc = ("One row = one download task:\n\n"
                "Video_URL, Start_Time, End_Time\n\n"
                "Example:\n"
                "https://youtu.be/example, 00:00, 01:30\n"
                "https://youtu.be/example2, 1:00, 2:45\n"
                "https://youtu.be/example3\n\n"
                "- Times can use mm:ss, hh:mm:ss, or seconds (90)\n"
                "- Times are optional (no time range = full video)\n"
                "- Header rows, blank rows, and rows starting with # are skipped automatically\n"
                "- TXT files with one URL per row are also supported")
        tk.Label(self.top, text=desc, font=PIXEL_FONT, bg=BG_COLOR, fg=TEXT_COLOR, justify="left").pack(padx=20, pady=5, anchor="w")
        tk.Button(self.top, text="CLOSE", font=PIXEL_FONT, bg=BORDER_COLOR, fg=TEXT_COLOR, relief="flat",
                  command=self.top.destroy).pack(pady=15, ipadx=10, ipady=3)


class SettingsWindow:
    def __init__(self, parent, settings, on_save):
        self.settings = settings
        self.on_save = on_save
        self.top = tk.Toplevel(parent)
        self.top.title("SYSTEM_SETTINGS")
        self.top.geometry("700x600")
        self.top.configure(bg=BG_COLOR)
        make_modal(self.top, parent)

        tk.Label(self.top, text="CONFIGURATION_PANEL", font=PIXEL_FONT_LG, bg=BG_COLOR, fg=TEXT_COLOR).pack(pady=8)
        nb = ttk.Notebook(self.top)
        nb.pack(fill="both", expand=True, padx=12, pady=(0, 4))

        t_dl = self._tab(nb, "DOWNLOAD")
        t_cut = self._tab(nb, "CUTTING")
        t_net = self._tab(nb, "NETWORK")
        t_app = self._tab(nb, "APP")

        # ---- DOWNLOAD
        self._label(t_dl, 0, "DIR:")
        self.e_dir = self._entry(t_dl, 0, settings.out_dir)
        tk.Button(t_dl, text="...", font=PIXEL_FONT, bg=BORDER_COLOR, fg=TEXT_COLOR, relief="flat",
                  command=self.browse).grid(row=0, column=2, padx=(5, 0))
        self._label(t_dl, 1, "FORMAT:")
        self.cb_fmt = self._combo(t_dl, 1, FORMATS, settings.format)
        self._label(t_dl, 2, "QUALITY:")
        self.cb_q = self._combo(t_dl, 2, QUALITIES, settings.quality)
        self._label(t_dl, 3, "CODEC:")
        self.cb_codec = self._combo(t_dl, 3, CODECS, settings.codec)
        self._label(t_dl, 4, "FILE TPL:")
        self.e_tpl = self._entry(t_dl, 4, settings.name_template)
        self._label(t_dl, 5, "EXISTING:")
        self.cb_col = self._combo(t_dl, 5, COLLISIONS, settings.collision)
        self._label(t_dl, 6, "RETRIES:")
        self.e_retries = self._entry(t_dl, 6, str(settings.retries))
        self.v_thumb = tk.BooleanVar(value=settings.save_thumb)
        self.v_meta = tk.BooleanVar(value=settings.save_meta)
        self.v_playlist = tk.BooleanVar(value=settings.allow_playlist)
        self._check(t_dl, 7, "DOWNLOAD MAX-RES THUMBNAIL (Cover Art)", self.v_thumb)
        self._check(t_dl, 8, "ARCHIVE METADATA (Description, Comments & JSON)", self.v_meta)
        self._check(t_dl, 9, "ALLOW PLAYLIST / CHANNEL DOWNLOADING", self.v_playlist)
        self._note(t_dl, 10, "* CODEC: force a specific video codec (Any = best available).\n"
                             "* EXISTING: unique = save a copy, skip = leave it, overwrite = replace.")

        # ---- CUTTING
        self._label(t_cut, 0, "CUT MODE:")
        self.cb_cutmode = self._combo(t_cut, 0, CUT_MODES, settings.cut_mode)
        self._label(t_cut, 1, "ENCODER:")
        self.cb_enc = self._combo(t_cut, 1, CUT_ENCODERS, settings.cut_encoder)
        self._label(t_cut, 2, "CPU PRESET:")
        self.cb_preset = self._combo(t_cut, 2, CUT_PRESETS, settings.cut_preset)
        self._label(t_cut, 3, "QUALITY CRF:")
        self.e_crf = self._entry(t_cut, 3, str(settings.cut_crf))
        self.v_h264 = tk.BooleanVar(value=settings.cut_h264)
        self._check(t_cut, 4, "PREFER H.264 SOURCE FOR PRECISE CUTS (much faster decode)", self.v_h264)
        if not HW["checked"]:
            hw = "DETECTING GPU ENCODERS..."
        elif HW["encoders"]:
            hw = "DETECTED GPU ENCODERS: " + ", ".join(HW["encoders"])
        else:
            hw = "NO GPU ENCODER DETECTED (CPU x264 will be used)"
        tk.Label(t_cut, text=hw, font=PIXEL_FONT_SM, bg=BG_COLOR, fg=GOOD_GREEN if HW["encoders"] else WARN_YELLOW,
                 anchor="w").grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 2))
        self._note(t_cut, 6,
                   "* precise = frame-accurate cut (re-encodes the clip). Default.\n"
                   "* fast = copies the stream, finishes in seconds, but cut points\n"
                   "  snap to the nearest keyframe (can be 1-3 s off).\n"
                   "* ENCODER: Auto uses your GPU when one works, otherwise CPU.\n"
                   "  If a GPU encode fails the app retries with CPU automatically.\n"
                   "* CRF: lower = better quality / bigger file. 18 is near-lossless.\n"
                   "* PRESET: faster presets cut quicker with a slightly bigger file.")

        # ---- NETWORK
        self._label(t_net, 0, "THREADS (-N):")
        self.e_threads = self._entry(t_net, 0, str(settings.threads))
        self._label(t_net, 1, "LIMIT RATE:")
        self.e_rate = self._entry(t_net, 1, settings.rate_limit)
        self._label(t_net, 2, "COOKIES:")
        self.cb_browser = self._combo(t_net, 2, BROWSERS, settings.browser)
        self._label(t_net, 3, "PROXY:")
        self.e_proxy = self._entry(t_net, 3, settings.proxy)
        self._label(t_net, 4, "SPEED UNIT:")
        self.cb_unit = self._combo(t_net, 4, SPEED_UNIT_NAMES, settings.speed_unit)
        self.v_aria = tk.BooleanVar(value=settings.use_aria2c)
        self._check(t_net, 5, "USE aria2c FOR FULL DOWNLOADS (experimental, needs aria2c)", self.v_aria)
        self._note(t_net, 6,
                   "* SPEED UNIT: Mbps = megabits (ISP / speed tests), MB/s = megabytes\n"
                   "  (browsers), MiB/s = mebibytes (yt-dlp), Mib/s = mebibits.\n"
                   "  You can also click the NET_SPEED label to cycle units.\n"
                   "* THREADS: parallel fragments (only helps segmented streams).\n"
                   "* COOKIES: reading browser cookies slows every request; use only when\n"
                   "  a video needs your login.\n"
                   "* PROXY: HTTP/SOCKS proxy, LIMIT RATE like 500K or 2M.")

        # ---- APP
        self.v_sound = tk.BooleanVar(value=settings.sound)
        self.v_open = tk.BooleanVar(value=settings.open_when_done)
        self.v_verbose = tk.BooleanVar(value=settings.verbose_log)
        self.v_autoupd = tk.BooleanVar(value=settings.auto_update_check)
        self._check(t_app, 0, "BEEP WHEN BATCH FINISHES", self.v_sound)
        self._check(t_app, 1, "OPEN FOLDER WHEN FINISHED", self.v_open)
        self._check(t_app, 2, "VERBOSE LOG (show full yt-dlp / ffmpeg output)", self.v_verbose)
        self._check(t_app, 3, "CHECK FOR TOOL UPDATES AT STARTUP", self.v_autoupd)
        self._note(t_app, 4, "* Updates: use the UPDATES button in the main window to check and\n"
                             "  update yt-dlp, ffmpeg and deno.")

        tk.Button(self.top, text="SAVE & APPLY", font=PIXEL_FONT, bg=ACCENT_RED, fg=TEXT_COLOR, relief="flat",
                  command=self.save).pack(pady=10, ipadx=10, ipady=5)

    # --- builders -----------------------------------------------------------
    def _tab(self, nb, title):
        f = tk.Frame(nb, bg=BG_COLOR)
        f.columnconfigure(1, weight=1)
        nb.add(f, text="  %s  " % title)
        f.configure(padx=14, pady=10)
        return f

    def _label(self, tab, row, text):
        tk.Label(tab, text=text, font=PIXEL_FONT, bg=BG_COLOR, fg=TEXT_COLOR).grid(
            row=row, column=0, sticky="w", pady=5, padx=(0, 10))

    def _entry(self, tab, row, value):
        e = tk.Entry(tab, font=PIXEL_FONT, bg=PANEL_COLOR, fg=TEXT_COLOR, insertbackground=ACCENT_RED,
                     relief="flat", highlightbackground=BORDER_COLOR, highlightthickness=1)
        e.grid(row=row, column=1, sticky="ew", pady=5)
        e.insert(0, value)
        return e

    def _combo(self, tab, row, values, value):
        c = ttk.Combobox(tab, values=values, state="readonly", font=PIXEL_FONT, width=24)
        c.set(value)
        c.grid(row=row, column=1, sticky="w", pady=5)
        return c

    def _check(self, tab, row, text, var):
        tk.Checkbutton(tab, text=text, variable=var, font=PIXEL_FONT, bg=BG_COLOR, fg=TEXT_COLOR,
                       selectcolor=PANEL_COLOR, activebackground=BG_COLOR, activeforeground=TEXT_COLOR,
                       highlightthickness=0).grid(row=row, column=0, columnspan=3, sticky="w", pady=2)

    def _note(self, tab, row, text):
        tk.Label(tab, text=text, font=PIXEL_FONT_SM, bg=BG_COLOR, fg=ACCENT_DIM, justify="left",
                 anchor="w").grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def browse(self):
        d = filedialog.askdirectory(initialdir=self.settings.out_dir, parent=self.top)
        if d:
            self.e_dir.delete(0, tk.END)
            self.e_dir.insert(0, d)

    def _int(self, entry, lo, hi, name):
        try:
            value = int(entry.get().strip())
            if not lo <= value <= hi:
                raise ValueError
            return value
        except ValueError:
            messagebox.showerror("ERROR", "%s must be a number from %d to %d." % (name, lo, hi), parent=self.top)
            return None

    def save(self):
        threads = self._int(self.e_threads, 1, 16, "Threads")
        if threads is None:
            return
        retries = self._int(self.e_retries, 0, 10, "Retries")
        if retries is None:
            return
        crf = self._int(self.e_crf, 10, 30, "Quality CRF")
        if crf is None:
            return

        rate = self.e_rate.get().strip().upper()
        if rate and not re.match(r"^\d+(\.\d+)?[KMG]?$", rate):
            messagebox.showerror("ERROR", "Limit rate must look like 500K or 2M.", parent=self.top)
            return

        out_dir = self.e_dir.get().strip()
        if not out_dir:
            messagebox.showerror("ERROR", "Output directory is empty.", parent=self.top)
            return

        s = self.settings
        s.out_dir = out_dir
        s.format = self.cb_fmt.get()
        s.quality = self.cb_q.get()
        s.codec = self.cb_codec.get()
        s.name_template = safe_template(self.e_tpl.get())
        s.collision = self.cb_col.get()
        s.retries = retries
        s.threads = threads
        s.rate_limit = rate
        s.browser = self.cb_browser.get()
        s.proxy = self.e_proxy.get().strip()
        s.speed_unit = self.cb_unit.get()
        s.use_aria2c = self.v_aria.get()
        s.cut_mode = self.cb_cutmode.get()
        s.cut_encoder = self.cb_enc.get()
        s.cut_preset = self.cb_preset.get()
        s.cut_crf = crf
        s.cut_h264 = self.v_h264.get()
        s.sound = self.v_sound.get()
        s.open_when_done = self.v_open.get()
        s.verbose_log = self.v_verbose.get()
        s.auto_update_check = self.v_autoupd.get()
        s.save_thumb = self.v_thumb.get()
        s.save_meta = self.v_meta.get()
        s.allow_playlist = self.v_playlist.get()

        s.save()
        self.on_save()
        self.top.destroy()


class DepsWindow:
    """Shows installed vs latest versions of yt-dlp / ffmpeg / deno and can update them."""
    TOOLS = ("yt-dlp", "ffmpeg", "deno")
    LABELS = {"yt-dlp": "yt-dlp", "ffmpeg": "ffmpeg", "deno": "deno (JS runtime)"}

    def __init__(self, parent, app):
        self.app = app
        self.busy = False
        self.top = tk.Toplevel(parent)
        self.top.title("DEPENDENCY_UPDATES")
        self.top.geometry("780x560")
        self.top.configure(bg=BG_COLOR)
        make_modal(self.top, parent)

        tk.Label(self.top, text="DEPENDENCIES", font=PIXEL_FONT_LG, bg=BG_COLOR, fg=TEXT_COLOR).pack(pady=(10, 6))
        grid = tk.Frame(self.top, bg=BG_COLOR)
        grid.pack(fill="x", padx=15)
        grid.columnconfigure(4, weight=1)
        for col, text in enumerate(("TOOL", "INSTALLED", "LATEST", "STATUS", "")):
            tk.Label(grid, text=text, font=PIXEL_FONT_SM, bg=BG_COLOR, fg=ACCENT_DIM, anchor="w").grid(
                row=0, column=col, sticky="w", padx=(0, 14), pady=(0, 4))

        self.rows = {}
        for i, name in enumerate(self.TOOLS, 1):
            lbl_name = tk.Label(grid, text=self.LABELS[name], font=PIXEL_FONT, bg=BG_COLOR, fg=TEXT_COLOR, anchor="w")
            lbl_inst = tk.Label(grid, text="...", font=PIXEL_FONT, bg=BG_COLOR, fg=TEXT_COLOR, anchor="w")
            lbl_late = tk.Label(grid, text="...", font=PIXEL_FONT, bg=BG_COLOR, fg=TEXT_COLOR, anchor="w")
            lbl_stat = tk.Label(grid, text="CHECKING...", font=PIXEL_FONT, bg=BG_COLOR, fg=ACCENT_DIM, anchor="w")
            btn = tk.Button(grid, text="UPDATE", font=PIXEL_FONT_SM, bg=BORDER_COLOR, fg=TEXT_COLOR, relief="flat",
                            state="disabled", command=lambda n=name: self.update_tool(n))
            for col, w in enumerate((lbl_name, lbl_inst, lbl_late, lbl_stat)):
                w.grid(row=i, column=col, sticky="w", padx=(0, 14), pady=6)
            btn.grid(row=i, column=4, sticky="w", pady=6)
            self.rows[name] = (lbl_inst, lbl_late, lbl_stat, btn)

        bar = tk.Frame(self.top, bg=BG_COLOR)
        bar.pack(fill="x", padx=15, pady=8)
        tk.Button(bar, text="CHECK AGAIN", font=PIXEL_FONT_SM, bg=BORDER_COLOR, fg=TEXT_COLOR, relief="flat",
                  command=self.check).pack(side="left")
        tk.Button(bar, text="OPEN TOOLS FOLDER", font=PIXEL_FONT_SM, bg=BORDER_COLOR, fg=TEXT_COLOR, relief="flat",
                  command=lambda: open_path(app_dir())).pack(side="left", padx=6)
        tk.Button(bar, text="CLOSE", font=PIXEL_FONT_SM, bg=BORDER_COLOR, fg=TEXT_COLOR, relief="flat",
                  command=self.top.destroy).pack(side="right")

        self.txt = tk.Text(self.top, font=PIXEL_FONT_SM, bg=TERMINAL_BG, fg=ACCENT_DIM, relief="flat",
                           state="disabled", wrap="word", height=14)
        self.txt.pack(fill="both", expand=True, padx=15, pady=(0, 12))
        self.append("Tools are searched in the app folder first, then PATH.\n"
                    "Updating while a batch is running is blocked.")
        self.check()

    def append(self, text):
        self.txt.config(state="normal")
        self.txt.insert(tk.END, text + "\n")
        self.txt.see(tk.END)
        self.txt.config(state="disabled")

    def check(self):
        if self.busy:
            return
        self.busy = True
        for name in self.TOOLS:
            lbl_inst, lbl_late, lbl_stat, btn = self.rows[name]
            lbl_stat.config(text="CHECKING...", fg=ACCENT_DIM)
            btn.config(state="disabled")
        threading.Thread(target=self._t_check, daemon=True).start()

    def _t_check(self):
        for name in self.TOOLS:
            path, ver = tool_info(self.app.pool, name)
            latest, err = latest_version(name)
            self.app.ui(self._show_row, name, path, ver, latest, err)
        self.app.ui(self._check_done)

    def _check_done(self):
        self.busy = False

    def _show_row(self, name, path, ver, latest, err):
        lbl_inst, lbl_late, lbl_stat, btn = self.rows[name]
        lbl_inst.config(text=ver or ("?" if path else "-"))
        lbl_late.config(text=latest or "?")
        if not path:
            lbl_stat.config(text="MISSING", fg=WARNING_RED)
            btn.config(text="INSTALL", state="normal")
        elif latest and ver and vtuple(ver) < vtuple(latest):
            lbl_stat.config(text="UPDATE AVAILABLE", fg=WARN_YELLOW)
            btn.config(text="UPDATE", state="normal")
        elif latest and ver:
            lbl_stat.config(text="UP TO DATE", fg=GOOD_GREEN)
            btn.config(text="UPDATE", state="normal")
        else:
            lbl_stat.config(text="CANNOT COMPARE" + (" (%s)" % err if err else ""), fg=ACCENT_DIM)
            btn.config(text="UPDATE", state="normal")

    def update_tool(self, name):
        if self.busy:
            return
        if self.app.downloading:
            messagebox.showwarning("BATCH RUNNING", "Stop the batch before updating tools.", parent=self.top)
            return
        cmd = update_command(name)
        if not cmd:
            self.append("%s must be updated manually. Opening the download page..." % name)
            if name == "ffmpeg":
                self.append("Replace ffmpeg.exe / ffprobe.exe in the tools folder with the new build.")
            webbrowser.open(DOWNLOAD_PAGES[name])
            return
        self.busy = True
        for n in self.TOOLS:
            self.rows[n][3].config(state="disabled")
        threading.Thread(target=self._t_update, args=(name, cmd), daemon=True).start()

    def _t_update(self, name, cmd):
        self.app.ui(self.append, "\n$ " + " ".join(cmd))
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        except OSError as e:
            self.app.ui(self.append, "Could not start: %s" % e)
            self.app.ui(self._update_done)
            return
        self.app.pool.register(proc, "update")
        try:
            for raw in proc.stdout:
                line = raw.strip()
                if line:
                    self.app.ui(self.append, line)
            proc.wait()
        finally:
            self.app.pool.unregister(proc)
        self.app.ui(self.append, "Finished (exit code %s)." % proc.returncode)
        if name == "yt-dlp" and proc.returncode != 0:
            self.app.ui(self.append, "If yt-dlp was installed with pip or winget, update it that way "
                                     "(pip install -U yt-dlp / winget upgrade yt-dlp.yt-dlp).")
        self.app.ui(self._update_done)

    def _update_done(self):
        self.busy = False
        self.app.log(">> SYSTEM: Tool update finished. Restart CUTTER_01 if a tool was replaced.")
        self.check()


# ----------------------------------------------------------------------------
# MAIN APP
# ----------------------------------------------------------------------------
class CutterApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.settings = AppSettings()
        self.root.geometry(self.settings.geometry or "980x740")
        self.root.minsize(780, 540)
        self.root.configure(bg=BG_COLOR)

        self.jobs = []
        self.pool = ProcessPool()
        self.ui_q = queue.Queue()
        self.fetch_sem = threading.Semaphore(2)
        self.cancel_event = threading.Event()
        self.downloading = False
        self.current_job = None
        self.closing = False
        self._net_bps = 0.0 if psutil else None
        
        self.is_spinning = False
        self.spin_angle = 90

        self.setup_styles()
        self.setup_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Control-Return>", lambda e: self.toggle_batch())
        self.root.after(40, self._pump)

        self.log(">> SYSTEM READY (v%s). Auto-Fetch Enabled (Type/Paste URL)." % APP_VERSION)
        self.load_queue()
        if not self.jobs:
            self.add_job()
        self.refresh_speed_label()
        self.start_net_monitor()
        threading.Thread(target=self._boot_report, daemon=True).start()

    # --- ui plumbing --------------------------------------------------------
    def ui(self, fn, *args, **kwargs):
        self.ui_q.put((fn, args, kwargs))

    def _pump(self):
        try:
            for _ in range(300):
                fn, args, kwargs = self.ui_q.get_nowait()
                try:
                    fn(*args, **kwargs)
                except tk.TclError:
                    pass
                except Exception as e:
                    print("UI error:", e)
        except queue.Empty:
            pass
        if not self.closing:
            self.root.after(40, self._pump)

    def log(self, text):
        self.ui(self._log_ui, text)

    def _log_ui(self, text):
        t = self.txt_log
        t.config(state="normal")
        t.insert(tk.END, text + "\n")
        lines = int(t.index("end-1c").split(".")[0])
        if lines > MAX_LOG_LINES:
            t.delete("1.0", "%d.0" % (lines - MAX_LOG_LINES + 200))
        t.see(tk.END)
        t.config(state="disabled")

    def clear_log(self):
        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", tk.END)
        self.txt_log.config(state="disabled")

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.txt_log.get("1.0", tk.END))
        self.log(">> SYSTEM: Log copied to clipboard.")

    def setup_styles(self):
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Vertical.TScrollbar", background=PANEL_COLOR, troughcolor=BG_COLOR,
                        bordercolor=BORDER_COLOR, arrowcolor=TEXT_COLOR)
        style.map("Vertical.TScrollbar", background=[("active", BORDER_COLOR)])
        style.configure("TCombobox", fieldbackground=PANEL_COLOR, background=PANEL_COLOR,
                        foreground=TEXT_COLOR, bordercolor=BORDER_COLOR, arrowcolor=TEXT_COLOR,
                        selectbackground=PANEL_COLOR, selectforeground=TEXT_COLOR)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL_COLOR)],
                  foreground=[("readonly", TEXT_COLOR)], background=[("readonly", PANEL_COLOR)])
        style.configure("TNotebook", background=BG_COLOR, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL_COLOR, foreground=TEXT_COLOR,
                        padding=(8, 4), font=PIXEL_FONT_SM, borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", ACCENT_RED)],
                  foreground=[("selected", TEXT_COLOR)])
        self.root.option_add("*TCombobox*Listbox.background", PANEL_COLOR)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT_COLOR)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_RED)

    def _btn(self, parent, text, cmd, **kw):
        return tk.Button(parent, text=text, font=kw.pop("font", PIXEL_FONT), bg=kw.pop("bg", BORDER_COLOR),
                         fg=kw.pop("fg", TEXT_COLOR), relief="flat", command=cmd, **kw)

    def setup_ui(self):
        hf = tk.Frame(self.root, bg=BG_COLOR, highlightbackground=BORDER_COLOR, highlightthickness=1)
        hf.pack(side="top", fill="x", padx=10, pady=(10, 5))
        tk.Label(hf, text="CUTTER_01", font=PIXEL_FONT_XL, bg=BG_COLOR, fg=TEXT_COLOR).pack(side="left", padx=10, pady=5)
        tk.Label(hf, text="BATCH VIDEO UTILITY", font=PIXEL_FONT, bg=BG_COLOR, fg=ACCENT_DIM).pack(side="left", padx=10)
        self.lbl_sys = tk.Label(hf, text="[ READY ]", font=PIXEL_FONT, bg=BG_COLOR, fg=ACCENT_RED)
        self.lbl_sys.pack(side="right", padx=10)

        tf = tk.Frame(self.root, bg=BG_COLOR)
        tf.pack(side="top", fill="x", padx=10, pady=5)
        sm = PIXEL_FONT_SM
        self._btn(tf, "IMPORT", self.import_csv, font=sm).pack(side="left", padx=2)
        self._btn(tf, "EXPORT", self.export_csv, font=sm).pack(side="left", padx=2)
        self._btn(tf, "GUIDE", lambda: CsvGuideWindow(self.root), font=sm).pack(side="left", padx=2)
        self._btn(tf, "PASTE ALL", self.paste_all, font=sm).pack(side="left", padx=2)
        self._btn(tf, "CLEAR DONE", self.clear_done, font=sm).pack(side="left", padx=2)

        tk.Label(tf, text="QUALITY:", font=PIXEL_FONT_SM, bg=BG_COLOR, fg=ACCENT_DIM).pack(side="left", padx=(12, 4))
        self.cb_quality = ttk.Combobox(tf, values=QUALITIES, state="readonly", width=22, font=PIXEL_FONT_SM)
        self.cb_quality.set(self.settings.quality)
        self.cb_quality.pack(side="left")
        self.cb_quality.bind("<<ComboboxSelected>>", self.on_quality_change)

        self._btn(tf, "SETTINGS", lambda: SettingsWindow(self.root, self.settings, self.on_settings_saved), font=sm).pack(side="right", padx=2)
        self.btn_updates = self._btn(tf, "UPDATES", lambda: DepsWindow(self.root, self), font=sm)
        self.btn_updates.pack(side="right", padx=2)
        self._btn(tf, "OPEN DIR", lambda: open_path(self.settings.out_dir), font=sm).pack(side="right", padx=2)

        cf = tk.Frame(self.root, bg=PANEL_COLOR, highlightbackground=BORDER_COLOR, highlightthickness=1)
        cf.pack(side="bottom", fill="x", padx=10, pady=(5, 10))

        pf = tk.Frame(cf, bg=PANEL_COLOR)
        pf.pack(side="left", padx=15, pady=10)
        self.c_prog = tk.Canvas(pf, width=40, height=40, bg=PANEL_COLOR, highlightthickness=0)
        self.c_prog.pack(side="left")
        self.c_prog.create_oval(4, 4, 36, 36, outline=BORDER_COLOR, width=3)
        self.arc_prog = self.c_prog.create_arc(4, 4, 36, 36, start=90, extent=0, outline=ACCENT_RED, style="arc", width=3)
        self.lbl_pct = tk.Label(pf, text="0%", font=PIXEL_FONT, bg=PANEL_COLOR, fg=TEXT_COLOR, width=5, anchor="w")
        self.lbl_pct.pack(side="left", padx=(10, 0))

        sf = tk.Frame(cf, bg=PANEL_COLOR, cursor="hand2")
        sf.pack(side="left", padx=20)
        self.lbl_speed_title = tk.Label(sf, text="NET_SPEED (click = change unit):", font=PIXEL_FONT_SM,
                                        bg=PANEL_COLOR, fg=ACCENT_DIM, cursor="hand2")
        self.lbl_speed_title.pack(anchor="w")
        self.lbl_speed = tk.Label(sf, text="N/A", font=PIXEL_FONT, bg=PANEL_COLOR, fg=TEXT_COLOR, cursor="hand2")
        self.lbl_speed.pack(anchor="w")
        for w in (sf, self.lbl_speed_title, self.lbl_speed):
            w.bind("<Button-1>", self.cycle_unit)

        rf = tk.Frame(cf, bg=PANEL_COLOR)
        rf.pack(side="right", padx=15, pady=10)
        self.lbl_batch = tk.Label(rf, text="", font=PIXEL_FONT_SM, bg=PANEL_COLOR, fg=TEXT_COLOR)
        self.lbl_batch.pack(anchor="e")
        self.lbl_dl_info = tk.Label(rf, text="", font=PIXEL_FONT_SM, bg=PANEL_COLOR, fg=ACCENT_DIM)
        self.lbl_dl_info.pack(anchor="e")
        self.btn_action = tk.Button(rf, text="START BATCH \u2197", font=PIXEL_FONT_LG, bg=ACCENT_RED, fg=TEXT_COLOR,
                                    relief="flat", command=self.toggle_batch)
        self.btn_action.pack(anchor="e", ipadx=10, ipady=3)

        self.paned = tk.PanedWindow(self.root, orient="vertical", bg=BORDER_COLOR, bd=0, sashwidth=4)
        self.paned.pack(side="top", fill="both", expand=True, padx=10, pady=5)

        self.q_frame = tk.Frame(self.paned, bg=BG_COLOR)
        self.paned.add(self.q_frame, minsize=150)
        self.job_canvas = tk.Canvas(self.q_frame, bg=BG_COLOR, highlightthickness=0)
        scroll = ttk.Scrollbar(self.q_frame, orient="vertical", command=self.job_canvas.yview)
        self.job_canvas.configure(yscrollcommand=scroll.set)
        self.job_container = tk.Frame(self.job_canvas, bg=BG_COLOR)
        window_id = self.job_canvas.create_window((0, 0), window=self.job_container, anchor="nw")
        self.job_canvas.bind("<Configure>", lambda e: self.job_canvas.itemconfig(window_id, width=e.width))
        self.job_container.bind("<Configure>", lambda e: self.job_canvas.configure(scrollregion=self.job_canvas.bbox("all")))
        self.job_canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.jobs_frame = tk.Frame(self.job_container, bg=BG_COLOR)
        self.jobs_frame.pack(fill="x")
        self._btn(self.job_container, "+ ADD ANOTHER URL", self.on_add_clicked).pack(pady=10)
        self.root.bind_all("<MouseWheel>", self._on_wheel)

        log_frame = tk.Frame(self.paned, bg=BG_COLOR, highlightbackground=BORDER_COLOR, highlightthickness=1)
        self.paned.add(log_frame, minsize=100)
        lh = tk.Frame(log_frame, bg=BORDER_COLOR)
        lh.pack(fill="x")
        tk.Label(lh, text=" SYSTEM_LOG ", font=PIXEL_FONT, bg=BORDER_COLOR, fg=TEXT_COLOR, anchor="w").pack(side="left")
        tk.Label(lh, text="Mixl", font=("Courier New", 8, "italic"),
                 bg=BORDER_COLOR, fg="#858585", anchor="w").pack(side="left", padx=(5, 0))
        self._btn(lh, "CLEAR", self.clear_log, font=PIXEL_FONT_SM, bg=PANEL_COLOR).pack(side="right", padx=2, pady=1)
        self._btn(lh, "COPY", self.copy_log, font=PIXEL_FONT_SM, bg=PANEL_COLOR).pack(side="right", padx=2, pady=1)
        self.txt_log = tk.Text(log_frame, font=PIXEL_FONT_SM, bg=TERMINAL_BG, fg=ACCENT_DIM, relief="flat", state="disabled", wrap="word")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=log_scroll.set)
        self.txt_log.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        log_scroll.pack(side="right", fill="y")

    def _on_wheel(self, event):
        w = self.root.winfo_containing(event.x_root, event.y_root)
        if w is not None and str(w).startswith(str(self.q_frame)):
            self.job_canvas.yview_scroll(int(-event.delta / 120), "units")

    def on_add_clicked(self):
        self.add_job()
        self.job_canvas.after(60, lambda: self.job_canvas.yview_moveto(1.0))

    def on_quality_change(self, event=None):
        self.settings.quality = self.cb_quality.get()
        self.settings.save()

    def on_settings_saved(self):
        self.cb_quality.set(self.settings.quality)
        self.refresh_speed_label()
        self.log(">> SYSTEM: Settings saved.")

    def set_sys(self, text, color):
        self.lbl_sys.config(text="[" + text + "]", fg=color)

    def eval_btn_state(self):
        if self.downloading:
            return
        fetching = any(j.status == "FETCHING" for j in self.jobs)
        if fetching:
            self.btn_action.config(state="disabled", bg=BORDER_COLOR, text="FETCHING...")
        else:
            self.btn_action.config(state="normal", bg=ACCENT_RED, text="START BATCH \u2197")

    # --- network speed ------------------------------------------------------
    def set_net_bps(self, bps):
        self._net_bps = bps
        self.refresh_speed_label()

    def refresh_speed_label(self):
        if self._net_bps is None:
            self.lbl_speed.config(text="N/A")
        else:
            self.lbl_speed.config(text=format_speed(self._net_bps, self.settings.speed_unit))

    def cycle_unit(self, event=None):
        names = SPEED_UNIT_NAMES
        cur = self.settings.speed_unit
        i = names.index(cur) if cur in names else 0
        self.settings.speed_unit = names[(i + 1) % len(names)]
        self.settings.save()
        self.refresh_speed_label()

    def start_net_monitor(self):
        if not psutil:
            return

        def loop():
            last = psutil.net_io_counters().bytes_recv
            last_t = time.time()
            while not self.closing:
                time.sleep(1)
                cur = psutil.net_io_counters().bytes_recv
                now = time.time()
                bps = max(0, cur - last) / max(0.001, now - last_t)
                last, last_t = cur, now
                self.ui(self.set_net_bps, bps)

        threading.Thread(target=loop, daemon=True).start()

    # --- boot report / update check ----------------------------------------
    def _boot_report(self):
        try:
            yt = tool_info(self.pool, "yt-dlp")
            ff = tool_info(self.pool, "ffmpeg")
            dn = tool_info(self.pool, "deno")

            def desc(info):
                path, ver = info
                if not path:
                    return "MISSING"
                return (ver or "?") + (" (app folder)" if path and is_local_tool(path) else "")

            self.log(">> DEPS: yt-dlp %s | ffmpeg %s | deno %s" % (desc(yt), desc(ff), desc(dn)))
            if not yt[0]:
                self.log(">> WARNING: yt-dlp is missing. Use UPDATES -> INSTALL.")
            if not ff[0]:
                self.log(">> WARNING: ffmpeg is missing. Merging and cutting will fail.")
            elif not find_tool("ffprobe"):
                self.log(">> WARNING: ffprobe not found next to ffmpeg.")
            if not dn[0] and not find_tool("node") and not find_tool("bun"):
                self.log(">> WARNING: no JavaScript runtime (deno). YouTube downloads may be throttled "
                         "or miss formats. Use UPDATES -> INSTALL deno.")

            base = ytdlp_base()
            if base:
                try:
                    rc, out, err = self.pool.run_capture(base + ["--help"], 40)
                    CAPS["js_runtimes"] = "--js-runtimes" in (out or "")
                    if not CAPS["js_runtimes"]:
                        self.log(">> WARNING: this yt-dlp is too old for JS runtimes. Update it (UPDATES).")
                except OSError:
                    pass

            HW["encoders"] = detect_hw_encoders(self.pool)
            HW["checked"] = True
            if HW["encoders"]:
                self.log(">> DEPS: GPU encoders available: " + ", ".join(HW["encoders"]))
            else:
                self.log(">> DEPS: no GPU encoder detected, precise cuts use CPU (x264).")

            if self.settings.auto_update_check and not self.closing:
                outdated = []
                for name, info in (("yt-dlp", yt), ("deno", dn)):
                    latest, err = latest_version(name)
                    if latest and info[1] and vtuple(info[1]) < vtuple(latest):
                        outdated.append("%s %s -> %s" % (name, info[1], latest))
                if outdated:
                    self.log(">> UPDATE: " + "; ".join(outdated) + "  (open UPDATES)")
                    self.ui(self.btn_updates.config, text="UPDATES (!)", fg=GOOD_GREEN)
        except Exception as e:
            self.log(">> WARN: boot check failed: %s" % short(str(e), 80))

    # --- jobs ---------------------------------------------------------------
    def add_job(self, url="", start=0, end=0, duration=0, title="UNKNOWN", fetch=False, vid=""):
        job = JobItem(self, self.jobs_frame)
        job.start_sec, job.end_sec, job.duration_sec, job.title, job.vid = start, end, duration, title, vid
        if url:
            job.set_url(url)
            if title != "UNKNOWN":
                job.url = url          # already known: don't refetch
        job.refresh_all()
        if url and title != "UNKNOWN":
            job.set_status("READY")
        self.jobs.append(job)
        if fetch and url:
            job.fetch()
        self.eval_btn_state()
        return job

    def paste_all(self):
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            self.log(">> SYSTEM: Clipboard is empty.")
            return
        urls = []
        for u in URL_RE.findall(text):
            if u not in urls:
                urls.append(u)
        if not urls:
            self.log(">> SYSTEM: No URLs found in clipboard.")
            return
        existing = {j.entry_url.get().strip() for j in self.jobs}
        added = 0
        for u in urls:
            if u in existing:
                continue
            empty = next((j for j in self.jobs if not j.entry_url.get().strip()), None)
            if empty:
                empty.set_url(u)
                if len(urls) <= 6:
                    empty.fetch()
            else:
                self.add_job(url=u, fetch=len(urls) <= 6)
            existing.add(u)
            added += 1
        self.log(">> SYSTEM: Added %d URL(s) from clipboard." % added)
        self.job_canvas.after(80, lambda: self.job_canvas.yview_moveto(1.0))

    def remove_job(self, job):
        if job not in self.jobs:
            return
        job.removed = True
        self.pool.kill(job)
        self.jobs.remove(job)
        job.frame.destroy()
        if not self.jobs:
            self.add_job()
            self.ui(self.reset_progress_ui)
        self.eval_btn_state()

    def clear_done(self):
        for job in [j for j in self.jobs if j.status in ("COMPLETE", "SKIPPED") and j is not self.current_job]:
            self.remove_job(job)
        self.ui(self.reset_progress_ui)
        self.log(">> SYSTEM: Cleared finished jobs.")

    def save_queue(self):
        data = []
        for j in self.jobs:
            url = j.entry_url.get().strip()
            if url and j.status not in ("COMPLETE", "SKIPPED"):
                data.append({"url": url, "start": j.start_sec, "end": j.end_sec,
                             "duration": j.duration_sec, "title": j.title, "id": j.vid})
        try:
            with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            pass

    def load_queue(self):
        if not os.path.exists(QUEUE_FILE):
            return
        try:
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            count = 0
            for item in data:
                if isinstance(item, dict) and valid_url(item.get("url", "")):
                    self.add_job(item["url"], int(item.get("start", 0)), int(item.get("end", 0)),
                                 int(item.get("duration", 0)), str(item.get("title", "UNKNOWN")),
                                 vid=str(item.get("id", "")))
                    count += 1
            if count:
                self.log(">> SYSTEM: Restored %d job(s) from last session." % count)
        except (OSError, ValueError, TypeError):
            pass

    def on_close(self):
        if self.downloading:
            if not messagebox.askyesno("QUIT", "A batch is running. Stop it and quit?"):
                return
            self.cancel_event.set()
            self.pool.kill_all()
        self.closing = True
        try:
            self.settings.geometry = "%dx%d" % (self.root.winfo_width(), self.root.winfo_height())
            self.settings.save()
        except Exception:
            pass
        self.save_queue()
        self.root.destroy()

    # --- csv ----------------------------------------------------------------
    def import_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV / TXT", "*.csv *.txt"), ("All files", "*.*")])
        if not path:
            return
        entries, skipped = [], 0
        try:
            with open(path, "r", newline="", encoding="utf-8-sig") as fh:
                for n, row in enumerate(csv.reader(fh), 1):
                    if not row or not row[0].strip() or row[0].strip().startswith("#"):
                        continue
                    url = row[0].strip()
                    if not valid_url(url):
                        skipped += 1
                        self.log(">> SKIP: line %d is not a URL (%s)" % (n, short(url, 30)))
                        continue
                    start = end = 0
                    if len(row) >= 3:
                        try:
                            s, e = parse_time(row[1]), parse_time(row[2])
                            if s < e:
                                start, end = s, e
                            else:
                                self.log(">> WARN: line %d has an invalid range, using full video." % n)
                        except ValueError:
                            self.log(">> WARN: line %d has an unreadable range, using full video." % n)
                    entries.append((url, start, end))
        except (OSError, UnicodeDecodeError, csv.Error) as e:
            messagebox.showerror("ERROR", "Failed to read file:\n%s" % e)
            self.log(">> ERROR: Failed to import file: %s" % e)
            return
        fetch_now = len(entries) <= 10
        # reuse a single empty starter row instead of leaving it blank
        if len(self.jobs) == 1 and not self.jobs[0].entry_url.get().strip():
            self.remove_job(self.jobs[0])
        for url, start, end in entries:
            self.add_job(url, start, end, fetch=fetch_now)
        self.log(">> SYSTEM: Imported %d job(s), skipped %d line(s)." % (len(entries), skipped))
        if entries and not fetch_now:
            self.log(">> SYSTEM: Large import: titles and durations load when the batch starts.")

    def export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                for j in self.jobs:
                    url = j.entry_url.get().strip()
                    if not url:
                        continue
                    if j.is_cut():
                        writer.writerow([url, sec_to_str(j.start_sec), sec_to_str(j.end_sec)])
                    else:
                        writer.writerow([url])
            self.log(">> SYSTEM: Batch list exported.")
        except OSError as e:
            messagebox.showerror("ERROR", "Failed to write file:\n%s" % e)

    # --- batch & progress UI ------------------------------------------------
    def _spin_loop(self):
        if getattr(self, "is_spinning", False):
            self.spin_angle = (self.spin_angle - 15) % 360
            self.c_prog.itemconfig(self.arc_prog, start=self.spin_angle, extent=90)
            self.root.after(40, self._spin_loop)

    def start_spinner(self, text=""):
        if not getattr(self, "is_spinning", False):
            self.is_spinning = True
            self.spin_angle = 90
            self.lbl_pct.config(text="")
            self._spin_loop()
        if text:
            self.lbl_dl_info.config(text=text)

    def stop_spinner(self):
        self.is_spinning = False
        self.c_prog.itemconfig(self.arc_prog, start=90, extent=0)

    def reset_progress_ui(self):
        self.stop_spinner()
        self.c_prog.itemconfig(self.arc_prog, start=90, extent=0)
        self.lbl_pct.config(text="0%")
        self.lbl_dl_info.config(text="")
        if not self.downloading:
            self.root.title(APP_TITLE)
            self.lbl_batch.config(text="")

    def update_c_prog(self, pct):
        self.stop_spinner()
        pct = max(0.0, min(100.0, pct))
        self.c_prog.itemconfig(self.arc_prog, start=90, extent=-(pct / 100.0) * 359.99)
        self.lbl_pct.config(text="%d%%" % int(pct))
        if self.downloading and pct > 0:
            self.root.title("[%d%%] %s" % (int(pct), APP_TITLE))

    def toggle_batch(self):
        if self.downloading:
            self.cancel_event.set()
            self.pool.kill_all()
            self.set_sys("CANCELLING...", WARNING_RED)
            self.log(">> SYSTEM: Cancellation requested...")
            self.btn_action.config(state="disabled")
            self.ui(self.reset_progress_ui)
        elif str(self.btn_action.cget("state")) != "disabled":
            self.start_batch()

    def start_batch(self):
        if not ytdlp_base():
            messagebox.showerror("yt-dlp missing", "yt-dlp was not found. Use UPDATES -> INSTALL, "
                                                   "or run: pip install yt-dlp")
            return
        work, seen = [], set()
        for job in self.jobs:
            url = job.entry_url.get().strip()
            if not url or job.status in ("COMPLETE", "SKIPPED"):
                continue
            if not valid_url(url):
                job.set_status("ERROR", "INVALID URL")
                continue
            job.on_range_edit()
            job.url = url
            key = (url, job.start_sec, job.end_sec)
            if key in seen:
                job.set_status("SKIPPED", "DUPLICATE")
                self.log(">> SKIP: duplicate job for " + url)
                continue
            seen.add(key)
            work.append((job, url))
        if not work:
            self.log(">> SYSTEM: Nothing to do.")
            return

        cfg = copy.copy(self.settings)
        for job, _ in work:
            job.set_status("QUEUED")
        self.downloading = True
        self.cancel_event.clear()
        self.btn_action.config(text="STOP BATCH \u2297", bg=BORDER_COLOR)
        self.set_sys("PROCESSING BATCH", TEXT_COLOR)
        self.log("\n>> SYSTEM: Batch started (%d job(s), quality %s)." % (len(work), cfg.quality))
        threading.Thread(target=self.batch_worker, args=(work, cfg), daemon=True).start()

    def batch_worker(self, work, cfg):
        stats = {"ok": 0, "skipped": 0, "failed": 0}
        total = len(work)
        for idx, (job, url) in enumerate(work, 1):
            if self.cancel_event.is_set():
                break
            if job.removed:
                continue
            self.current_job = job
            self.ui(self.lbl_batch.config, text="JOB %d/%d" % (idx, total))
            self.ui(self.reset_progress_ui)
            self.log(">> SYSTEM: Processing URL -> " + url)
            result = self.process_job(job, url, cfg)
            if result == "ok":
                stats["ok"] += 1
            elif result == "skipped":
                stats["skipped"] += 1
            elif result == "failed":
                stats["failed"] += 1
            elif result == "cancelled" and not job.removed:
                self.ui(job.set_status, "CANCELLED")
        self.ui(self.finish_batch, work, stats, cfg)

    def finish_batch(self, work, stats, cfg):
        cancelled = self.cancel_event.is_set()
        self.downloading = False
        self.current_job = None
        self.reset_progress_ui()
        for job, _ in work:
            if not job.removed and job.status == "QUEUED":
                job.set_status("READY" if job.title != "UNKNOWN" else "IDLE")

        self.eval_btn_state()
        summary = "%d done, %d skipped, %d failed" % (stats["ok"], stats["skipped"], stats["failed"])
        if cancelled:
            self.set_sys("CANCELLED", WARNING_RED)
            self.log(">> SYSTEM: Batch stopped (%s)." % summary)
        else:
            self.set_sys("BATCH COMPLETE", ACCENT_RED)
            self.log(">> SYSTEM: All batch jobs processed (%s)." % summary)
            if cfg.sound and winsound:
                try:
                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
                except Exception:
                    pass
            if cfg.open_when_done and stats["ok"] > 0:
                open_path(cfg.out_dir)
        self.save_queue()

    def resolve_stem_fast(self, job, template, cfg):
        """Fast local template formatting to replace slow yt-dlp --print filename call."""
        def clean(s):
            return re.sub(r'[\\/*?:"<>|]', "_", str(s))
        
        name = template.replace("%(title)s", clean(job.title)).replace("%(id)s", clean(job.vid))
        ext = cfg.format
        if is_audio(cfg.quality):
            ext = "mp3" if "MP3" in cfg.quality else "m4a"
            
        if "%(ext)s" in name:
            name = name.replace("%(ext)s", ext)
        else:
            name += "." + ext
            
        # Strip extension to return just the stem
        if name.lower().endswith("." + ext.lower()):
            name = name[:-(len(ext)+1)]
            
        return os.path.join(cfg.out_dir, name)

    def process_job(self, job, url, cfg):
        if job.duration_sec <= 0 and job.title == "UNKNOWN":
            self.ui(self.start_spinner, "FETCHING METADATA...")
            self.ui(job.set_status, "FETCHING")
            meta, err = None, ""
            for _ in range(2):
                if self._stopped(job):
                    return "cancelled"
                try:
                    meta = fetch_meta(self.pool, url, cfg, tag=job)
                    break
                except Exception as e:
                    err = str(e)
                    if is_permanent(err) or self.cancel_event.wait(1.5):
                        break
            self.ui(self.stop_spinner)
            if self._stopped(job):
                return "cancelled"
            if meta is None:
                self.ui(job.set_status, "ERROR", err)
                self.log(">> ERROR: Could not fetch metadata: " + err)
                if "sign in" in err.lower():
                    self.log(">> HINT: Try SETTINGS -> NETWORK -> COOKIES to use your browser login.")
                return "failed"
            job.absorb_meta(meta)
            self.ui(job.refresh_all)

        is_cut = job.is_cut()
        start, end = job.start_sec, job.end_sec
        audio = is_audio(cfg.quality)
        precise = is_cut and cfg.cut_mode == "precise" and not audio
        codec = effective_codec(cfg, is_cut)
        template = safe_template(cfg.name_template)
        if is_cut:
            template = add_suffix(template, "_%s-%s" % (sec_to_tag(start), sec_to_tag(end)))
        try:
            os.makedirs(cfg.out_dir, exist_ok=True)
        except OSError as e:
            self.ui(job.set_status, "ERROR", "BAD OUTPUT DIR")
            self.log(">> ERROR: Cannot create output folder: %s" % e)
            return "failed"

        if cfg.collision in ("skip", "unique"):
            stem = self.resolve_stem_fast(job, template, cfg)
            if stem and media_exists(stem):
                if cfg.collision == "skip":
                    self.ui(job.set_status, "SKIPPED", "FILE EXISTS")
                    self.log(">> SYSTEM: File already exists, skipping.")
                    return "skipped"
                n = 1
                while media_exists("%s (%d)" % (stem, n)):
                    n += 1
                template = add_suffix(template, " (%d)" % n)
                self.log(">> SYSTEM: File exists, saving as copy (%d)." % n)

        max_attempts = 1 + cfg.retries
        last_err = ""
        force_cpu = False
        attempt = 0
        t0 = time.time()
        while attempt < max_attempts:
            attempt += 1
            if self._stopped(job):
                return "cancelled"
            enc = pick_encoder(cfg, force_cpu) if precise else None
            if precise:
                if cfg.cut_encoder not in ("Auto", "CPU (x264)") and enc == "libx264" and not force_cpu:
                    self.log(">> WARN: %s not available, using CPU (x264)." % cfg.cut_encoder)
                self.log(">> SYSTEM: Precise cut with %s (%s)." % (
                    enc, ("CRF %d, preset %s" % (cfg.cut_crf, cfg.cut_preset)) if enc == "libx264"
                    else "quality %d" % cfg.cut_crf))
            job.output_path = ""
            self.ui(job.set_status, "DOWNLOADING", "" if attempt == 1 else "RETRY %d" % (attempt - 1))
            self.ui(self.update_c_prog, 0)
            state, permanent, last_err = self.run_download(job, url, template, cfg, codec,
                                                           is_cut, precise, start, end, enc)
            if state == "ok":
                self.ui(job.set_status, "COMPLETE")
                self.ui(job.show_output_button)
                self.ui(self.update_c_prog, 100)
                self.log(">> SYSTEM: Download complete in %s." % sec_to_str(time.time() - t0))
                return "ok"
            if state == "cancel":
                return "cancelled"
            if enc and enc != "libx264" and not permanent:
                force_cpu = True
                attempt -= 1             # the GPU fallback does not use up a retry
                self.log(">> WARN: GPU encode failed (%s). Retrying with CPU (x264)." % short(last_err, 60))
                continue
            if permanent:
                self.log(">> ERROR: Permanent failure, not retrying: " + last_err)
                if "sign in" in last_err.lower():
                    self.log(">> HINT: Try SETTINGS -> NETWORK -> COOKIES to use your browser login.")
                break
            if attempt < max_attempts:
                self.log(">> SYSTEM: Attempt %d failed (%s). Retrying..." % (attempt, short(last_err, 60)))
                if self.cancel_event.wait(2 * attempt) or job.removed:
                    return "cancelled"

        self.ui(job.set_status, "ERROR", last_err or "FAILED")
        self.log(">> ERROR: Job failed. " + (last_err or ""))
        return "failed"

    def build_download_cmd(self, template, cfg, codec, is_cut, precise, start, end, enc, url):
        cmd = ytdlp_base() + [
            "--encoding", "utf-8", "--newline", "--windows-filenames",
            "--socket-timeout", "30", "--retries", "3", "--extractor-retries", "3",
            "--fragment-retries", "10", "--file-access-retries", "3",
            "-N", str(cfg.threads),
        ]
        cmd += tool_args()
        cmd += format_args(cfg.format, cfg.quality, codec)
        cmd += ["-o", os.path.join(cfg.out_dir, template)]
        cmd.append("--yes-playlist" if cfg.allow_playlist else "--no-playlist")
        if cfg.save_thumb:
            cmd.append("--write-thumbnail")
        if cfg.save_meta:
            cmd.extend(["--write-description", "--write-info-json", "--write-comments"])
        if is_cut:
            cmd += ["--download-sections", "*%s-%s" % (sec_to_str(start), sec_to_str(end))]
            if precise:
                cmd.append("--force-keyframes-at-cuts")
                cmd += ["--downloader-args", "ffmpeg_o:" + " ".join(encoder_args(enc, cfg))]
        elif cfg.use_aria2c:
            aria = find_tool("aria2c")
            if aria:
                cmd += ["--downloader", aria, "--downloader-args", "aria2c:-x 16 -s 16 -k 1M"]
        if cfg.collision == "overwrite":
            cmd.append("--force-overwrites")
        if cfg.rate_limit:
            cmd += ["--limit-rate", cfg.rate_limit]
        cmd += cookie_args(cfg)
        cmd += extra_args(cfg)
        cmd.append(url)
        return cmd

    def should_log(self, line, cfg):
        if cfg.verbose_log or KEEP_RE.match(line):
            return True
        if NOISE_RE.match(line):
            return False
        return line.startswith("[") or "ERROR" in line or "WARNING" in line

    def run_download(self, job, url, template, cfg, codec, is_cut, precise, start, end, enc):
        cmd = self.build_download_cmd(template, cfg, codec, is_cut, precise, start, end, enc, url)
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=0, creationflags=NO_WINDOW,
            )
        except OSError as e:
            return "fail", True, "cannot start yt-dlp: %s" % e
        self.pool.register(proc, job)

        permanent, last_err = False, ""
        clip_len = max(1, end - start)
        ff_prog, last_push = 0.0, 0.0
        n_streams, stage, dest_count = 1, 0, 0
        tail = deque(maxlen=25)

        # Read in chunks, not one byte at a time. Keep support for both CR and LF
        # because yt-dlp and ffmpeg versions differ in how they terminate progress.
        def read_output_lines(pipe):
            pending = bytearray()
            while True:
                chunk = pipe.read(8192)
                if not chunk:
                    if pending:
                        yield pending.decode("utf-8", "replace")
                    return
                pending.extend(chunk)
                while True:
                    cr = pending.find(b"\r")
                    lf = pending.find(b"\n")
                    ends = [i for i in (cr, lf) if i >= 0]
                    if not ends:
                        break
                    end = min(ends)
                    line = bytes(pending[:end])
                    del pending[:end + 1]
                    # Consume the LF in a CRLF pair without emitting an empty line.
                    if pending[:1] == b"\n" and line is not None:
                        del pending[:1]
                    if line:
                        yield line.decode("utf-8", "replace")

        try:
            for raw_line in read_output_lines(proc.stdout):
                if self._stopped(job):
                    self.pool.kill(job)
                    break
                line = raw_line.strip()
                if not line:
                    continue
                tail.append(line)

                mf = FMT_COUNT_RE.search(line)
                if mf:
                    n_streams = max(1, len(mf.group(2).split("+")))
                    stage, dest_count = 0, 0
                md = DEST_RE.match(line)
                if md:
                    job.output_path = md.group(2).strip()
                    if md.group(1) == "download":
                        stage = dest_count
                        dest_count += 1
                mm = MERGE_RE.match(line)
                if mm:
                    job.output_path = mm.group(1)
                me_ex = EXISTS_RE.match(line)
                if me_ex:
                    job.output_path = me_ex.group(1)

                pct, bps, eta, encx = None, None, None, None
                m = PCT_RE.search(line)
                ma = ARIA_PCT_RE.match(line)
                if m:
                    pct = overall_pct(stage, n_streams, float(m.group(1)))
                    ms = SPEED_RE.search(line)
                    if ms:
                        bps = speed_from_match(ms)
                    me = ETA_RE.search(line)
                    if me:
                        eta = me.group(1)
                elif ma:
                    pct = overall_pct(stage, n_streams, float(ma.group(1)))
                    md2 = ARIA_DL_RE.search(line)
                    if md2:
                        bps = speed_from_match(md2)
                    me2 = ARIA_ETA_RE.search(line)
                    if me2:
                        eta = me2.group(1)
                elif "bitrate=" in line:
                    mt = FFTIME_RE.search(line)
                    if mt:
                        cur = int(mt.group(1)) * 3600 + int(mt.group(2)) * 60 + float(mt.group(3))
                        ff_prog = max(ff_prog, min(99.0, cur / clip_len * 100))
                        pct = ff_prog
                        msp = FFSPEED_RE.search(line)
                        if msp:
                            try:
                                encx = float(msp.group(1))
                            except ValueError:
                                encx = None
                            if encx and encx > 0:
                                eta = sec_to_str(max(0, (clip_len - cur) / encx))

                if pct is not None:
                    now = time.time()
                    if now - last_push > 0.1 or pct >= 100:
                        last_push = now
                        self.ui(self.update_c_prog, pct)
                        self.ui(job.set_status, "DOWNLOADING", "%d%%" % int(pct))
                        info = []
                        if bps is not None:
                            info.append(format_speed(bps, self.settings.speed_unit))
                            if not psutil:
                                self.ui(self.set_net_bps, bps)
                        if encx:
                            info.append("ENC %.1fx" % encx)
                        if eta:
                            info.append("ETA " + eta)
                        if info:
                            self.ui(self.lbl_dl_info.config, text="  ".join(info))
                    if m or ma or line.startswith(("frame=", "size=")):
                        continue

                if any(tag in line for tag in ("[Merger]", "[ExtractAudio]", "[VideoRemuxer]", "[VideoConvertor]")):
                    self.ui(job.set_status, "PROCESSING")
                    self.ui(self.start_spinner, "MERGING MEDIA...")
                if line.startswith("ERROR") or "ERROR:" in line:
                    last_err = re.sub(r"^.*?ERROR:\s*", "", line)[:200]
                    if is_permanent(line):
                        permanent = True
                if self.should_log(line, cfg):
                    self.log("  " + line)
            if self._stopped(job):
                self.pool.kill(job)
            proc.wait()
        finally:
            self.pool.unregister(proc)
            try:
                proc.stdout.close()
            except Exception:
                pass

        if self._stopped(job):
            return "cancel", False, ""
        if proc.returncode == 0:
            return "ok", False, ""
        if not cfg.verbose_log:
            self.log("  --- last output ---")
            for l in list(tail)[-15:]:
                self.log("  | " + l)
        return "fail", permanent, last_err or "exit code %s" % proc.returncode

    def _stopped(self, job):
        return self.cancel_event.is_set() or job.removed


# ----------------------------------------------------------------------------
# ENTRY POINT
# ----------------------------------------------------------------------------
def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    root.withdraw()
    try:
        root.iconbitmap(resource_path("icon.ico"))
    except Exception:
        pass

    def launch():
        CutterApp(root)
        root.deiconify()
        apply_dark_titlebar(root)

    SplashScreen(root, launch)
    root.mainloop()


if __name__ == "__main__":
    main()