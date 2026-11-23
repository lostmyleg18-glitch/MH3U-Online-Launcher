# MH3U-Online-Launcher

MH3U-Online-Launcher and Server to play with other players over the Internet again.

A one-click launcher for the **MH3U Online** server: Monster Hunter 3 Ultimate online on your
PC, through [MH3U Revival](https://github.com/Matt-Wood-23/mh3u-revival) and Cemu. You never
have to open or set up Cemu yourself.

No game files are included. Bring your own copy of the game.

## Play

1. **Download `MH3U_Play.exe`** from the [latest release](../../releases/latest) and put it in a
   folder of its own, for example `MH3U Online`.
2. **Put your game in the same folder:** your own dump of Monster Hunter 3 Ultimate, US or EU
   (JP works too), as `.wua`, `.wux`, `.wud` or `.iso`. A dumped `[Game]` folder works too.
3. **Disc image (`.wux`, `.wud`, `.iso`)?** Put the `keys.txt` with your disc key, the one you use
   for Cemu, in the same folder. The launcher adds the key by itself. A `game.key` from Dumpling
   next to the image works as well. A `.wua` needs no key.
4. **Add the game update** (v32 for US and EU, v96 for JP). Dump it from your own Wii U with
   [Dumpling](https://github.com/emiyl/dumpling) ("Dump game update") and put the `[Update]`
   folder into the `updates` folder next to `MH3U_Play.exe`. If there's no `updates` folder yet,
   create one (the launcher also makes it the first time it starts). A `.wua` that already
   contains the update needs nothing else.
5. **Start `MH3U_Play.exe` and press START GAME.** The first start downloads the game client
   (about 60 MB). Windows may warn because the launcher isn't code-signed: click
   **More info**, then **Run anyway**.

Your folder then looks like this:

```
MH3U Online\
├── MH3U_Play.exe
├── keys.txt                                  (disc images only)
├── Monster Hunter 3 Ultimate (USA).wux
└── updates\
    └── MH3U [Update] [0005000e10118300]\     (code, content, meta)
```

The launcher checks the folder every time it starts and before every game, and always uses
the newest update it finds there. **Game Files** in the launcher shows what it found.

### Good to know

- **Controllers:** every Xbox and PlayStation controller works, over USB or Bluetooth.
  **Controls** sets each stick's deadzone and sensitivity.
- **GamePad screen** (map, items, chat): off by default. Turn it on under **Graphics**; it opens
  in a second window that you touch with your mouse. On PlayStation controllers the touchpad
  swaps the screens.
- **Graphics:** up to 4K, 60 FPS by default, 120 FPS experimental.
- **Sound:** stereo through XAudio2 by default; **Graphics** has 5.1 surround and Cubeb.
  The launcher installs a fixed game client, so footsteps and ambience no longer sound hollow.
  For the game's real reverb, copy `snd_user.rpl` and `snduser2.rpl` from your own Wii U
  (`storage_slc/sys/title/00050010/1000400a/code`, for example with the FTPiiU plugin) into the
  `updates` folder. Only copy them: never delete or rename anything in that folder on the console.
- **Saves:** in the game client's folder (folder button, bottom right), `portable\mlc01\usr\save`.

## Host your own server

[`server/`](server) has a one-click setup for a Windows VPS: it installs the MH3U Revival
server, opens the firewall, runs it in the background and sets up 15 gathering halls.
See [server/README.md](server/README.md).

## Build the launcher

See [BUILDING.md](BUILDING.md). The server address isn't in the code: it goes into
`launcher/server.txt`, which is built into `MH3U_Play.exe`.

## Credits and licenses

- The launcher is free software under the GNU Affero General Public License 3.0 or later
  ([LICENSE](LICENSE)).
- It builds on [MH3U Revival](https://github.com/Matt-Wood-23/mh3u-revival) (AGPL-3.0), which
  provides the server and the patched Cemu.
- `MH3U_Play.exe` carries a build of that Cemu (Mozilla Public License 2.0) with a fix for
  hollow-sounding effects: [launcher/cemu_soundfix](launcher/cemu_soundfix).
- [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt) lists every part inside `MH3U_Play.exe`
  and its license.

Monster Hunter is a trademark of Capcom; Wii U is a trademark of Nintendo. This is a fan
project, not affiliated with or endorsed by Capcom or Nintendo.
