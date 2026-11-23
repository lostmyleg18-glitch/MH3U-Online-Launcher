# Build MH3U_Play.exe

| File | What |
| --- | --- |
| `launcher/mh3u_play.py` | the launcher |
| `launcher/ui/index.html` | its interface |
| `launcher/build.ps1` | builds `MH3U_Play.exe` |
| `launcher/make_icon.py` | draws the icon (`mh3u_play.ico`) |
| `launcher/SDL3.dll` | SDL 3.4.10, for controllers (zlib license) |
| `launcher/server.txt.example` | template for `launcher/server.txt`, your server's address |
| `launcher/cemu_soundfix/` | the game client with the sound fix, built into `MH3U_Play.exe` (Cemu, MPL-2.0; its README says how it was built) |

## Steps

1. Install 64-bit Python 3.11 or newer from <https://www.python.org> and tick
   "Add python.exe to PATH" in the installer.
2. Copy `launcher/server.txt.example` to `launcher/server.txt` and put your server's public
   IPv4 address or DNS name on its last line. This file is never uploaded (`.gitignore`).
3. Open a terminal in this folder and run:

   ```powershell
   python -m pip install pyinstaller pywebview
   powershell -ExecutionPolicy Bypass -File launcher\build.ps1
   ```

4. The new launcher is `dist\MH3U_Play.exe`.

The build runs the launcher's self-test first. The released `MH3U_Play.exe` was built with
Python 3.13.16, PyInstaller 6.22.3 and pywebview 6.2.1.

## Try it without building

```powershell
python launcher\mh3u_play.py              # opens the launcher (reads launcher\server.txt)
python launcher\mh3u_play.py --selftest   # runs the checks
```

`MH3U_SERVER_HOST` overrides the server address, for example for testing.

## Your own background art

Put `background.jpg` (or `background.png`) into `launcher/ui/` and rebuild. Use only art you
have the rights to.
