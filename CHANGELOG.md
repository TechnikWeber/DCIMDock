# Changelog

## [0.1.0] - 2026-11-11

First release.

* Detects the iPhone, guides through Trust and passcode, mounts it read-only.
* Copies only new files, never overwrites, `.part` files until a file is
  complete, synced and size-checked; SHA-256 in the index.
* Live Photo, edited version and `.AAE` stay together.
* Folders by year/month, year/month/day, month, year, like on the iPhone or
  all in one; optional folder per iPhone; optional photos and videos apart.
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
