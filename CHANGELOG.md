# Changelog

## [0.5.5] - 2026-11-12

* **Windows: Update now.** Next to the notice of a new version: downloads
  the new `.exe` beside the old one, checks it against `SHA256SUMS`, starts
  it and quits; the new one deletes the old file. While a backup runs it
  waits. If it fails: the reason and the link to download by hand.
* Every release carries `SHA256SUMS` for all files.

## [0.5.4] - 2026-11-12

* Windows: a *Start the iPhone service* button on the screen that says
  Apple's driver is missing; it starts the driver and looks again.
* After an update the autostart starts the new `.exe` or AppImage, not the
  old file (their names carry the version).
* README: how to update on Windows.

## [0.5.3] - 2026-11-12

* Windows: the *Apple Devices* app from the Store has no Windows service;
  its driver starts only at the next sign-in. DCIMDock now starts it itself
  right after installing, so *Check again* works without signing out.
  *Restart the iPhone service* does the same (no admin rights needed).
  If it still does not start: a note to sign out and in again.
* Diagnosis says whether the Store app is installed.

## [0.5.2] - 2026-11-12

(The tag v0.5.1 went out by mistake on the code of 0.5.0; it has no release.)

* Windows: when Apple's driver is missing, an *Open Microsoft Store* button
  goes straight to the *Apple Devices* app; the terminal prints the link.
  The German text names the app *Apple Geräte* without a hyphen, as the
  Store does, so searching for it finds it.

## [0.5.0] - 2026-11-12

* **Beta: Photos library.** Off by default (*Settings → Beta features*).
  Reads a copy of the iPhone's `Photos.sqlite`: leaves out *Recently
  Deleted* (on by default with beta), warns about photos only in iCloud, and
  adds *leave out hidden*, *only favorites* and *only from these albums* to
  *What to copy*. Unreadable library: a note, and it works as before.
* Terminal: `--beta`, `--include-deleted`, `--skip-hidden`, `--favorites`,
  `--album NAME`.
* Diagnosis shows what the library contains.

## [0.4.0] - 2026-11-12

* **Automatic backup** when an iPhone is plugged in, in the background with
  a notification at the end. Tray icon; the window closes to it. Optional
  autostart at login (`--background`; Linux `~/.config/autostart`,
  Windows the Run key of the user).
* **Name files by capture time** (optional):
  `2026-11-03_14-22-05_IMG_0001.HEIC`, the same prefix for a whole group.
* **JPEG next to HEIC** (optional): `IMG_0001.jpg` beside the untouched
  original, EXIF kept, orientation fixed. pillow-heif in the AppImage and
  the `.exe`, `heif-dec` (libheif-tools) for the RPM.
* Settings dialog (*More → Settings*).
* Notice when a new release is out (GitHub, at most once a day, can be
  switched off).

## [0.3.0] - 2026-11-12

* **Choose what to copy:** a period (last 7/30/90 days, this year, last
  year, from … to …) by capture date or file date; photos, videos and
  screenshots each on or off; with or without Live Photo videos and edits
  (`IMG_E…`, `.AAE`). Decided per group, so a Live Photo stays together.
  The window shows how many files are not selected, and the report at the
  end how many are not in the backup yet.
* *Copy everything again* takes the selection into account and names the
  new folder after it.
* Terminal mode: `--period`, `--from`, `--to`, `--only`, `--no-live`,
  `--no-edits`.
* Paths in the window use the system's separator (`\` on Windows).

## [0.2.0] - 2026-11-12

* **Windows.** `DCIMDock-0.2.0-windows-x64.exe`, one file without installer.
  It reads the photos directly over AFC with pymobiledevice3 (no mounting)
  and needs Apple's driver from the "Apple Devices" app or iTunes. Same
  window, same rules: only new files, never overwrite, `.part` files,
  SHA-256, nothing on the iPhone is changed.
* Status beta: tested with a real iPhone on Linux.
* The index file is named after the same UDID on Linux and Windows, so a
  backup drive can move between both.
* Linux is unchanged (ifuse). `DCIMDOCK_BACKEND=afc` tries the Windows way
  on Linux.

## [0.1.1] - 2026-11-11

First release. (The v0.1.0 tag was never released: its AppImage crashed on
exit with PySide 6.12.)

* Detects the iPhone, guides through Trust and passcode, mounts it read-only.
* Copies only new files, never overwrites, `.part` files until a file is
  complete, synced and size-checked; SHA-256 in the index.
* Live Photo, edited version and `.AAE` stay together.
* Folders by year/month, year/month/day, month, year, like on the iPhone or
  all in one; optional folder per iPhone; optional photos and videos apart.
* Folders by the capture date from EXIF (JPEG, HEIC, PNG, DNG) or the movie
  header (MOV, MP4), switchable to the file date.
* Screenshots into their own folder, recognised by the mark iOS writes.
* A list to pick the iPhone when several are connected.
* Copy everything again into a new folder; check the backup against the
  checksums.
* Troubleshooting: release stuck ifuse mounts (also automatically on start),
  pair again, restart usbmuxd, diagnosis text. Detects the empty pseudo
  folder of a locked iPhone.
* Free space check, progress bar with speed and time left, optional preview.
* "Before you start" page (iCloud, HEIC vs JPEG, iPhone settings) with
  "Don't show this again".
* Terminal mode `dcimdock --cli`, `dcimdock --verify`.
* AppImage, RPM, `install.sh` for Fedora, Debian/Ubuntu, Arch and openSUSE.
