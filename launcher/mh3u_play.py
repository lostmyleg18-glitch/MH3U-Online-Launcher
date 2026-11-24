#!/usr/bin/env python3
"""MH3U Online - one-click player launcher for a single MH3U Revival server.

A player runs MH3U_Play.exe, clicks Install, chooses their own MH3U dump and clicks Play.
They never download, open or configure Cemu themselves. The launcher:

  * downloads the patched Cemu from the MH3U Revival release and offers updates,
  * checks that the chosen folder really holds Monster Hunter 3 Ultimate (US, EU or JP)
    and its update, and registers it with Cemu,
  * turns a few simple graphics choices into Cemu settings and graphic packs (the
    community MH3U resolution pack and the MH3U Revival frame-rate pack),
  * finds the player's Xbox or PlayStation controller (USB or Bluetooth) and writes a
    matching Cemu profile with the player's own stick deadzones,
  * creates the player's online identity, points the game at the server and starts it.

License: AGPL-3.0-or-later. The account format, the NAT check and the update rules follow
MH3U Revival's own launcher (github.com/Matt-Wood-23/mh3u-revival, AGPL-3.0).
"""
from __future__ import annotations

import argparse
import copy
import ctypes
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path

# ============================================================================ server
SERVER_NAME = "MH3U Online"          # window title
# The server's address (IPv4 or DNS name) isn't in the source code: build.ps1 builds
# launcher\server.txt (one line, e.g. 203.0.113.5) into MH3U_Play.exe. MH3U_SERVER_HOST overrides it.
SERVER_HOST_FILE = "server.txt"
STATUS_PORT = 0                     # MH3U_STATUS_PORT on the server (0 = none, the setup default)
NATCHECK_PORT = 10025
LAUNCHER_VERSION = "1.0.1"

# ============================================================================ sources
GITHUB_REPO = "Matt-Wood-23/mh3u-revival"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main"
BUNDLE_ASSET = "MH3U_Online_Bundle.zip"
FPS_ASSET = "MH3U_FPS_Cap.zip"
GFXPACKS_API = "https://api.github.com/repos/cemu-project/cemu_graphic_packs/releases/latest"
USER_AGENT = "MH3U-Online-Launcher"

# ============================================================================ layout
CEMU_EXE = "Cemu_release.exe"
VERSION_FILE = "version.txt"
P = "portable"
SETTINGS_REL = f"{P}/settings.xml"
SRVFILE_REL = f"{P}/mh3u_server.txt"
ACTDIR_REL = f"{P}/mlc01/usr/save/system/act/80000001"
CTRL_REL = f"{P}/controllerProfiles/controller0.xml"
CONFIG_REL = f"{P}/mh3u_play.json"
LOG_REL = f"{P}/mh3u_play.log"
MLC_TITLE_REL = f"{P}/mlc01/usr/title"
FPS_PACK_DIR = f"{P}/graphicPacks/MH3U_FPS_Cap"
GFX_PACK_DIR = f"{P}/graphicPacks/downloadedGraphicPacks/MonsterHunter3Ultimate"
# Cemu stores a pack as its rules.txt path relative to the portable folder, with
# Windows separators (GraphicPack2::GetNormalizedPathString).
FPS_PACK_KEY = "graphicPacks\\MH3U_FPS_Cap\\rules.txt"
GFX_PACK_KEY = "graphicPacks\\downloadedGraphicPacks\\MonsterHunter3Ultimate\\Graphics\\rules.txt"

# Files in the release bundle that players of this server don't need (the upstream
# launcher would point them at the official server).
SKIP_FROM_BUNDLE = {"mh3u_online.exe", "server.exe",
                    "if antivirus blocks the launcher - join.bat", "quickstart.txt"}
# Player state: written on first install, never overwritten by an update.
KEEP_IF_PRESENT = (SRVFILE_REL, SETTINGS_REL, CONFIG_REL, f"{P}/controllerProfiles",
                   f"{P}/mlc01/usr/save", f"{P}/mlc01/usr/title", f"{P}/graphicPacks")

# ============================================================================ game ids
MH3U_REGIONS = {"0005000010118300": "US", "0005000010117200": "EU", "0005000010104D00": "JP"}

# ============================================================================ graphics
RES_OPTIONS = [("1280 x 720 (faster)", "1280x720 (HD)"),
               ("1600 x 900", "1600x900"),
               ("1920 x 1080 (original)", "1920x1080 (Full HD, Default)"),
               ("2560 x 1440 (2K)", "2560x1440 (2K)"),
               ("3200 x 1800", "3200x1800"),
               ("3840 x 2160 (4K)", "3840x2160 (4K)")]
FPS_OPTIONS = [("30 FPS (original speed)", "30 FPS (vanilla-correct)"),
               ("45 FPS", "45 FPS (middle ground)"),
               ("60 FPS (recommended)", "60 FPS (normalized beta)"),
               ("120 FPS (experimental)", "120 FPS (experimental)")]
SHADOW_OPTIONS = [("Low", "Low (50%)"), ("Medium (original)", "Medium (100%, Default)"),
                  ("High", "High (200%)"), ("Ultra", "Ultra (300%)")]
ANISO_OPTIONS = [("Off (original)", "1x (Default)"), ("2x", "2x"), ("4x", "4x"),
                 ("8x", "8x"), ("16x", "16x")]

# A 120 FPS preset for the MH3U Revival FPS Cap pack. Every per-frame correction is half
# of the pack's own 60 FPS value (the pack's 30 -> 60 step), the buff-icon reload keeps
# 0.70 s per icon (84 frames). Not play-tested by the pack's author: experimental.
FPS120_NAME = "120 FPS (experimental)"
FPS120_PRESET = f"""
[Preset]
name = {FPS120_NAME}
$fpsCap = 120.0
$lanceDrain = -1.0
$camYaw1 = 0x3B200137
$camYaw2 = 0x3B2000FD
$camYaw3 = 0x3B2000E0
$camPitch1 = 0x3B40008C
$camPitch2 = 0x3B40005C
$buffHold = 0x39800053
$golfA = 0x3D801008
$golfB = 0xC00CDED0
$alaTurn0 = 0x39080040
$alaTurn1 = 0x390AFFC0
$alaTurn2 = 0x390B0060
$alaTurn3 = 0x390CFFA0
$alaTurn4 = 0x380B0040
$alaTurn5 = 0x380CFFC0
$alaTurn6 = 0x38050060
$alaTurn7 = 0x3806FFA0
"""

DEFAULT_GRAPHICS = {
    "resolution": "1920x1080 (Full HD, Default)",
    "fps": "60 FPS (normalized beta)",
    "shadows": "Medium (100%, Default)",
    "aniso": "1x (Default)",
    "fullscreen": False,
    "vsync": False,
    "show_fps": False,
    "gamepad_window": False,
    "api": "vulkan",
    "sound": "stereo",
    "audio_api": "xaudio2",
}
# Saved with every launcher config. 2: the GamePad window became off by default, and configs
# saved before that (where it was simply on) get it turned off once. 3: sound became stereo
# by default (surround was the default before), so older configs get stereo once.
SETTINGS_VERSION = 3
SOUND_OPTIONS = ("stereo", "surround")
# Cemu's settings.xml <Audio> values (Cemu src/audio/IAudioAPI.h, src/config/CemuConfig.h):
# api DirectSound 0, XAudio2.7 1, XAudio2 2, Cubeb 3; TVChannels mono 0, stereo 1, surround 2 (5.1).
CEMU_AUDIO_APIS = {"xaudio2": 2, "cubeb": 3}
CEMU_TV_CHANNELS = {"surround": 2, "stereo": 1}
# The default output device, "default" under both XAudio2 and Cubeb. Cemu plays no TV sound
# when the saved device isn't one of the API's devices, so a device saved under another API
# is replaced by this.
CEMU_DEFAULT_AUDIO_DEVICE = "default"
DEFAULT_CONTROLS = {
    "mode": "auto",            # auto = the launcher writes the profile; keep = player's own
    "device": None,            # last chosen controller {key, api, uuid, name, kind}
    "confirm_bottom": False,   # False = Wii U layout (confirm on the right button)
    "rumble": True,
    "left_deadzone": 0.08,
    "left_range": 1.3,
    "right_deadzone": 0.08,
    "right_range": 1.3,
}

# ============================================================================ controller
# Cemu's emulated Wii U GamePad button ids (VPADController::ButtonId).
WIIU_NAMES = {1: "A", 2: "B", 3: "X", 4: "Y", 5: "L", 6: "R", 7: "ZL", 8: "ZR", 9: "+",
              10: "-", 11: "Up", 12: "Down", 13: "Left", 14: "Right", 15: "L-stick click",
              16: "R-stick click", 17: "L-stick up", 18: "L-stick down", 19: "L-stick left",
              20: "L-stick right", 21: "R-stick up", 22: "R-stick down", 23: "R-stick left",
              24: "R-stick right", 26: "switch screens"}
# Cemu button codes (Buttons2): kButton0..31 = 0..31, then axis directions.
K_AXIS_XP, K_AXIS_YP, K_ROT_XP, K_ROT_YP, K_TRIG_XP, K_TRIG_YP = 38, 39, 40, 41, 42, 43
K_AXIS_XN, K_AXIS_YN, K_ROT_XN, K_ROT_YN = 44, 45, 46, 47
# SDL gamepad buttons are positional: 0 south, 1 east, 2 west, 3 north ...
SDL_FACE_WIIU = {1: 1, 2: 0, 3: 3, 4: 2}        # Wii U A on the right button (Cemu default)
SDL_FACE_BOTTOM = {1: 0, 2: 1, 3: 2, 4: 3}      # confirm (A) on the bottom button
SDL_COMMON = {5: 9, 6: 10, 7: K_TRIG_XP, 8: K_TRIG_YP, 9: 6, 10: 4, 11: 11, 12: 12, 13: 13,
              14: 14, 15: 7, 16: 8, 17: K_AXIS_YN, 18: K_AXIS_YP, 19: K_AXIS_XN,
              20: K_AXIS_XP, 21: K_ROT_YN, 22: K_ROT_YP, 23: K_ROT_XN, 24: K_ROT_XP}
# XInput: button code = bit index in wButtons (A=12, B=13, X=14, Y=15); stick Y is up-positive.
XI_FACE_WIIU = {1: 13, 2: 12, 3: 15, 4: 14}
XI_FACE_BOTTOM = {1: 12, 2: 13, 3: 14, 4: 15}
XI_COMMON = {5: 8, 6: 9, 7: K_TRIG_XP, 8: K_TRIG_YP, 9: 4, 10: 5, 11: 0, 12: 1, 13: 2, 14: 3,
             15: 6, 16: 7, 17: K_AXIS_YP, 18: K_AXIS_YN, 19: K_AXIS_XN, 20: K_AXIS_XP,
             21: K_ROT_YP, 22: K_ROT_YN, 23: K_ROT_XN, 24: K_ROT_XP}
SDL_TOUCHPAD = 20

PHYS_PS = {0: "Cross", 1: "Circle", 2: "Square", 3: "Triangle", 4: "Create/Share",
           5: "PS button", 6: "Options", 7: "L3", 8: "R3", 9: "L1", 10: "R1",
           11: "D-pad up", 12: "D-pad down", 13: "D-pad left", 14: "D-pad right",
           15: "Mute", 20: "Touchpad", K_TRIG_XP: "L2", K_TRIG_YP: "R2"}
PHYS_SDL = {0: "bottom button", 1: "right button", 2: "left button", 3: "top button",
            4: "Back/Select", 5: "Home", 6: "Start", 7: "left stick click",
            8: "right stick click", 9: "left bumper", 10: "right bumper", 11: "D-pad up",
            12: "D-pad down", 13: "D-pad left", 14: "D-pad right",
            K_TRIG_XP: "left trigger", K_TRIG_YP: "right trigger"}
PHYS_XI = {0: "D-pad up", 1: "D-pad down", 2: "D-pad left", 3: "D-pad right", 4: "Menu",
           5: "View", 6: "left stick click", 7: "right stick click", 8: "LB", 9: "RB",
           12: "A", 13: "B", 14: "X", 15: "Y", K_TRIG_XP: "LT", K_TRIG_YP: "RT"}

# Cemu's SDL setup (SDLControllerProvider::InitSDL). Same hints -> same device GUIDs.
CEMU_SDL_HINTS = [
    ("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1"), ("SDL_JOYSTICK_ENHANCED_REPORTS", "1"),
    ("SDL_JOYSTICK_HIDAPI_PS4", "1"), ("SDL_JOYSTICK_HIDAPI_PS5", "1"),
    ("SDL_JOYSTICK_HIDAPI_GAMECUBE", "1"), ("SDL_JOYSTICK_HIDAPI_SWITCH", "1"),
    ("SDL_JOYSTICK_HIDAPI_SWITCH2", "1"), ("SDL_JOYSTICK_HIDAPI_JOY_CONS", "1"),
    ("SDL_JOYSTICK_HIDAPI_STADIA", "1"), ("SDL_JOYSTICK_HIDAPI_STEAM", "1"),
    ("SDL_JOYSTICK_HIDAPI_LUNA", "1"),
]
SDL_INIT_GAMEPAD = 0x00002000
SDL_TYPE_XBOX = (2, 3)          # SDL_GAMEPAD_TYPE_XBOX360 / XBOXONE
SDL_TYPE_PS = (4, 5, 6)         # PS3 / PS4 / PS5
SONY_VID = 0x054C

# Default Mii, identical to MH3U Revival's account maker (cosmetic only).
DEFAULT_MII = ("010001100000d73e030034330100010001000100010001000100640065006600610075"
               "006c0074000000000000000100010001000100010001000106010001000100010001"
               "000100010001000100010001000100010001000100010001000100")
DEFAULT_MIINAME = "00640065006600610075006c00740000000000000000"
ACCT_VALID_MARKER = "IsPasswordCacheEnabled=1"

CREATE_NO_WINDOW = 0x08000000
_IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
SDL_LOCK = threading.Lock()


class UserError(Exception):
    """A problem the player can fix; shown as-is."""


# ============================================================================ paths
def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_path(name: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", app_dir())) / name


def install_dir() -> Path:
    env = os.environ.get("MH3U_PLAY_HOME", "").strip()
    if env:
        return Path(env)
    here = app_dir()
    if (here / CEMU_EXE).is_file():          # dropped into an existing bundle folder
        return here
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "MH3U Online"


def client_installed(root) -> bool:
    return (Path(root) / CEMU_EXE).is_file()


def is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


# ============================================================================ config
def _pick(value, options, default):
    return value if value in [v for _, v in options] else default


def load_config(root) -> dict:
    root = Path(root)
    try:
        data = json.loads((root / CONFIG_REL).read_text("utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    cfg = {"graphics": dict(DEFAULT_GRAPHICS), "controls": dict(DEFAULT_CONTROLS), "game": None,
           "settings_version": SETTINGS_VERSION}
    for section in ("graphics", "controls"):
        src = data.get(section)
        if isinstance(src, dict):
            for k, v in src.items():
                if k in cfg[section]:
                    cfg[section][k] = v
    g = cfg["graphics"]
    saved_version = data.get("settings_version", 1) if data else SETTINGS_VERSION
    if not isinstance(saved_version, int) or saved_version < 2:
        g["gamepad_window"] = False
    if not isinstance(saved_version, int) or saved_version < 3:
        g["sound"] = "stereo"
    g["resolution"] = _pick(g["resolution"], RES_OPTIONS, DEFAULT_GRAPHICS["resolution"])
    g["fps"] = _pick(g["fps"], FPS_OPTIONS, DEFAULT_GRAPHICS["fps"])
    g["shadows"] = _pick(g["shadows"], SHADOW_OPTIONS, DEFAULT_GRAPHICS["shadows"])
    g["aniso"] = _pick(g["aniso"], ANISO_OPTIONS, DEFAULT_GRAPHICS["aniso"])
    if g["sound"] not in SOUND_OPTIONS:
        g["sound"] = DEFAULT_GRAPHICS["sound"]
    if g["audio_api"] not in CEMU_AUDIO_APIS:
        g["audio_api"] = DEFAULT_GRAPHICS["audio_api"]
    c = cfg["controls"]
    for k in ("left_deadzone", "right_deadzone"):
        c[k] = min(0.5, max(0.0, float(c[k] or 0)))
    for k in ("left_range", "right_range"):
        c[k] = min(2.0, max(0.5, float(c[k] or 1)))
    if isinstance(data.get("game"), dict):
        cfg["game"] = data["game"]
    if "controls" not in data and (root / CTRL_REL).is_file():
        c["mode"] = "keep"          # an existing Cemu setup: leave the player's profile alone
    return cfg


def save_config(root, cfg) -> None:
    path = Path(root) / CONFIG_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), "utf-8")
    os.replace(tmp, path)


# ============================================================================ versions
def ver_key(tag):
    nums = re.findall(r"\d+", tag or "")
    return tuple(int(n) for n in nums) if nums else None


def is_newer(remote, local) -> bool:
    r, l = ver_key(remote), ver_key(local)
    if r is None:
        return False
    if l is None:
        return True
    n = max(len(r), len(l))
    return r + (0,) * (n - len(r)) > l + (0,) * (n - len(l))


def read_version(root) -> str:
    try:
        return (Path(root) / VERSION_FILE).read_text("utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def write_version(root, tag) -> None:
    (Path(root) / VERSION_FILE).write_text(tag.strip() + "\n", "utf-8")


# ============================================================================ network
def http_get(url, timeout=20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest_release(api=RELEASES_API):
    data = json.loads(http_get(api, 15))
    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])
              if a.get("name") and a.get("browser_download_url")}
    return data.get("tag_name", ""), assets


def download(url, dest, progress=None, timeout=60) -> None:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            buf = r.read(1 << 17)
            if not buf:
                break
            f.write(buf)
            got += len(buf)
            if progress and total:
                progress(min(1.0, got / total))
    os.replace(part, dest)


def resolve_host(host) -> str:
    host = host.strip()
    if _IPV4_RE.match(host):
        return host
    infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_DGRAM)
    if not infos:
        raise OSError(f"no IPv4 address for {host}")
    return infos[0][4][0]


def fetch_status(ip, port=STATUS_PORT, timeout=4) -> dict:
    req = urllib.request.Request(f"http://{ip}:{port}/status", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read(64 * 1024))
    if not isinstance(data, dict):
        raise ValueError("bad status")
    return data


def natcheck_probe(ip, port=NATCHECK_PORT, timeout=2.0, tries=3):
    """The game's first online step: ask the server which address it sees us at."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    reason = "no answer"
    try:
        for _ in range(tries):
            try:
                s.sendto(struct.pack(">IIII", 0x65, 0, 0, 0), (ip, port))
                data, _ = s.recvfrom(64)
            except socket.timeout:
                continue
            except ConnectionResetError:
                reason = "port closed (server not running)"
                continue
            except OSError as e:
                return False, str(e)
            if len(data) >= 16:
                _t, seen_port, seen_ip, _x = struct.unpack(">IIII", data[:16])
                return True, f"{socket.inet_ntoa(struct.pack('>I', seen_ip))}:{seen_port}"
            reason = "unexpected reply"
    finally:
        s.close()
    return False, reason


def format_status(snap) -> str:
    try:
        p, r = int(snap.get("players", 0)), int(snap.get("rooms", 0))
    except (TypeError, ValueError):
        return "online"
    return f"online - {p} hunter{'s' if p != 1 else ''}, {r} room{'s' if r != 1 else ''}"


def server_host() -> str:
    """The game server's address: MH3U_SERVER_HOST, else the server.txt built into the launcher
    (next to mh3u_play.py when it runs from source)."""
    host = os.environ.get("MH3U_SERVER_HOST", "").strip()
    if not host:
        try:
            lines = [ln.strip() for ln in resource_path(SERVER_HOST_FILE).read_text("utf-8").splitlines()
                     if ln.strip() and not ln.strip().startswith("#")]
            host = lines[-1].split()[0] if lines else ""
        except OSError:
            host = ""
    if not host:
        raise UserError("This launcher was built without a server address. Put it into "
                        "launcher\\server.txt and build the launcher again.")
    return host


def check_server() -> dict:
    """Server status for the launcher: ok, players, rooms, ping (ms), detail."""
    out = {"ok": False, "players": None, "rooms": None, "ping": None, "detail": ""}
    try:
        ip = resolve_host(server_host())
    except (OSError, UserError):
        out["detail"] = "can't find the server address"
        return out
    t0 = time.perf_counter()
    ok, _info = natcheck_probe(ip, timeout=1.5, tries=2)
    if ok:
        out["ok"], out["ping"] = True, max(1, round((time.perf_counter() - t0) * 1000))
    if STATUS_PORT:
        try:
            snap = fetch_status(ip)
            out["ok"] = True
            out["players"], out["rooms"] = int(snap.get("players", 0)), int(snap.get("rooms", 0))
        except Exception:
            pass
    if not out["ok"]:
        out["detail"] = "offline or unreachable"
    return out


# ============================================================================ processes
def is_running(exe_name) -> bool:
    if os.name != "nt":
        return False
    try:
        res = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/NH"],
                             capture_output=True, timeout=8, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    # tasklist answers in the console code page (umlauts etc.); the exe name is ASCII.
    out = (res.stdout or b"").decode("latin-1")
    return exe_name.lower() in out.lower()


def monitor_refresh_hz():
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        hz = ctypes.windll.gdi32.GetDeviceCaps(hdc, 116)   # VREFRESH
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return hz if hz and hz > 1 else None
    except Exception:
        return None


# ============================================================================ bundle
def safe_member(name):
    """Zip member -> safe relative path with '/', or None if it would leave the folder."""
    n = name.replace("\\", "/")
    if n.startswith("/") or re.match(r"^[A-Za-z]:", n):
        return None
    parts = [p for p in n.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def is_kept(rel) -> bool:
    r = rel.lower()
    return any(r == k.lower() or r.startswith(k.lower() + "/") for k in KEEP_IF_PRESENT)


def extract_bundle(zip_path, root) -> int:
    root = Path(root)
    written = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = safe_member(info.filename)
            if not rel or rel.lower() in SKIP_FROM_BUNDLE:
                continue
            target = root / rel
            if is_kept(rel) and target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_name(target.name + ".part")
            with zf.open(info) as src, open(part, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            os.replace(part, target)
            written += 1
    return written


def extract_subtree(zip_bytes, folder, dest) -> int:
    """Extract everything under the first `folder/` segment of each member into dest."""
    dest = Path(dest)
    n = 0
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        members = []
        for info in zf.infolist():
            rel = safe_member(info.filename)
            if not rel or info.is_dir():
                continue
            parts = rel.split("/")
            if folder in parts:
                sub = parts[parts.index(folder) + 1:]
                if sub:
                    members.append((info, "/".join(sub)))
        if not members:
            raise ValueError(f"{folder} not found in the download")
        if dest.exists():
            shutil.rmtree(dest)
        for info, sub in members:
            target = dest / sub
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            n += 1
    return n


def ensure_fps120(rules_path) -> None:
    p = Path(rules_path)
    if not p.is_file():
        return
    text = p.read_text("utf-8", errors="replace")
    if FPS120_NAME not in text:
        p.write_text(text.rstrip("\n") + "\n" + FPS120_PRESET, "utf-8", newline="\n")


def install_graphic_packs(root, log, progress, fps_url=None, force=False) -> dict:
    root = Path(root)
    fps_rules = root / FPS_PACK_DIR / "rules.txt"
    gfx_rules = root / GFX_PACK_DIR / "Graphics" / "rules.txt"
    if force or not fps_rules.is_file():
        try:
            local = os.environ.get("MH3U_PLAY_FPS_ZIP")
            data = Path(local).read_bytes() if local else None
            if data is None:
                if not fps_url:
                    _tag, assets = latest_release()
                    fps_url = assets.get(FPS_ASSET)
                data = http_get(fps_url, 60) if fps_url else None
            if data:
                extract_subtree(data, "MH3U_FPS_Cap", root / FPS_PACK_DIR)
            else:
                d = root / FPS_PACK_DIR
                d.mkdir(parents=True, exist_ok=True)
                for name in ("rules.txt", "patches.txt"):
                    (d / name).write_bytes(http_get(f"{RAW_BASE}/graphic_packs/MH3U_FPS_Cap/{name}", 30))
            log("Frame-rate pack ready.")
        except Exception as e:
            log(f"Couldn't get the frame-rate pack ({e}). The game still runs without it.")
    ensure_fps120(fps_rules)
    if force or not gfx_rules.is_file():
        try:
            progress(None, "Getting the resolution pack")
            _tag, assets = latest_release(GFXPACKS_API)
            url = next((u for n, u in assets.items()
                        if n.lower().startswith("graphicpacks") and n.lower().endswith(".zip")), None)
            if not url:
                raise ValueError("no download found")
            extract_subtree(http_get(url, 120), "MonsterHunter3Ultimate", root / GFX_PACK_DIR)
            log("Resolution pack ready.")
        except Exception as e:
            log(f"Couldn't get the resolution pack ({e}). The game runs at its normal resolution.")
    return {"fps": fps_rules.is_file(), "gfx": gfx_rules.is_file()}


# ============================================================================ game dump
def read_title(folder):
    folder = Path(folder)
    try:
        if not ((folder / "code" / "app.xml").is_file() and (folder / "content").is_dir()
                and (folder / "meta").is_dir()):
            return None
        app = ET.parse(folder / "code" / "app.xml").getroot()
    except (OSError, ET.ParseError):
        return None
    tid = (app.findtext("title_id") or "").strip().upper()
    if not re.fullmatch(r"[0-9A-F]{16}", tid):
        return None
    try:
        ver = int((app.findtext("title_version") or "0").strip(), 16)
    except ValueError:
        ver = 0
    return {"path": str(folder), "title_id": tid, "version": ver}


def mh3u_kind(tid):
    tid = tid.upper()
    if tid in MH3U_REGIONS:
        return "base", MH3U_REGIONS[tid]
    base = "00050000" + tid[8:]
    if tid.startswith("0005000E") and base in MH3U_REGIONS:
        return "update", MH3U_REGIONS[base]
    return None, None


def _subdirs(p):
    try:
        return [c for c in sorted(Path(p).iterdir()) if c.is_dir()]
    except OSError:
        return []


def find_mh3u(chosen, install_root=None):
    """Find MH3U (+ its update) in/next to the folder the player picked. None if absent."""
    chosen = Path(chosen)
    if chosen.is_file():
        chosen = chosen.parent
    if chosen.name.lower() in ("code", "content", "meta"):
        chosen = chosen.parent
    if read_title(chosen):
        cands = [chosen] + _subdirs(chosen.parent)
    else:
        lvl1 = _subdirs(chosen)
        cands = list(lvl1)
        for d in lvl1:
            cands += _subdirs(d)
    if install_root:
        mlc = Path(install_root) / MLC_TITLE_REL
        for tid in MH3U_REGIONS:
            cands.append(mlc / "00050000" / tid[8:].lower())
            cands.append(mlc / "0005000e" / tid[8:].lower())
    bases, updates, seen = [], [], set()
    for c in cands:
        key = str(c).lower()
        if key in seen:
            continue
        seen.add(key)
        t = read_title(c)
        if not t:
            continue
        kind, region = mh3u_kind(t["title_id"])
        if kind:
            t["region"] = region
            (bases if kind == "base" else updates).append(t)
    if not bases:
        return None
    base = bases[0]
    ups = [u for u in updates if u["region"] == base["region"]]
    return {"kind": "folder", "base": base,
            "update": max(ups, key=lambda u: u["version"]) if ups else None}


def find_update(chosen, region=None):
    """The MH3U update in/under the folder the player picked (prefers the game's region)."""
    chosen = Path(chosen)
    if chosen.name.lower() in ("code", "content", "meta"):
        chosen = chosen.parent
    cands = [chosen] + _subdirs(chosen)
    for d in _subdirs(chosen):
        cands += _subdirs(d)
    ups = []
    for c in cands:
        t = read_title(c)
        if t:
            kind, reg = mh3u_kind(t["title_id"])
            if kind == "update":
                t["region"] = reg
                ups.append(t)
    if region:
        ups = [u for u in ups if u["region"] == region] or ups
    return max(ups, key=lambda u: u["version"]) if ups else None


def game_label(game) -> str:
    if not game:
        return "No game chosen yet"
    if game.get("kind") == "file":
        upd = game.get("update")
        reg = f" ({game['region']})" if game.get("region") else ""
        return f"Game file: {Path(game['path']).name}{reg}" + (f"  +  update v{upd['version']}" if upd else "")
    base, upd = game["base"], game.get("update")
    text = f"Monster Hunter 3 Ultimate ({base['region']})"
    return text + (f"  +  update v{upd['version']}" if upd else "  -  update missing")


def game_ok(game) -> bool:
    if not game:
        return False
    if game.get("kind") == "file":
        return Path(game["path"]).is_file()
    return read_title(game["base"]["path"]) is not None


def game_paths_for(root, game) -> list:
    mlc = Path(root) / MLC_TITLE_REL
    paths = []
    if game.get("kind") == "file":
        paths.append(str(Path(game["path"]).resolve().parent))
    for t in [game.get("base"), game.get("update")] + list(game.get("extra_updates") or []):
        if t and not is_within(Path(t["path"]), mlc):
            paths.append(str(Path(t["path"]).resolve().parent))
    out = []
    for p in paths:
        if p.lower() not in [o.lower() for o in out]:
            out.append(p)
    return out


def launch_path(game) -> str:
    return game["path"] if game.get("kind") == "file" else game["base"]["path"]


# ============================================================================ cemu settings
def _child(parent, tag):
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag)
    return el


def _set(parent, tag, value) -> None:
    _child(parent, tag).text = str(value)


def write_xml(root_el, path, indent="    ") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root_el, space=indent)
    data = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root_el, encoding="unicode") + "\n"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data, "utf-8", newline="\n")
    os.replace(tmp, path)


def apply_cemu_settings(root, game_paths, gfx, packs) -> None:
    path = Path(root) / SETTINGS_REL
    try:
        content = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        content = ET.Element("content")
    gp = _child(content, "GamePaths")
    have = {(e.text or "").strip().replace("/", "\\").rstrip("\\").lower() for e in gp.findall("Entry")}
    for p in game_paths:
        norm = str(p).replace("/", "\\").rstrip("\\")
        if norm.lower() not in have:
            ET.SubElement(gp, "Entry").text = norm
            have.add(norm.lower())
    graphic = _child(content, "Graphic")
    _set(graphic, "api", 1 if gfx.get("api") == "vulkan" else 0)
    _set(graphic, "VSync", 1 if gfx.get("vsync") else 0)
    overlay = _child(graphic, "Overlay")
    _set(overlay, "Position", 1 if gfx.get("show_fps") else 0)
    _set(overlay, "FPS", "true")
    _set(content, "open_pad", "true" if gfx.get("gamepad_window") else "false")
    _set(content, "fullscreen", "true" if gfx.get("fullscreen") else "false")
    # Sound: XAudio2 (default) or Cubeb, TV output in stereo (default) or 5.1 surround. A device
    # the player chose in Cemu is kept as long as the audio API stays the same.
    audio = _child(content, "Audio")
    api = CEMU_AUDIO_APIS.get(gfx.get("audio_api"), CEMU_AUDIO_APIS["xaudio2"])
    if ((audio.findtext("api") or "").strip() != str(api)
            or not (audio.findtext("TVDevice") or "").strip()):
        _set(audio, "TVDevice", CEMU_DEFAULT_AUDIO_DEVICE)
    _set(audio, "api", api)
    _set(audio, "TVChannels", CEMU_TV_CHANNELS.get(gfx.get("sound"), CEMU_TV_CHANNELS["stereo"]))
    packs_el = _child(content, "GraphicPack")
    ours = {FPS_PACK_KEY.lower(), GFX_PACK_KEY.lower()}
    for e in list(packs_el.findall("Entry")):
        fn = (e.get("filename") or e.findtext("filename") or "").replace("/", "\\").lower()
        if fn in ours:
            packs_el.remove(e)
    if packs.get("gfx"):
        e = ET.SubElement(packs_el, "Entry", {"filename": GFX_PACK_KEY})
        for cat, val in (("TV Resolution", gfx["resolution"]), ("Shadow Quality", gfx["shadows"]),
                         ("Anisotropic Filtering", gfx["aniso"])):
            pr = ET.SubElement(e, "Preset")
            ET.SubElement(pr, "category").text = cat
            ET.SubElement(pr, "preset").text = val
    if packs.get("fps"):
        e = ET.SubElement(packs_el, "Entry", {"filename": FPS_PACK_KEY})
        ET.SubElement(ET.SubElement(e, "Preset"), "preset").text = gfx["fps"]
    write_xml(content, path)


def _num(x) -> str:
    return f"{float(x):.3f}".rstrip("0").rstrip(".") or "0"


def controller_mapping(api, confirm_bottom) -> dict:
    if api == "XInput":
        m = dict(XI_FACE_BOTTOM if confirm_bottom else XI_FACE_WIIU)
        m.update(XI_COMMON)
    else:
        m = dict(SDL_FACE_BOTTOM if confirm_bottom else SDL_FACE_WIIU)
        m.update(SDL_COMMON)
    return m


def controller_profile(dev, controls) -> ET.Element:
    api = dev["api"]
    mapping = controller_mapping(api, controls.get("confirm_bottom"))
    if api == "SDLController" and dev.get("kind") == "playstation":
        mapping[26] = SDL_TOUCHPAD            # touchpad click swaps TV / GamePad screen
    root = ET.Element("emulated_controller")
    ET.SubElement(root, "type").text = "Wii U GamePad"
    ET.SubElement(root, "toggle_display").text = "1"
    c = ET.SubElement(root, "controller")
    ET.SubElement(c, "api").text = api
    ET.SubElement(c, "uuid").text = dev["uuid"]
    ET.SubElement(c, "display_name").text = dev.get("name") or "Controller"
    ET.SubElement(c, "rumble").text = "0.5" if controls.get("rumble") else "0"
    for tag, dz, rng in (("axis", controls["left_deadzone"], controls["left_range"]),
                         ("rotation", controls["right_deadzone"], controls["right_range"]),
                         ("trigger", 0.15, 1.0)):
        n = ET.SubElement(c, tag)
        ET.SubElement(n, "deadzone").text = _num(dz)
        ET.SubElement(n, "range").text = _num(rng)
    maps = ET.SubElement(c, "mappings")
    for k in sorted(mapping):
        e = ET.SubElement(maps, "entry")
        ET.SubElement(e, "mapping").text = str(k)
        ET.SubElement(e, "button").text = str(mapping[k])
    return root


def write_controller_profile(root, dev, controls) -> None:
    path = Path(root) / CTRL_REL
    bak = path.with_name("controller0.before_launcher.xml")
    if path.is_file() and not bak.exists():
        shutil.copy2(path, bak)
    write_xml(controller_profile(dev, controls), path, indent="\t")


def cemu_stick_output(length, deadzone, rng) -> float:
    """What Cemu hands the game for a stick pushed `length` (0..1), per
    ControllerBase::apply_axis_setting (scaled radial deadzone, then range)."""
    if length < deadzone or length <= 0:
        return 0.0
    out = (length * rng - deadzone) / (1.0 - deadzone) if deadzone < 1 else 0.0
    return max(0.0, min(1.0, out))


# ============================================================================ account
def make_pid() -> str:
    return secrets.choice("456") + "".join(secrets.choice("0123456789abcdef") for _ in range(7))


def account_dat_text(pid_hex) -> str:
    lines = ["AccountInstance_20120705", "PersistentId=80000001",
             f"TransferableIdBase={secrets.token_hex(8)}", f"Uuid={secrets.token_hex(16)}",
             f"MiiData={DEFAULT_MII}", f"MiiName={DEFAULT_MIINAME}",
             f"AccountId=CemuMH3U{pid_hex[-4:]}", "BirthYear=0", "BirthMonth=0", "BirthDay=0",
             "Gender=0", "EmailAddress=", "Country=0", "SimpleAddressId=0",
             f"PrincipalId={pid_hex}", "IsPasswordCacheEnabled=1",
             f"AccountPasswordCache={secrets.token_hex(32)}"]
    return "\n".join(lines) + "\n"


def ensure_account(root, log) -> None:
    acct = Path(root) / ACTDIR_REL / "account.dat"
    if acct.is_file():
        try:
            if ACCT_VALID_MARKER in acct.read_text("utf-8", errors="replace"):
                return
        except OSError:
            pass
        bak = acct.with_suffix(".dat.offline.bak")
        try:
            if bak.exists():
                bak.unlink()
            acct.replace(bak)
        except OSError:
            pass
    acct.parent.mkdir(parents=True, exist_ok=True)
    with open(acct, "w", newline="\n", encoding="utf-8") as f:
        f.write(account_dat_text(make_pid()))
    log("Created your online hunter identity.")


def write_server_file(root, ip) -> None:
    p = Path(root) / SRVFILE_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="\n", encoding="utf-8") as f:
        f.write(ip.strip() + "\n")


# ============================================================================ controllers
class SDLGUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_uint8 * 16)]


class SDL3:
    """The few SDL3 calls we need, with Cemu's hints, so GUIDs match Cemu's."""

    def __init__(self, dll_path):
        d = ctypes.CDLL(str(dll_path))
        C = ctypes

        def fn(name, res, *args):
            f = getattr(d, name)
            f.restype, f.argtypes = res, list(args)
            return f
        self.SetHint = fn("SDL_SetHint", C.c_bool, C.c_char_p, C.c_char_p)
        self.Init = fn("SDL_Init", C.c_bool, C.c_uint32)
        self.Quit = fn("SDL_Quit", None)
        self.GetError = fn("SDL_GetError", C.c_char_p)
        self.UpdateJoysticks = fn("SDL_UpdateJoysticks", None)
        self.GetGamepads = fn("SDL_GetGamepads", C.POINTER(C.c_uint32), C.POINTER(C.c_int))
        self.free = fn("SDL_free", None, C.c_void_p)
        self.NameForID = fn("SDL_GetGamepadNameForID", C.c_char_p, C.c_uint32)
        self.GUIDForID = fn("SDL_GetGamepadGUIDForID", SDLGUID, C.c_uint32)
        self.TypeForID = fn("SDL_GetGamepadTypeForID", C.c_int, C.c_uint32)
        self.VendorForID = fn("SDL_GetGamepadVendorForID", C.c_uint16, C.c_uint32)
        self.Open = fn("SDL_OpenGamepad", C.c_void_p, C.c_uint32)
        self.Close = fn("SDL_CloseGamepad", None, C.c_void_p)
        self.Button = fn("SDL_GetGamepadButton", C.c_bool, C.c_void_p, C.c_int)
        self.Axis = fn("SDL_GetGamepadAxis", C.c_int16, C.c_void_p, C.c_int)

    def start(self):
        for k, v in CEMU_SDL_HINTS:
            self.SetHint(k.encode(), v.encode())
        if not self.Init(SDL_INIT_GAMEPAD):
            raise RuntimeError((self.GetError() or b"SDL init failed").decode("utf-8", "replace"))
        for _ in range(6):                     # let HIDAPI finish finding devices
            self.UpdateJoysticks()
            time.sleep(0.05)

    def gamepads(self):
        n = ctypes.c_int(0)
        ids = self.GetGamepads(ctypes.byref(n))
        out, counter = [], {}
        try:
            for i in range(n.value):
                jid = ids[i]
                guid = bytes(self.GUIDForID(jid).data).hex()
                idx = counter.get(guid, 0)
                counter[guid] = idx + 1
                out.append({"id": jid, "guid": guid, "index": idx,
                            "name": (self.NameForID(jid) or b"").decode("utf-8", "replace"),
                            "type": self.TypeForID(jid), "vendor": self.VendorForID(jid)})
        finally:
            if ids:
                self.free(ids)
        return out


def open_sdl():
    path = resource_path("SDL3.dll")
    if not path.is_file():
        return None
    s = SDL3(path)
    s.start()
    return s


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [("wButtons", ctypes.c_ushort), ("bLeftTrigger", ctypes.c_ubyte),
                ("bRightTrigger", ctypes.c_ubyte), ("sThumbLX", ctypes.c_short),
                ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short)]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_uint32), ("Gamepad", XINPUT_GAMEPAD)]


class XInput:
    def __init__(self):
        self.dll = None
        for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                self.dll = ctypes.WinDLL(name)
                break
            except (OSError, AttributeError):
                continue
        if self.dll:
            self.dll.XInputGetState.argtypes = [ctypes.c_uint32, ctypes.POINTER(XINPUT_STATE)]
            self.dll.XInputGetState.restype = ctypes.c_uint32

    def state(self, slot):
        if not self.dll:
            return None
        st = XINPUT_STATE()
        return st if self.dll.XInputGetState(slot, ctypes.byref(st)) == 0 else None

    def slots(self):
        return [i for i in range(4) if self.state(i) is not None]


def list_controllers(sdl, xi) -> list:
    devs = []
    slots = xi.slots() if xi else []
    for s in slots:
        devs.append({"key": f"xinput:{s}", "api": "XInput", "uuid": str(s), "kind": "xbox",
                     "name": f"Xbox controller {s + 1}", "label": f"Xbox controller (slot {s + 1})"})
    if sdl:
        for g in sdl.gamepads():
            if g["type"] in SDL_TYPE_XBOX and slots:
                continue                      # Cemu reads Xbox pads through XInput
            if g["type"] in SDL_TYPE_PS or g["vendor"] == SONY_VID:
                kind, label = "playstation", f"PlayStation: {g['name'] or 'controller'}"
            elif g["type"] in SDL_TYPE_XBOX:
                kind, label = "xbox", g["name"] or "Xbox controller"
            else:
                kind, label = "other", g["name"] or "Controller"
            uuid = f"{g['index']}_{g['guid']}"
            devs.append({"key": f"sdl:{uuid}", "api": "SDLController", "uuid": uuid,
                         "kind": kind, "name": g["name"] or "Controller", "label": label,
                         "sdl_id": g["id"], "type": g["type"]})
    return devs


def detect_controllers_once() -> list:
    xi = XInput()
    with SDL_LOCK:
        sdl = None
        try:
            sdl = open_sdl()
        except Exception:
            sdl = None
        try:
            return list_controllers(sdl, xi)
        finally:
            if sdl:
                sdl.Quit()


def choose_device(devs, saved):
    if not devs:
        return None
    if saved:
        for d in devs:
            if d["key"] == saved.get("key"):
                return d
        for d in devs:
            if d["kind"] == saved.get("kind"):
                return d
    for kind in ("playstation", "xbox", "other"):
        for d in devs:
            if d["kind"] == kind:
                return d
    return devs[0]


def public_device(dev) -> dict:
    return {k: dev[k] for k in ("key", "api", "uuid", "kind", "name", "label") if k in dev}


# ============================================================================ jobs
# ============================================================================ sound fix (patched Cemu)
# MH3U Revival's game client (Cemu, Matt-Wood-23/Cemu mh3u-revival at 3163f35) has two Cemu
# sound bugs. Its stand-in for the Wii U's reverb clears only the first of the reverb's channels,
# so every effect sound is played again a frame late and footsteps and ambience sound hollow. And
# its voice low-pass filter has the wrong sign and loses its state every 3 ms audio frame, so
# low-passed sounds (stomps, monster sounds) crackle softly. The launcher carries that same Cemu
# built with both fixes (cemu_soundfix\, see its README) and swaps it in for exactly that client
# or an earlier build of the fix. Any other client (a newer MH3U Revival release) is left alone.
SOUNDFIX_DIR = "cemu_soundfix"
_HASH_CACHE = {}


def file_sha256(path) -> str:
    p = Path(path)
    st = p.stat()
    key = (str(p).lower(), st.st_size, st.st_mtime_ns)
    if key not in _HASH_CACHE:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _HASH_CACHE[key] = h.hexdigest()
    return _HASH_CACHE[key]


def soundfix_info(folder=None):
    """The patched Cemu the launcher carries: {exe, sha256, replaces, ...}, or None."""
    d = Path(folder) if folder else resource_path(SOUNDFIX_DIR)
    try:
        info = json.loads((d / "soundfix.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    exe = d / CEMU_EXE
    if not exe.is_file() or not info.get("sha256") or not isinstance(info.get("replaces"), list):
        return None
    return dict(info, exe=exe)


def soundfix_state(root, info) -> str:
    """'fixed', 'fixable' (the client the fix was built for, not swapped yet), 'other' or 'none'."""
    target = Path(root) / CEMU_EXE
    if not info or not target.is_file():
        return "none"
    try:
        current = file_sha256(target)
    except OSError:
        return "none"
    if current == info["sha256"]:
        return "fixed"
    return "fixable" if current in info["replaces"] else "other"


def apply_sound_fix(root, info) -> bool:
    """Swap in the patched Cemu if the installed client is the one it was built for. -> swapped"""
    if soundfix_state(root, info) != "fixable":
        return False
    target = Path(root) / CEMU_EXE
    tmp = target.with_name(CEMU_EXE + ".soundfix.tmp")
    shutil.copyfile(info["exe"], tmp)
    if file_sha256(tmp) != info["sha256"]:
        tmp.unlink()
        raise OSError("the fixed game client didn't copy correctly")
    os.replace(tmp, target)
    return True


def install_sound_fix(root, log) -> None:
    """Called whenever Cemu isn't running and is about to be used or was just installed."""
    try:
        if apply_sound_fix(root, soundfix_info()):
            log("Sound fix installed: effects no longer sound hollow, stomps and monster sounds no longer crackle.")
    except OSError as e:
        log(f"Couldn't install the sound fix ({e}). The game still starts, with hollow and crackling effect sounds.")


def job_install(root, log, progress, remote=None) -> None:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if is_running(CEMU_EXE):
        raise UserError("Close Monster Hunter (Cemu) first, then try again.")
    local_zip = os.environ.get("MH3U_PLAY_BUNDLE_ZIP")
    assets = {}
    if local_zip:
        tag, zip_path = os.environ.get("MH3U_PLAY_BUNDLE_TAG", "local"), Path(local_zip)
    else:
        try:
            tag, assets = remote or latest_release()
        except Exception as e:
            raise UserError(f"Couldn't reach GitHub to download the game client ({e}). "
                            "Check your internet connection and try again.")
        url = assets.get(BUNDLE_ASSET)
        if not url:
            raise UserError("The game client download wasn't found. Try again later.")
        zip_path = root / P / "downloads" / BUNDLE_ASSET
        log(f"Downloading the game client ({tag}, about 60 MB)...")
        download(url, zip_path, lambda f: progress(f, "Downloading the game client"))
    progress(None, "Unpacking")
    n = extract_bundle(zip_path, root)
    write_version(root, tag)
    log(f"Game client ready ({tag}, {n} files).")
    install_sound_fix(root, log)
    install_graphic_packs(root, log, progress, fps_url=assets.get(FPS_ASSET), force=True)
    if not local_zip:
        try:
            zip_path.unlink()
        except OSError:
            pass
    progress(1.0, "Ready")


def job_play(root, cfg, log, progress, launch=True):
    """Write every setting, then start the game. Returns (cemu command, device used)."""
    root = Path(root)
    game = cfg.get("game")
    if not game_ok(game):
        raise UserError("Choose your copy of Monster Hunter 3 Ultimate first (Game Files).")
    if is_running(CEMU_EXE):
        raise UserError("Monster Hunter is already running. Close it first, then press Start Game again.")
    install_sound_fix(root, log)
    keys = import_keys_files(root)
    if keys:
        log(f"{keys} key(s) from keys.txt next to MH3U_Play.exe added.")
    if game.get("kind") == "file" and Path(game["path"]).suffix.lower() in DISC_EXTS and not has_disc_key(root):
        raise UserError("Your disc image needs its disc key. Put your keys.txt next to MH3U_Play.exe, "
                        "or paste the key in Game Files > Disc key.")
    progress(None, "Getting ready")
    packs = install_graphic_packs(root, log, progress)
    apply_cemu_settings(root, game_paths_for(root, game), cfg["graphics"], packs)
    log("Graphics settings applied.")
    used = None
    controls = cfg["controls"]
    if controls.get("mode") == "auto":
        dev = choose_device(detect_controllers_once(), controls.get("device"))
        if dev:
            write_controller_profile(root, dev, controls)
            used = public_device(dev)
            log(f"Controller: {dev['label']}.")
        elif controls.get("device"):
            write_controller_profile(root, controls["device"], controls)
            log(f"No controller found right now - using {controls['device'].get('label')}. "
                "Connect it before the game starts.")
        else:
            log("No controller found. Plug in your Xbox or PlayStation controller and press Play again.")
    ensure_account(root, log)
    try:
        ip = resolve_host(server_host())
    except OSError as e:
        raise UserError(f"Can't look up the server address ({e}). Check your internet connection.")
    write_server_file(root, ip)
    cmd = [str(root / CEMU_EXE), "-g", launch_path(game)]
    if cfg["graphics"].get("fullscreen"):
        cmd.append("-f")
    if launch and os.environ.get("MH3U_NOLAUNCH") != "1":
        subprocess.Popen(cmd, cwd=str(root), close_fds=True)
        log("Starting Monster Hunter 3 Ultimate - happy hunting!")
    else:
        log("(launch skipped) " + subprocess.list2cmdline(cmd))
    progress(1.0, "Game started" if launch else "Ready")
    return cmd, used


def job_open_cemu(root, cfg, log) -> None:
    """Open Cemu itself (no game) so the player can use its own input settings."""
    root = Path(root)
    if is_running(CEMU_EXE):
        raise UserError("Cemu is already open.")
    install_sound_fix(root, log)
    ensure_account(root, log)
    write_server_file(root, resolve_host(server_host()))
    subprocess.Popen([str(root / CEMU_EXE)], cwd=str(root), close_fds=True)
    log("Cemu opened: Options > Input settings. Close Cemu when you're done.")


# ============================================================================ disc keys
KEYS_REL = f"{P}/keys.txt"
DISC_EXTS = (".wud", ".wux", ".iso")
FILE_EXTS = (".wua",) + DISC_EXTS


def find_disc_key(image_path):
    """A disc key dumped next to the image: game.key / <name>.key (16 bytes) or 32 hex chars."""
    image = Path(image_path)
    cands = [image.with_suffix(".key"), image.parent / "game.key", image.parent / "disc.key"]
    cands += sorted(p for p in image.parent.glob("*.key") if p not in cands)
    for p in cands:
        try:
            if not p.is_file() or p.stat().st_size > 4096 or p.name.lower() == "common.key":
                continue
            data = p.read_bytes()
        except OSError:
            continue
        if len(data) == 16:
            return data.hex()
        m = re.search(rb"\b([0-9a-fA-F]{32})\b", data)
        if m:
            return m.group(1).decode().lower()
    return None


def add_disc_key(root, key_hex, label="MH3U disc key") -> bool:
    key = (key_hex or "").strip().lower().replace(" ", "").replace("-", "")
    if not re.fullmatch(r"[0-9a-f]{32}", key):
        raise UserError("A disc key is 32 letters and numbers (0-9, a-f).")
    p = Path(root) / KEYS_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    text = p.read_text("utf-8", errors="replace") if p.is_file() else ""
    if key in text.lower():
        return False
    with open(p, "a", encoding="utf-8", newline="") as f:
        if text and not text.endswith("\n"):
            f.write("\r\n")
        f.write(f"{key} # {label} (added by the MH3U Online launcher)\r\n")
    return True


def _key_lines(text):
    """(key, comment) for each 32-hex-character key in a keys.txt ('#' or ';' starts a comment)."""
    for line in text.splitlines():
        body, _, comment = line.replace(";", "#", 1).partition("#")
        key = body.strip().replace(" ", "").replace("-", "").lower()
        if re.fullmatch(r"[0-9a-f]{32}", key):
            yield key, comment.strip()


def import_keys_files(root, sources=None) -> int:
    """Disc keys from a keys.txt next to MH3U_Play.exe (or in its updates folder), added to the
    game client's keys.txt so players never have to paste them. -> number of keys added."""
    dst = Path(root) / KEYS_REL
    added = 0
    for src in sources or [app_dir() / "keys.txt", updates_dir() / "keys.txt"]:
        src = Path(src)
        try:
            if not src.is_file() or src.stat().st_size > 1024 * 1024:
                continue
            if dst.exists() and src.resolve() == dst.resolve():
                continue
            text = src.read_text("utf-8", errors="replace")
        except OSError:
            continue
        for key, comment in _key_lines(text):
            if add_disc_key(root, key, comment or f"from {src.name} next to MH3U_Play.exe"):
                added += 1
    return added


def has_disc_key(root) -> bool:
    p = Path(root) / KEYS_REL
    try:
        for line in p.read_text("utf-8", errors="replace").splitlines():
            line = line.split("#")[0].split(";")[0].strip().replace(" ", "")
            if re.fullmatch(r"[0-9a-fA-F]{32}", line) and line.lower() != "541b9889519b27d363cd21604b97c67a":
                return True
    except OSError:
        pass
    return False


def find_updates_near(folder):
    """MH3U update folders next to a disc image / archive (folder format only)."""
    ups = []
    for c in _subdirs(folder):
        t = read_title(c)
        if t:
            kind, region = mh3u_kind(t["title_id"])
            if kind == "update":
                t["region"] = region
                ups.append(t)
    return max(ups, key=lambda u: u["version"]) if ups else None


REGION_BY_DISC_LETTER = {"E": "US", "P": "EU", "J": "JP"}


def disc_region(image_path):
    """Region from the disc header (WUP-P-xxxR) at the start of a .wud/.iso or inside a .wux."""
    try:
        with open(image_path, "rb") as f:
            head = f.read(8 * 1024 * 1024)
    except OSError:
        return None
    m = re.search(rb"WUP-P-[A-Z0-9]{3}([A-Z])", head)
    return REGION_BY_DISC_LETTER.get(m.group(1).decode()) if m else None


def find_game_near_launcher(folder=None):
    """MH3U next to MH3U_Play.exe: a .wua/.wux/.wud/.iso file (one named MH3U / Monster Hunter
    first; a single game file whatever its name), else a dumped [Game] folder there."""
    base = Path(folder or app_dir())
    try:
        files = [p for p in sorted(base.iterdir()) if p.suffix.lower() in FILE_EXTS and p.is_file()]
    except OSError:
        files = []
    named = [p for p in files if re.search(r"(?i)mh3|monster.?hunter", p.name)]
    pick = named[:1] or (files if len(files) == 1 else [])
    if pick:
        path = pick[0].resolve()
        game = {"kind": "file", "path": str(path)}
        if path.suffix.lower() in DISC_EXTS:
            game["region"] = disc_region(path)
        return game
    return find_mh3u(base)


_SKIP_DIRS = {"windows", "program files","program files (x86)", "programdata", "$recycle.bin",
              "system volume information", "appdata", "node_modules", ".git", "shadercache",
              "graphicpacks", "gameprofiles", "resources", "steamapps", "content", "code", "meta"}
_LOOKS_LIKE = ("game", "wii", "cemu", "emu", "rom", "dump", "mh3", "monster", "nintendo")


def _update_roots(extra=()):
    home = Path.home()
    roots = [Path(p) for p in extra]
    # The launcher's own folder first: players can drop their dumped [Update] folder next to MH3U_Play.exe.
    roots.append(app_dir())
    roots += [home / "Downloads", home / "Desktop", home / "Documents", home / "Games", home / "OneDrive"]
    for env in ("APPDATA", "LOCALAPPDATA"):
        if os.environ.get(env):
            roots.append(Path(os.environ[env]) / "Cemu")
    for letter in "CDEFGHIJKLMN":
        drive = Path(f"{letter}:/")
        try:
            if not drive.exists():
                continue
        except OSError:
            continue
        roots += [c for c in _subdirs(drive) if any(k in c.name.lower() for k in _LOOKS_LIKE)]
    return roots


def find_updates_anywhere(extra=(), budget=6.0) -> dict:
    """Look for MH3U updates (folder format) on this PC: next to the game, in the usual
    folders and inside other Cemu installs. -> {region: newest update}. Time-boxed."""
    return find_updates_in(_update_roots(extra), budget)


def find_updates_in(roots, budget=6.0, depth=4) -> dict:
    """MH3U updates (folder format) in or under `roots`, up to `depth` folders down, also inside
    Cemu installs found there. -> {region: newest update}. Time-boxed."""
    deadline = time.time() + budget
    found, seen = {}, set()

    def take(t):
        kind, region = mh3u_kind(t["title_id"])
        if kind == "update":
            t["region"] = region
            if region not in found or t["version"] > found[region]["version"]:
                found[region] = t

    def visit(d, depth):
        if depth < 0 or time.time() > deadline:
            return
        key = str(d).lower()
        if key in seen:
            return
        seen.add(key)
        t = read_title(d)
        if t:
            take(t)
            return
        for mlc in (d / "mlc01", d / "portable" / "mlc01", d):
            for tid in MH3U_REGIONS:
                u = read_title(mlc / "usr" / "title" / "0005000e" / tid[8:].lower())
                if u:
                    take(u)
        for sub in _subdirs(d):
            if sub.name.lower() not in _SKIP_DIRS:
                visit(sub, depth - 1)

    for r in roots:
        visit(Path(r), depth)
    return found


def _fitting_update(game, found):
    """The update in `found` ({region: update}) that fits `game`, plus all of them when the
    game's region is unknown (Cemu then picks the one that fits). -> (update or None, extras)."""
    region = (game.get("base") or {}).get("region") or game.get("region")
    if region:
        return found.get(region), None
    if len(found) == 1:
        return next(iter(found.values())), None
    return found.get("US") or next(iter(found.values())), list(found.values())


def auto_attach_update(game, root, budget=6.0):
    """Give `game` the matching update if one exists on this PC (no questions asked)."""
    if not game:
        return None
    if game.get("update"):
        return game["update"]
    if game.get("kind") == "file":
        near = [Path(game["path"]).parent, Path(game["path"]).parent.parent]
    else:
        near = [Path(game["base"]["path"]).parent]
    found = find_updates_anywhere(near + [Path(root)], budget)
    if not found:
        return None
    upd, extras = _fitting_update(game, found)
    if extras:
        game["extra_updates"] = extras
    if upd:
        game["update"] = upd
    return upd


UPDATES_DIR_NAME = "updates"


def updates_dir() -> Path:
    """The folder next to MH3U_Play.exe that players drop their dumped game updates into."""
    return app_dir() / UPDATES_DIR_NAME


def refresh_update(game, folder=None):
    """Run before every start. Forgets an update that was moved or deleted, then uses the newest
    update for this game from the updates folder (any folder depth inside it) when the game
    has none yet or only an older one. -> (update that was gone or None, update now used or None)."""
    if not game:
        return None, None
    gone = None
    cur = game.get("update")
    if cur and not read_title(cur["path"]):
        gone, cur = cur, None
        game["update"] = None
    if game.get("extra_updates"):
        game["extra_updates"] = [u for u in game["extra_updates"] if read_title(u["path"])] or None
    found = find_updates_in([folder or updates_dir()], budget=3.0)
    upd, extras = _fitting_update(game, found) if found else (None, None)
    if not upd or (cur and cur["version"] >= upd["version"]):
        return gone, None
    game["update"] = upd
    if extras:
        game["extra_updates"] = extras
    return gone, upd


# MH3U's footsteps, ambience and other effects go through the Wii U's multi-channel reverb
# (AXFXMultiChReverb in snd_user / snduser2). Cemu only has a stand-in for it whose clean-up
# loop clears the first of the 6 reverb channels only (its sample counter isn't reset per
# channel), so the effects' reverb send comes back a frame late on the other 5 and sounds
# hollow, like through a tube. Cemu loads the Wii U's own libraries instead when they're in its
# cafeLibs folder (portable\cafeLibs, the user data folder in portable mode).
SOUND_LIBS = ("snd_user.rpl", "snduser2.rpl")
CAFELIBS_REL = Path("portable") / "cafeLibs"


def _is_rpl(path) -> bool:
    """A Wii U library: a 32-bit big-endian ELF file."""
    try:
        with open(path, "rb") as f:
            head = f.read(6)
        return head[:4] == b"\x7fELF" and head[4] == 1 and head[5] == 2 and Path(path).stat().st_size > 4096
    except OSError:
        return False


def find_sound_libs(folder=None, budget=2.0, depth=4) -> dict:
    """The player's snd_user.rpl / snduser2.rpl: in the updates folder (any folder depth) or
    right next to MH3U_Play.exe. -> {file name: path}"""
    deadline = time.time() + budget
    found = {}

    def take(p):
        name = p.name.lower()
        if name in SOUND_LIBS and name not in found and p.is_file() and _is_rpl(p):
            found[name] = p

    def visit(d, depth):
        if depth < 0 or time.time() > deadline or len(found) == len(SOUND_LIBS):
            return
        try:
            entries = sorted(Path(d).iterdir())
        except OSError:
            return
        for e in entries:
            take(e)
        for e in entries:
            if e.is_dir():
                visit(e, depth - 1)

    visit(folder or updates_dir(), depth)
    if folder is None:
        for name in SOUND_LIBS:
            take(app_dir() / name)
    return found


def install_sound_libs(root, found) -> list:
    """Copy the player's sound libraries to where Cemu loads them. -> names newly copied."""
    dst_dir = Path(root) / CAFELIBS_REL
    copied = []
    for name, src in sorted(found.items()):
        dst = dst_dir / name
        try:
            data = Path(src).read_bytes()
            if dst.is_file() and dst.read_bytes() == data:
                continue
            dst_dir.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, dst)
            copied.append(name)
        except OSError:
            pass
    return copied


def sound_libs_installed(root) -> bool:
    return all(_is_rpl(Path(root) / CAFELIBS_REL / n) for n in SOUND_LIBS)


def updates_in_wrong_format(folder=None):
    """Folders in the updates folder holding Wii U install files (title.tmd and .app files)
    instead of a dump (code, content and meta). The launcher can't use those."""
    out = []
    base = Path(folder or updates_dir())
    for d in [base] + _subdirs(base) + [s for c in _subdirs(base) for s in _subdirs(c)]:
        if (d / "title.tmd").is_file() and not read_title(d):
            out.append(d)
    return out


# ============================================================================ app (pywebview)
def mapping_tables() -> dict:
    """For the page's button test: Cemu button code -> Wii U button, per layout."""
    out = {}
    for api in ("XInput", "SDLController"):
        for ps in ((False, True) if api == "SDLController" else (False,)):
            for bottom in (False, True):
                m = controller_mapping(api, bottom)
                if ps:
                    m[26] = SDL_TOUCHPAD
                key = api + (":ps" if ps else "") + (":bottom" if bottom else ":wiiu")
                out[key] = {str(code): WIIU_NAMES.get(wid, "") for wid, code in m.items()}
    return out


def game_public(game, root=None):
    if not game:
        return None
    is_file = game.get("kind") == "file"
    out = {"ok": game_ok(game), "kind": game.get("kind"), "label": game_label(game),
           "update": bool(game.get("update")),
           "update_version": (game.get("update") or {}).get("version"),
           "region": (game.get("base") or {}).get("region"),
           "disc": is_file and Path(game.get("path", "")).suffix.lower() in DISC_EXTS}
    out["needs_key"] = bool(out["disc"] and root is not None and not has_disc_key(root))
    return out


class PadService(threading.Thread):
    """Owns SDL while the Controls panel is open: lists pads, reports presses + stick positions."""

    def __init__(self, on_devices, on_pressed, on_sticks, on_note):
        super().__init__(daemon=True)
        self.on_devices, self.on_pressed, self.on_sticks, self.on_note = on_devices, on_pressed, on_sticks, on_note
        self.stop_evt = threading.Event()
        self.refresh_evt = threading.Event()
        self.selected = None          # device dict incl. sdl_id

    def run(self):
        xi = XInput()
        sdl = pad = pad_key = None
        with SDL_LOCK:
            try:
                sdl = open_sdl()
                if sdl is None:
                    self.on_note("PlayStation support file missing: only Xbox controllers can be found.")
            except Exception as e:
                self.on_note(f"PlayStation detection unavailable ({e}).")
                sdl = None
            last_sig, next_scan, prev, last_sticks, last_push = None, 0.0, set(), None, 0.0
            try:
                while not self.stop_evt.is_set():
                    if sdl:
                        sdl.UpdateJoysticks()
                    now = time.time()
                    if now >= next_scan or self.refresh_evt.is_set():
                        self.refresh_evt.clear()
                        devs = list_controllers(sdl, xi)
                        sig = [d["key"] for d in devs]
                        if sig != last_sig:
                            last_sig = sig
                            self.on_devices(devs)
                        next_scan = now + 1.5
                    sel = self.selected
                    pressed, sticks = set(), None
                    if sel and sel.get("api") == "XInput":
                        st = xi.state(int(sel["uuid"]))
                        if st:
                            g = st.Gamepad
                            pressed = {b for b in range(16) if g.wButtons >> b & 1}
                            if g.bLeftTrigger > 60:
                                pressed.add(K_TRIG_XP)
                            if g.bRightTrigger > 60:
                                pressed.add(K_TRIG_YP)
                            sticks = (g.sThumbLX / 32767, -g.sThumbLY / 32767, g.sThumbRX / 32767, -g.sThumbRY / 32767)
                    elif sel and sel.get("sdl_id") is not None and sdl:
                        if pad_key != sel["key"]:
                            if pad:
                                sdl.Close(pad)
                            pad = sdl.Open(sel["sdl_id"])
                            pad_key = sel["key"]
                        if pad:
                            pressed = {b for b in range(21) if sdl.Button(pad, b)}
                            if sdl.Axis(pad, 4) > 8000:
                                pressed.add(K_TRIG_XP)
                            if sdl.Axis(pad, 5) > 8000:
                                pressed.add(K_TRIG_YP)
                            sticks = tuple(sdl.Axis(pad, a) / 32767 for a in range(4))
                    if pressed - prev:
                        self.on_pressed(sorted(pressed))
                    prev = pressed
                    if sticks is not None:
                        rounded = tuple(round(max(-1.0, min(1.0, v)), 3) for v in sticks)
                        if rounded != last_sticks and now - last_push > 0.03:
                            last_sticks, last_push = rounded, now
                            self.on_sticks(rounded)
                    time.sleep(0.016)
            finally:
                if pad and sdl:
                    sdl.Close(pad)
                if sdl:
                    sdl.Quit()


class Api:
    """Everything the page can ask for. Private members start with _ so pywebview hides them."""

    def __init__(self):
        self._root = install_dir()
        self._cfg = load_config(self._root)
        self._lock = threading.RLock()
        self._game_lock = threading.Lock()     # the startup update check vs. START GAME
        self._sound_hint_shown = False
        self._busy = False
        self._remote = None
        self._server = {"name": SERVER_NAME, "ok": None, "checked": ""}
        self._devices = None            # full device dicts (with sdl_id) from the pad service
        self._pad = None
        self._log = []
        self._win = None
        self._hz = monitor_refresh_hz()
        if not self._cfg.get("game") and client_installed(self._root):
            found = find_mh3u(self._root / MLC_TITLE_REL, self._root)
            if found:
                self._cfg["game"] = found

    # ------------------------------------------------------------------ internals
    def _emit(self, kind, **data):
        if self._win is None:
            return
        try:
            self._win.run_js("window.MH && MH.event(%s)" % json.dumps(dict(type=kind, **data)))
        except Exception:
            pass

    def _logline(self, text):
        stamp = time.strftime("%H:%M")
        self._log = (self._log + [{"time": stamp, "text": text}])[-200:]
        self._emit("log", text=text, time=stamp)
        try:
            p = self._root / LOG_REL
            if p.parent.is_dir():
                with open(p, "a", encoding="utf-8") as f:
                    f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
        except OSError:
            pass

    def _progress(self, frac, text=None):
        self._emit("progress", frac=frac, text=text)

    def _save(self):
        try:
            save_config(self._root, self._cfg)
        except OSError:
            pass

    def _client(self):
        installed = client_installed(self._root)
        local = read_version(self._root) if installed else ""
        update = self._remote[0] if (installed and self._remote and is_newer(self._remote[0], local)) else None
        return {"installed": installed, "version": local, "update": update}

    def _state(self):
        devs = None if self._devices is None else [public_device(d) for d in self._devices]
        return {"server": self._server, "client": self._client(),
                "game": game_public(self._cfg.get("game"), self._root),
                "graphics": self._cfg["graphics"], "controls": self._cfg["controls"], "devices": devs,
                "mapping": mapping_tables(), "refresh_hz": self._hz, "launcher_version": LAUNCHER_VERSION,
                "sound_libs": sound_libs_installed(self._root),
                "sound_fix": soundfix_state(self._root, soundfix_info()),
                "install_dir": str(self._root)}

    def _job(self, name, fn):
        with self._lock:
            if self._busy:
                return {"error": "Hold on - the launcher is still busy with the last step."}
            self._busy = True
        self._pad_stop()

        def worker():
            err, msg = None, ""
            try:
                msg = fn() or ""
            except UserError as e:
                err = str(e)
            except Exception as e:
                err = f"Something went wrong: {e}"
                self._logline(traceback.format_exc().strip().splitlines()[-1])
            finally:
                with self._lock:
                    self._busy = False
            if err:
                self._logline(err)
            self._emit("done", job=name, error=err, message=msg, state=self._state())
        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True}

    def _pad_stop(self):
        pad, self._pad = self._pad, None
        if pad:
            pad.stop_evt.set()
            pad.join(timeout=2)

    def _on_devices(self, devs):
        self._devices = devs
        saved = self._cfg["controls"].get("device")
        dev = choose_device(devs, saved)
        if dev and (not saved or saved.get("key") != dev["key"]):
            self._cfg["controls"]["device"] = public_device(dev)
            self._save()
        if self._pad:
            self._pad.selected = dev
        self._emit("devices", devices=[public_device(d) for d in devs], controls=self._cfg["controls"])

    def _status_loop(self):
        while True:
            st = check_server()
            # Only online/offline reaches the page: no address, player count or ping.
            self._server = {"name": SERVER_NAME, "ok": st["ok"], "checked": time.strftime("%H:%M")}
            self._emit("status", server=self._server)
            time.sleep(30)

    def _update_check(self):
        try:
            self._remote = latest_release()
            self._emit("state", state={"client": self._client()})
        except Exception:
            pass

    def _refresh_update(self, look_wider=0.0):
        """The updates folder next to MH3U_Play.exe, checked at every start and before every
        game: a newer update dropped there is used automatically. With `look_wider` (seconds),
        a game still without an update also gets the PC-wide search."""
        with self._game_lock:
            game = self._cfg.get("game")
            if not game:
                return False
            gone, used = refresh_update(game)
            if gone:
                self._logline(f"Update v{gone['version']} isn't at {gone['path']} any more.")
            if used:
                self._logline(f"Update v{used['version']} ({used['region']}) found in the updates "
                              "folder - using it.")
            if look_wider and not game.get("update"):
                self._progress(None, "Looking for the game update on this PC")
                if auto_attach_update(game, self._root, look_wider):
                    used = game["update"]
                    self._logline(f"Update v{used['version']} found - using it.")
            if gone or used:
                self._save()
            return bool(gone or used)

    def _install_sound_libs(self, hint=False):
        """The Wii U's own reverb libraries from the updates folder, installed for Cemu."""
        if not client_installed(self._root):
            return False
        copied = install_sound_libs(self._root, find_sound_libs())
        if copied:
            self._logline("Wii U sound files installed (" + ", ".join(copied) + "): footsteps, ambience "
                          "and other effects now get the game's real reverb.")
        elif (hint and not sound_libs_installed(self._root) and not self._sound_hint_shown
              and soundfix_state(self._root, soundfix_info()) not in ("fixed", "fixable")):
            self._sound_hint_shown = True
            self._logline("Footsteps and ambience sound hollow without snd_user.rpl and snduser2.rpl from "
                          "your Wii U. Put them in the updates folder - see Game Files.")
        return bool(copied)

    def _find_game_near_launcher(self):
        """Use MH3U next to MH3U_Play.exe when no game is chosen yet (or the chosen one is gone)."""
        with self._game_lock:
            if game_ok(self._cfg.get("game")):
                return False
            game = find_game_near_launcher()
            if not game:
                return False
            refresh_update(game)
            if not game.get("update"):
                auto_attach_update(game, self._root, 3.0)
            if game.get("kind") == "file" and Path(game["path"]).suffix.lower() in DISC_EXTS:
                key = find_disc_key(Path(game["path"]))
                if key:
                    add_disc_key(self._root, key)
            self._cfg["game"] = game
            self._save()
        self._logline("Game found next to the launcher: " + game_label(game))
        return True

    def _check_updates_folder(self):
        try:
            updates_dir().mkdir(exist_ok=True)
        except OSError:
            pass
        found = self._find_game_near_launcher()
        for d in updates_in_wrong_format():
            self._logline(f"{d.name}: these are Wii U install files (title.tmd and .app), not a dumped "
                          "update. Put in the [Update] folder from Dumpling (code, content and meta).")
        changed = self._refresh_update()
        keys = import_keys_files(self._root) if client_installed(self._root) else 0
        if keys:
            self._logline(f"{keys} key(s) from keys.txt next to MH3U_Play.exe added.")
        if self._install_sound_libs() or changed or keys or found:
            self._emit("state", state={"game": game_public(self._cfg.get("game"), self._root),
                                       "sound_libs": sound_libs_installed(self._root)})

    def _on_start(self):
        threading.Thread(target=self._status_loop, daemon=True).start()
        threading.Thread(target=self._update_check, daemon=True).start()
        threading.Thread(target=self._check_updates_folder, daemon=True).start()

    def _dialog(self, folder):
        import webview
        kind = webview.FileDialog.FOLDER if folder else webview.FileDialog.OPEN
        kwargs = {} if folder else {"file_types": ("Wii U game (*.wua;*.wux;*.wud;*.iso)", "All files (*.*)")}
        res = self._win.create_file_dialog(kind, **kwargs)
        if not res:
            return None
        return res[0] if isinstance(res, (list, tuple)) else res

    # ------------------------------------------------------------------ page API
    def get_state(self):
        st = self._state()
        st["log"] = self._log
        return st

    def install(self):
        remote = self._remote

        def run():
            job_install(self._root, self._logline, self._progress, remote)
            return "Game client installed"
        return self._job("install", run)

    def play(self):
        remote = self._remote

        def run():
            if not client_installed(self._root):
                job_install(self._root, self._logline, self._progress, remote)
            self._find_game_near_launcher()
            self._refresh_update(look_wider=3.0)
            self._install_sound_libs(hint=True)
            cfg = copy.deepcopy(self._cfg)
            _cmd, used = job_play(self._root, cfg, self._logline, self._progress)
            if used:
                self._cfg["controls"]["device"] = used
                self._save()
            return "Game started - good hunting!"
        return self._job("play", run)

    def test_connection(self):
        def run():
            self._progress(None, "Contacting the server")
            ip = resolve_host(server_host())
            ok, _info = natcheck_probe(ip)
            if not ok:
                raise UserError("No answer from the server. It may be offline, or a firewall or "
                                "antivirus blocks the game's network traffic.")
            self._logline("Connection OK - the server answered.")
            return "Connection OK"
        return self._job("test", run)

    def open_cemu(self):
        if not client_installed(self._root):
            return {"error": "Install the game client first."}
        self._cfg["controls"]["mode"] = "keep"
        self._save()
        cfg = copy.deepcopy(self._cfg)
        return self._job("cemu", lambda: job_open_cemu(self._root, cfg, self._logline))

    def pick_folder(self):
        path = self._dialog(True)
        if not path:
            return None
        found = find_mh3u(path, self._root)
        if not found:
            return {"error": "Monster Hunter 3 Ultimate wasn't found there.\n\nChoose the folder that holds your "
                             "MH3U dump (the one with the [Game] and [Update] folders), or the [Game] folder "
                             "itself. It needs the code, content and meta folders inside.\n\nUsing a disc "
                             "image instead? Use 'Choose file'."}
        refresh_update(found)
        if not found.get("update"):
            self._progress(None, "Looking for the game update on this PC")
            auto_attach_update(found, self._root)
            self._progress(0, "")
        self._cfg["game"] = found
        self._save()
        self._logline("Game found: " + game_label(found))
        msg = game_label(found) + "\n\n" + ("The update is used automatically." if found.get("update") else
                                             "No update was found on this PC; the game starts without it.")
        return {"state": self._state(), "message": msg}

    def pick_file(self):
        path = self._dialog(False)
        if not path:
            return None
        p = Path(path)
        if p.suffix.lower() not in FILE_EXTS:
            return {"error": "Choose a .wua, .wux, .wud or .iso file, or use 'Choose folder' for a dump folder."}
        game = {"kind": "file", "path": str(p.resolve())}
        if p.suffix.lower() in DISC_EXTS:
            game["region"] = disc_region(p)
        refresh_update(game)
        if not game.get("update"):
            self._progress(None, "Looking for the game update on this PC")
            auto_attach_update(game, self._root)
            self._progress(0, "")
        upd = game.get("update")
        self._cfg["game"] = game
        self._save()
        self._logline("Game file chosen: " + game_label(game))
        msg = game_label(game) + "\n\n" + ("The update is used automatically." if upd else
                                            "No update was found on this PC; the game starts without it.")
        if p.suffix.lower() in DISC_EXTS:
            key = find_disc_key(p)
            imported = import_keys_files(self._root)
            if key:
                add_disc_key(self._root, key)
                msg += "\n\nThe disc key next to the image was added."
            elif imported:
                msg += f"\n\n{imported} key(s) from the keys.txt next to MH3U_Play.exe were added."
            elif not has_disc_key(self._root):
                msg += ("\n\nThis disc image needs its disc key and none was found next to it (game.key) "
                        "or next to MH3U_Play.exe (keys.txt). Put your keys.txt next to MH3U_Play.exe, "
                        "or paste the key in Game Files > Disc key.")
        return {"state": self._state(), "message": msg}

    def pick_update(self):
        game = self._cfg.get("game")
        if not game:
            return {"error": "Choose your game first, then add its update."}
        path = self._dialog(True)
        if not path:
            return None
        upd = find_update(path, (game.get("base") or {}).get("region"))
        if not upd:
            return {"error": "No MH3U update was found there.\n\nChoose the [Update] folder itself (it has "
                             "code, content and meta inside), or the folder that holds it."}
        base_region = (game.get("base") or {}).get("region")
        if base_region and upd["region"] != base_region:
            return {"error": f"That's the {upd['region']} update, but your game is {base_region}. "
                             "The update has to match your game's region."}
        game["update"] = upd
        self._save()
        self._logline(f"Update v{upd['version']} added.")
        return {"state": self._state(), "message": f"Update v{upd['version']} ({upd['region']}) added."}

    def open_updates_folder(self):
        d = updates_dir()
        try:
            d.mkdir(exist_ok=True)
            os.startfile(str(d))
        except OSError as e:
            return {"error": f"Couldn't open the updates folder ({d}): {e}"}
        return {"ok": True}

    def set_disc_key(self, key):
        try:
            added = add_disc_key(self._root, key)
        except UserError as e:
            return {"error": str(e)}
        self._logline("Disc key " + ("added." if added else "was already there."))
        return {"state": self._state(), "message": "Disc key saved."}

    def set_graphics(self, part):
        g = self._cfg["graphics"]
        allowed = {"resolution": RES_OPTIONS, "fps": FPS_OPTIONS, "shadows": SHADOW_OPTIONS, "aniso": ANISO_OPTIONS}
        for k, v in (part or {}).items():
            if k in allowed:
                g[k] = _pick(v, allowed[k], g[k])
            elif k == "api" and v in ("vulkan", "opengl"):
                g[k] = v
            elif k == "sound" and v in SOUND_OPTIONS:
                g[k] = v
            elif k == "audio_api" and v in CEMU_AUDIO_APIS:
                g[k] = v
            elif k in ("fullscreen", "vsync", "show_fps", "gamepad_window"):
                g[k] = bool(v)
        self._save()
        return g

    def set_controls(self, part):
        c = self._cfg["controls"]
        for k, v in (part or {}).items():
            if k == "mode" and v in ("auto", "keep"):
                c[k] = v
            elif k in ("confirm_bottom", "rumble"):
                c[k] = bool(v)
            elif k in ("left_deadzone", "right_deadzone"):
                c[k] = round(min(0.5, max(0.0, float(v))), 3)
            elif k in ("left_range", "right_range"):
                c[k] = round(min(2.0, max(0.5, float(v))), 3)
        self._save()
        return c

    def select_device(self, key):
        dev = next((d for d in (self._devices or []) if d["key"] == key), None)
        if dev:
            self._cfg["controls"]["device"] = public_device(dev)
            self._save()
            if self._pad:
                self._pad.selected = dev
        return self._cfg["controls"]

    def pad_start(self):
        if self._busy or (self._pad and self._pad.is_alive()):
            return True
        pad = PadService(self._on_devices,
                         lambda codes: self._emit("pressed", codes=codes),
                         lambda v: self._emit("sticks", v=v),
                         lambda text: self._emit("note", text=text))
        saved = self._cfg["controls"].get("device")
        pad.selected = next((d for d in (self._devices or []) if saved and d["key"] == saved.get("key")), None)
        self._pad = pad
        pad.start()
        return True

    def pad_stop(self):
        self._pad_stop()
        return True

    def open_folder(self):
        self._root.mkdir(parents=True, exist_ok=True)
        os.startfile(str(self._root))
        return True

    def minimize(self):
        self._win.minimize()
        return True

    def close(self):
        self._pad_stop()
        self._win.destroy()
        return True


def load_ui_html() -> str:
    import base64
    html = resource_path("ui/index.html").read_text("utf-8")
    font = resource_path("ui/Cinzel.ttf")
    if font.is_file():
        html = html.replace('url("Cinzel.ttf")', 'url("data:font/ttf;base64,%s")' % base64.b64encode(font.read_bytes()).decode())
    # Optional custom art: ui/background.jpg (or .png) next to index.html at build time.
    for name, mime in (("background.jpg", "image/jpeg"), ("background.png", "image/png")):
        art = resource_path("ui/" + name)
        if art.is_file():
            uri = "data:%s;base64,%s" % (mime, base64.b64encode(art.read_bytes()).decode())
            html = html.replace("/*CUSTOM_ART*/", '.art-custom{background-image:url("%s")}' % uri)
            html = html.replace('<body class="', '<body class="has-art ')
            break
    return html


def message_box(text, title=SERVER_NAME):
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
    except Exception:
        print(text)


def run_app():
    try:
        import webview
    except ImportError:
        message_box("pywebview is missing. Run the built MH3U_Play.exe, or: pip install pywebview")
        return 1
    api = Api()
    win = webview.create_window(SERVER_NAME, html=load_ui_html(), js_api=api, width=1100, height=680,
                                resizable=False, frameless=True, easy_drag=False, shadow=True,
                                background_color="#0a0806", text_select=False)
    api._win = win
    icon = resource_path("mh3u_play.ico")
    try:
        webview.start(api._on_start, gui="edgechromium", private_mode=True,
                      debug=os.environ.get("MH3U_DEBUG") == "1",
                      icon=str(icon) if icon.is_file() else None)
    except Exception as e:
        message_box("The launcher needs Microsoft Edge WebView2, which is part of Windows 11 and "
                    "most Windows 10 PCs.\n\nInstall it from "
                    "https://go.microsoft.com/fwlink/p/?LinkId=2124703 and start the launcher again."
                    f"\n\n({e})")
        return 1
    return 0


# ============================================================================ self-test
def _mk_title(folder, tid, ver_hex):
    (folder / "code").mkdir(parents=True)
    (folder / "content").mkdir()
    (folder / "meta").mkdir()
    (folder / "code" / "app.xml").write_text(
        f'<?xml version="1.0"?><app><title_id type="hexBinary" length="8">{tid}</title_id>'
        f'<title_version type="hexBinary" length="2">{ver_hex}</title_version></app>', "utf-8")
    (folder / "meta" / "meta.xml").write_text("<menu><longname_en>MH</longname_en></menu>", "utf-8")


def selftest() -> int:
    import tempfile
    fails = 0

    def check(cond, what):
        nonlocal fails
        print(("PASS  " if cond else "FAIL  ") + what)
        fails += not cond

    check(is_newer("v0.2.10-beta", "v0.2.9-beta"), "version: 0.2.10 > 0.2.9")
    check(not is_newer("v0.2.1-beta", "v0.2.1-beta"), "version: equal is not newer")
    check(is_newer("v0.2.1-beta", "unknown"), "version: unknown local gets the update")
    check(safe_member("../x") is None and safe_member("C:/x") is None and safe_member("/x") is None,
          "zip: escaping paths rejected")
    check(safe_member("portable\\settings.xml") == "portable/settings.xml", "zip: backslashes normalised")
    check(cemu_stick_output(0.05, 0.08, 1.3) == 0.0, "stick: inside deadzone -> 0")
    check(abs(cemu_stick_output(0.5, 0.1, 1.0) - (0.5 - 0.1) / 0.9) < 1e-9, "stick: Cemu scaled radial deadzone")
    check(cemu_stick_output(0.8, 0.08, 1.3) == 1.0, "stick: sensitivity reaches full tilt sooner")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        z = td / "bundle.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("Cemu_release.exe", "new")
            zf.writestr("MH3U_Online.exe", "x")
            zf.writestr("server.exe", "x")
            zf.writestr("portable/settings.xml", "<content/>")
            zf.writestr("portable/mh3u_server.txt", "PASTE_HOST_IP_HERE\n")
            zf.writestr("../escape.txt", "x")
        root = td / "inst"
        (root / "portable").mkdir(parents=True)
        (root / "portable" / "settings.xml").write_text("mine", "utf-8")
        extract_bundle(z, root)
        check((root / "Cemu_release.exe").read_text() == "new", "bundle: Cemu extracted")
        check(not (root / "MH3U_Online.exe").exists() and not (root / "server.exe").exists(),
              "bundle: upstream launcher and server skipped")
        check((root / "portable" / "settings.xml").read_text() == "mine", "bundle: player's settings kept")
        check((root / "portable" / "mh3u_server.txt").exists(), "bundle: missing player file installed")
        check(not (td / "escape.txt").exists(), "bundle: zip-slip blocked")

        dumps = td / "Wii U Games"
        _mk_title(dumps / "MH3U [Game] [0005000010117200]", "0005000010117200", "0000")
        _mk_title(dumps / "MH3U [Update] [0005000e10117200]", "0005000E10117200", "0020")
        _mk_title(dumps / "Other [Game] [0005000010101C00]", "0005000010101C00", "0000")
        g = find_mh3u(dumps)
        check(bool(g) and g["base"]["region"] == "EU" and g["update"]["version"] == 32,
              "game: EU base + update v32 found from parent folder")
        g2 = find_mh3u(dumps / "MH3U [Game] [0005000010117200]")
        check(bool(g2) and g2["update"] is not None, "game: update found next to chosen [Game] folder")
        g3 = find_mh3u(dumps / "MH3U [Game] [0005000010117200]" / "code")
        check(bool(g3), "game: picking the code folder still works")
        other = td / "Other"
        _mk_title(other / "Zelda [Game]", "0005000010101C00", "0000")
        check(find_mh3u(other) is None, "game: a different game is refused")
        check(game_paths_for(root, g) == [str(dumps.resolve())], "game: one game path for both folders")

        sroot = td / "s"
        (sroot / "portable").mkdir(parents=True)
        (sroot / SETTINGS_REL).write_text('<?xml version="1.0" encoding="UTF-8"?>\n<content>'
                                          "<GamePaths/><GraphicPack/><Graphic><api>1</api></Graphic>"
                                          "<Account><PersistentId>2147483649</PersistentId></Account>"
                                          "</content>", "utf-8")
        gfx = dict(DEFAULT_GRAPHICS, resolution="2560x1440 (2K)", fps=FPS120_NAME, gamepad_window=True)
        for _ in range(2):
            apply_cemu_settings(sroot, [str(dumps)], gfx, {"fps": True, "gfx": True})
        c = ET.parse(sroot / SETTINGS_REL).getroot()
        check([e.text for e in c.find("GamePaths").findall("Entry")] == [str(dumps)],
              "settings: game path added once")
        entries = c.find("GraphicPack").findall("Entry")
        check(len(entries) == 2, "settings: two graphic packs, no duplicates")
        res = [p.findtext("preset") for p in entries[0].findall("Preset") if p.findtext("category") == "TV Resolution"]
        check(res == ["2560x1440 (2K)"], "settings: resolution preset")
        check(entries[1].get("filename") == FPS_PACK_KEY and entries[1].find("Preset").findtext("preset") == FPS120_NAME,
              "settings: FPS preset, no category")
        check(c.findtext("open_pad") == "true" and c.find("Account") is not None, "settings: GamePad window, rest kept")
        check((c.findtext("Audio/api"), c.findtext("Audio/TVChannels"), c.findtext("Audio/TVDevice"))
              == ("2", "1", "default"), "sound: XAudio2, stereo, default device by default")
        # The bundle's own settings: DirectSound with a device id the other APIs may not have.
        (sroot / SETTINGS_REL).write_text('<?xml version="1.0" encoding="UTF-8"?>\n<content><Audio><api>0</api>'
                                          "<delay>2</delay><TVChannels>1</TVChannels><TVVolume>50</TVVolume>"
                                          "<TVDevice>{0.0.0.00000000}.{guid}</TVDevice></Audio></content>", "utf-8")
        apply_cemu_settings(sroot, [], dict(gfx, sound="surround", audio_api="cubeb"), {})
        a = ET.parse(sroot / SETTINGS_REL).getroot().find("Audio")
        check((a.findtext("api"), a.findtext("TVChannels"), a.findtext("TVDevice"), a.findtext("TVVolume"))
              == ("3", "2", "default", "50"), "sound: Cubeb + 5.1 options; other API's device replaced, volume kept")
        cur = ET.parse(sroot / SETTINGS_REL).getroot()
        cur.find("Audio/TVDevice").text = "{my-headset}"
        write_xml(cur, sroot / SETTINGS_REL)
        apply_cemu_settings(sroot, [], dict(gfx, audio_api="cubeb"), {})
        a = ET.parse(sroot / SETTINGS_REL).getroot().find("Audio")
        check((a.findtext("TVChannels"), a.findtext("TVDevice")) == ("1", "{my-headset}"),
              "sound: a device the player picked in Cemu is kept while the audio API stays")
        apply_cemu_settings(sroot, [], gfx, {})
        a = ET.parse(sroot / SETTINGS_REL).getroot().find("Audio")
        check((a.findtext("api"), a.findtext("TVDevice")) == ("2", "default"),
              "sound: switching the audio API goes back to the default device")
        nc = load_config(td / "nocfg")["graphics"]
        check((nc["sound"], nc["audio_api"]) == ("stereo", "xaudio2"), "sound: stereo through XAudio2 by default")
        v2 = td / "v2cfg"
        (v2 / CONFIG_REL).parent.mkdir(parents=True)
        (v2 / CONFIG_REL).write_text(json.dumps({"settings_version": 2, "graphics": {"sound": "surround"}}), "utf-8")
        check(load_config(v2)["graphics"]["sound"] == "stereo", "sound: surround from the earlier default becomes stereo once")
        (v2 / CONFIG_REL).write_text(json.dumps({"settings_version": 3, "graphics": {"sound": "surround"}}), "utf-8")
        check(load_config(v2)["graphics"]["sound"] == "surround", "sound: surround chosen since then is kept")

        # GamePad window: off by default; on in configs from older launchers only by their old default.
        check(load_config(td / "nocfg")["graphics"]["gamepad_window"] is False, "GamePad window: off by default")
        oldcfg = td / "oldcfg"
        (oldcfg / CONFIG_REL).parent.mkdir(parents=True)
        (oldcfg / CONFIG_REL).write_text(json.dumps({"graphics": {"gamepad_window": True, "fps": FPS120_NAME}}), "utf-8")
        oc = load_config(oldcfg)
        check(oc["graphics"]["gamepad_window"] is False and oc["graphics"]["fps"] == FPS120_NAME,
              "GamePad window: turned off once in an older launcher's config, other settings kept")
        oc["graphics"]["gamepad_window"] = True
        save_config(oldcfg, oc)
        check(load_config(oldcfg)["graphics"]["gamepad_window"] is True,
              "GamePad window: a player who turns it back on keeps it")

        rules = td / "rules.txt"
        rules.write_text("[Definition]\nname = x\n\n[Preset]\nname = 60 FPS (normalized beta)\n", "utf-8")
        ensure_fps120(rules)
        ensure_fps120(rules)
        check(rules.read_text().count(FPS120_NAME) == 1, "fps pack: 120 preset added once")

        ctl = dict(DEFAULT_CONTROLS)
        ps = {"api": "SDLController", "uuid": "0_050000004c050000e60c000000006800", "kind": "playstation",
              "name": "DualSense Wireless Controller"}
        x = controller_profile(ps, ctl)
        maps = {int(e.findtext("mapping")): int(e.findtext("button")) for e in x.iter("entry")}
        check(x.findtext("controller/uuid") == ps["uuid"] and x.findtext("controller/api") == "SDLController",
              "controller: SDL uuid + api")
        check(maps[1] == 1 and maps[2] == 0 and maps[26] == 20 and len(maps) == 25,
              "controller: Wii U layout, touchpad switches screens")
        check(x.findtext("controller/axis/deadzone") == "0.08" and x.findtext("controller/rotation/range") == "1.3",
              "controller: player's stick deadzone + sensitivity")
        xb = controller_profile({"api": "XInput", "uuid": "0", "kind": "xbox", "name": "Xbox"},
                                dict(ctl, confirm_bottom=True))
        mx = {int(e.findtext("mapping")): int(e.findtext("button")) for e in xb.iter("entry")}
        check(mx[1] == 12 and mx[2] == 13 and mx[17] == K_AXIS_YP, "controller: XInput, confirm on A, stick up")

        up = find_update(dumps, "EU")
        check(bool(up) and up["version"] == 32, "update: found from a parent folder")
        img = td / "disc"
        img.mkdir()
        (img / "MH3U.wux").write_bytes(b"x")
        (img / "game.key").write_bytes(bytes(range(16)))
        check(find_disc_key(img / "MH3U.wux") == bytes(range(16)).hex(), "disc key: game.key read")
        kroot = td / "k"
        check(add_disc_key(kroot, bytes(range(16)).hex()) and not add_disc_key(kroot, bytes(range(16)).hex()),
              "disc key: added once")
        check(has_disc_key(kroot), "disc key: present in keys.txt")
        mine = td / "next to the exe" / "keys.txt"
        mine.parent.mkdir()
        k1, k2 = "ab" * 16, "CD" * 16
        mine.write_text(f"# my keys\n{k1} # MH3U EU disc\nnot a key\n{k2} ; other game\n{bytes(range(16)).hex()}\n",
                        "utf-8")
        kroot2 = td / "k2"
        check(import_keys_files(kroot2, [mine]) == 3 and import_keys_files(kroot2, [mine]) == 0,
              "keys.txt next to the exe: every key added once")
        ktext = (kroot2 / KEYS_REL).read_text("utf-8")
        check(k1 in ktext and k2.lower() in ktext and "MH3U EU disc" in ktext and has_disc_key(kroot2),
              "keys.txt next to the exe: keys and their notes in the client's keys.txt")
        check(import_keys_files(kroot2, [kroot2 / KEYS_REL]) == 0, "keys.txt: the client's own file is skipped")
        fgame = {"kind": "file", "path": str(img / "MH3U.wux"), "update": g["update"]}
        check(len(game_paths_for(kroot, fgame)) == 2 and "update v32" in game_label(fgame),
              "disc image + separate update folder")

        wud = td / "img" / "MH3U.wud"
        wud.parent.mkdir()
        wud.write_bytes(b"WUP-P-ABCP" + bytes(1000))
        check(disc_region(wud) == "EU", "disc image: region read from the header")

        # The game next to MH3U_Play.exe.
        near = td / "launcher folder"
        near.mkdir()
        check(find_game_near_launcher(near) is None, "game next to the launcher: nothing there, nothing found")
        (near / "backup.iso").write_bytes(b"x")
        lone = find_game_near_launcher(near)
        check(bool(lone) and lone["path"].endswith("backup.iso"), "game next to the launcher: a single game file is used")
        (near / "other game.wux").write_bytes(b"x")
        check(find_game_near_launcher(near) is None, "game next to the launcher: two unnamed files, no guessing")
        (near / "Monster Hunter 3 Ultimate (Europe).wud").write_bytes(b"WUP-P-ABCP" + bytes(1000))
        mh = find_game_near_launcher(near)
        check(bool(mh) and mh["path"].endswith("(Europe).wud") and mh["region"] == "EU",
              "game next to the launcher: the MH3U-named file wins, region read")
        dumpdir = td / "launcher with dump"
        _mk_title(dumpdir / "MH3U [Game]", "0005000010118300", "0000")
        dg = find_game_near_launcher(dumpdir)
        check(bool(dg) and dg["kind"] == "folder" and dg["base"]["region"] == "US",
              "game next to the launcher: a dumped [Game] folder")
        os.environ["MH3U_SERVER_HOST"] = "203.0.113.5"
        check(server_host() == "203.0.113.5", "server address: MH3U_SERVER_HOST is used")
        del os.environ["MH3U_SERVER_HOST"]
        hits = find_updates_anywhere([dumps], budget=5)
        check(hits.get("EU", {}).get("version") == 32, "update: found by the PC-wide search")
        roots = _update_roots([dumps])
        check(roots[:2] == [dumps, app_dir()], "update: launcher's own folder searched right after the game")
        dg2 = {"kind": "file", "path": str(dumps / "x.wux"), "region": "EU"}
        check(bool(auto_attach_update(dg2, td / "nowhere")) and dg2["update"]["region"] == "EU",
              "update: matching region attached to a disc image automatically")

        # The updates folder next to MH3U_Play.exe: checked at every start and before every game.
        drop = td / "updates"
        drop.mkdir()
        eg = find_mh3u(dumps / "MH3U [Game] [0005000010117200]")
        check(refresh_update(eg, drop) == (None, None) and eg["update"]["version"] == 32,
              "updates folder: empty folder changes nothing")
        _mk_title(drop / "MH3U [Update] JP", "0005000E10104D00", "0060")
        _mk_title(drop / "Dumpling" / "dumps" / "MH3U [Update] [0005000e10117200]", "0005000E10117200", "0020")
        check(refresh_update(eg, drop) == (None, None) and eg["update"]["path"].startswith(str(dumps)),
              "updates folder: same version keeps the update already used, other regions ignored")
        _mk_title(drop / "newer" / "MH3U [Update]", "0005000E10117200", "0021")
        _gone, used = refresh_update(eg, drop)
        check(bool(used) and used["version"] == 33 and eg["update"]["path"].startswith(str(drop)),
              "updates folder: a newer update found deep inside it is used automatically")
        check(refresh_update(eg, drop) == (None, None), "updates folder: nothing to do the second time")
        shutil.rmtree(drop / "newer")
        gone, used = refresh_update(eg, drop)
        check(bool(gone) and gone["version"] == 33 and used["version"] == 32,
              "updates folder: a deleted update is forgotten, the next one there is used")
        ng = find_mh3u(dumps / "MH3U [Game] [0005000010117200]")
        ng["update"] = None
        check(refresh_update(ng, drop)[1]["region"] == "EU", "updates folder: game without update gets it")
        wup = drop / "MH3U update install files"
        wup.mkdir()
        (wup / "title.tmd").write_bytes(b"x")
        check(updates_in_wrong_format(drop) == [wup], "updates folder: install files (title.tmd) reported")

        # The Wii U's reverb libraries, dropped anywhere in the updates folder.
        rpl = b"\x7fELF\x01\x02\x01\xca\xfe" + bytes(5000)
        (drop / "from my wiiu" / "code").mkdir(parents=True)
        (drop / "from my wiiu" / "code" / "snd_user.rpl").write_bytes(rpl)
        (drop / "SNDUSER2.RPL").write_bytes(rpl + b"2")
        (drop / "Dumpling" / "snd_user.rpl").write_bytes(b"not a library")
        libs = find_sound_libs(drop)
        check(sorted(libs) == list(SOUND_LIBS) and libs["snd_user.rpl"].parent.name == "code",
              "sound files: found at any depth, any letter case, fakes skipped")
        sroot2 = td / "client"
        check(not sound_libs_installed(sroot2), "sound files: missing before install")
        check(install_sound_libs(sroot2, libs) == list(SOUND_LIBS) and sound_libs_installed(sroot2)
              and (sroot2 / CAFELIBS_REL / "snduser2.rpl").read_bytes() == rpl + b"2",
              "sound files: copied to portable\\cafeLibs where Cemu loads them")
        check(install_sound_libs(sroot2, libs) == [], "sound files: not copied again when unchanged")

        # The patched Cemu: swapped in only for the exact client it was built for.
        fixdir = td / "soundfix"
        fixdir.mkdir()
        (fixdir / CEMU_EXE).write_bytes(b"MZ fixed client")
        orig = b"MZ original client"
        (fixdir / "soundfix.json").write_text(json.dumps({
            "sha256": hashlib.sha256(b"MZ fixed client").hexdigest(),
            "replaces": [hashlib.sha256(orig).hexdigest()]}), "utf-8")
        fx = soundfix_info(fixdir)
        croot = td / "cemu"
        croot.mkdir()
        check(soundfix_state(croot, fx) == "none" and soundfix_state(croot, None) == "none",
              "sound fix: nothing to do without a client or without the fix")
        (croot / CEMU_EXE).write_bytes(orig)
        check(soundfix_state(croot, fx) == "fixable" and apply_sound_fix(croot, fx)
              and (croot / CEMU_EXE).read_bytes() == b"MZ fixed client" and soundfix_state(croot, fx) == "fixed",
              "sound fix: the known client is replaced by the fixed one")
        check(not apply_sound_fix(croot, fx) and not (croot / (CEMU_EXE + ".soundfix.tmp")).exists(),
              "sound fix: not applied twice, no temp file left")
        (croot / CEMU_EXE).write_bytes(b"MZ a newer client")
        check(soundfix_state(croot, fx) == "other" and not apply_sound_fix(croot, fx)
              and (croot / CEMU_EXE).read_bytes() == b"MZ a newer client",
              "sound fix: any other client is left alone")
        check(soundfix_info(td / "nowhere") is None, "sound fix: missing fix files are ignored")

        txt = account_dat_text("4abc1234")
        check("\r" not in txt and "PrincipalId=4abc1234\n" in txt and "AccountId=CemuMH3U1234\n" in txt
              and ACCT_VALID_MARKER in txt, "account: format")
        aroot = td / "a"
        ensure_account(aroot, lambda s: None)
        first = (aroot / ACTDIR_REL / "account.dat").read_text()
        ensure_account(aroot, lambda s: None)
        check((aroot / ACTDIR_REL / "account.dat").read_text() == first, "account: kept once made")
    print("FAILURES:", fails)
    return fails


# ============================================================================ main
def main(argv=None):
    ap = argparse.ArgumentParser(description="MH3U Online launcher")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--detect", action="store_true", help="list controllers as Cemu will see them")
    ap.add_argument("--install", action="store_true", help="install/update the client, no window")
    ap.add_argument("--prepare", metavar="GAME_FOLDER", help="write all settings for this game, no window")
    ap.add_argument("--launch", action="store_true", help="with --prepare: also start the game")
    a = ap.parse_args(argv)
    if a.selftest:
        return 1 if selftest() else 0
    if a.detect:
        for d in detect_controllers_once():
            print(json.dumps(d))
        return 0
    if a.install or a.prepare:
        root = install_dir()
        out = lambda *x: print(*[v for v in x if v is not None])
        if a.install or not client_installed(root):
            job_install(root, print, lambda f, t=None: None)
        if a.prepare:
            cfg = load_config(root)
            game = find_mh3u(a.prepare, root)
            if not game:
                print("no MH3U found in", a.prepare)
                return 2
            cfg["game"] = game
            save_config(root, cfg)
            cmd, used = job_play(root, cfg, print, lambda f, t=None: None, launch=a.launch)
            out("controller:", json.dumps(used))
        return 0
    return run_app()


if __name__ == "__main__":
    sys.exit(main())
