# Host an MH3U Online server

`MH3U_Server_Setup.bat` sets up the [MH3U Revival](https://github.com/Matt-Wood-23/mh3u-revival)
server on a Windows VPS in one go. 4 CPU cores and 8 GB of RAM are plenty: the server mostly
uses one core, and even 48 full hunts need only a few Mbit/s.

## Set it up

1. Connect to the VPS with Remote Desktop.
2. Copy `MH3U_Server_Setup.bat` onto the VPS desktop.
3. Double-click it, click **Yes** when Windows asks for administrator rights, then press Enter.
   The first time, it asks for the VPS's public IPv4 address (what players' games connect to).
   You can also put it into `$PublicIP` at the top of the file.

   It downloads the newest MH3U Revival server into `C:\MH3U-Server`, opens the Windows
   Firewall and runs the server in the background. The server starts with Windows and
   restarts itself if it ever crashes.
4. If your VPS provider has its own firewall in its web panel, open these UDP ports there too
   (inbound, from anywhere): `1223-1224`, `10025`, `27100-27387`.
5. Build the launcher with your server's address in `launcher/server.txt` (see
   [BUILDING.md](../BUILDING.md)) and give your players that `MH3U_Play.exe`.

## Later

- **Update the server:** run `MH3U_Server_Setup.bat` again. Your settings are kept.
- **Status or uninstall:** run it and choose 2 or 3.
- **Dashboard** (who is online, announcements, restarts once no hunts are running): the
  "MH3U Server dashboard" shortcut on the VPS desktop. It only opens on the VPS itself.
- **Settings:** `C:\MH3U-Server\server-settings.txt`. Run the setup again after changing them.
- **Gathering halls:** by default there are 15, the server's maximum: Low Rank 1-5,
  High Rank 1-5 and G Rank 1-5, with room for 32 hunters each. Each hall lists only the rooms
  made in it. Change `MH3U_HALL_NAMES` (comma-separated) and `MH3U_HALL_MAX` in the settings.
  A hunt itself stays at 4 players, the game's own limit.
- **Players at once:** 128 (`MH3U_MAX_CONNECTIONS`), 48 hunts at once.
- The setup installs the newest server release, test releases included (v0.3.0-beta is the
  first with several halls and the dashboard). To stay on stable releases only, set
  `$Prerelease = $false` at the top of the file.
