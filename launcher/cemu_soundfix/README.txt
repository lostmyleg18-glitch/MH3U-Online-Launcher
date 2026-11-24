THE GAME CLIENT WITH THE SOUND FIX
==================================

MH3U Revival's game client is Cemu, built from the mh3u-revival branch of
https://github.com/Matt-Wood-23/Cemu. It has two Cemu bugs that MH3U's sound
effects run into:

  1. Hollow effects (snd_user-aux-effect-stub-fix.patch)
     Cemu only has a stand-in for the Wii U's reverb (snd_user AXFX effects).
     That stand-in is meant to silence the reverb, but its loop clears only the
     first channel. On the other channels every effect sound is played a second
     time, one audio frame (3 ms) later: footsteps, ambience and most other
     effects sound hollow, as if through a tube.

  2. Crackling stomps and monster sounds (voice-lowpass-filter-fix.patch)
     The low-pass filter a game can put on each sound (snd_core, AX voice LPF)
     subtracted its feedback term instead of adding it, which turns the low-pass
     into a treble boost, and it saved its state with the wrong scale, so the
     filter started over every 3 ms audio frame. Low-passed sounds, like MH3U's
     stomps and monster sounds, got a soft crackle repeating every 3 ms.
     The fixed filter is y = a0*x + b0*y1 (Q15, output clamped to 16 bit), as
     Dolphin implements Nintendo's AX DSP, with its state carried between frames.

MH3U_Play.exe carries the same Cemu built with both fixes and puts it in place of
exactly the client it was built for, or an earlier build of this fix (checked by
SHA-256, see soundfix.json). A different client, for example a newer MH3U Revival
release, is left alone.


FILES
-----
  Cemu_release.exe                       the fixed game client
  soundfix.json                          its SHA-256 and the SHA-256s of the clients it replaces
  snd_user-aux-effect-stub-fix.patch     fix 1 (src/Cafe/OS/libs/snd_user/snd_user.cpp)
  voice-lowpass-filter-fix.patch         fix 2 (src/Cafe/OS/libs/snd_core/ax_mix.cpp)


HOW IT WAS BUILT
----------------
Source: https://github.com/Matt-Wood-23/Cemu, commit 3163f35 on the
mh3u-revival branch ("MH3U: redirect NAT-check (nncs*) lookups to the revival
server"). The Cemu_release.exe in MH3U Revival v0.2.1-beta and v0.3.0-beta
matches that commit: it has every change up to it and none after it.

  git clone --branch mh3u-revival https://github.com/Matt-Wood-23/Cemu.git C:\Cemu-mh3u-build
  cd C:\Cemu-mh3u-build
  git checkout 3163f35
  git submodule update --init --recursive
  git apply <this folder>\snd_user-aux-effect-stub-fix.patch
  git apply <this folder>\voice-lowpass-filter-fix.patch

Then, in a "x64 Native Tools Command Prompt" of Visual Studio 2022 or newer
(with the "C++ CMake tools for Windows" component):

  cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=release -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DVCPKG_INSTALL_OPTIONS=--clean-after-build
  cmake --build build

The result is bin\Cemu_release.exe. The first build takes long: vcpkg compiles
all of Cemu's libraries first. Put the new exe here, update soundfix.json
("sha256" = the new exe; add the old "sha256" to "replaces", so launchers
upgrade an earlier fixed client too) and build the launcher again.


LICENSES
--------
Cemu is licensed under the Mozilla Public License 2.0, and this folder is the
source of the changed files (the patches, on top of the public commit above).
The libraries built into Cemu_release.exe and their licenses are listed in
THIRD-PARTY-NOTICES.txt next to MH3U_Play.exe.
