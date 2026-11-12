# Changelog

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
