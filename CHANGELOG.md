# Changelog

## [0.1.0] - 2026-11-11

First release.

* Detects the iPhone, guides through Trust and passcode, mounts it read-only.
* Copies only new files, never overwrites, `.part` files until a file is
  complete, synced and size-checked; SHA-256 in the index.
* Live Photo, edited version and `.AAE` stay together.
* Sort by date or like on the iPhone, optional folder per iPhone.
* Free space check, progress bar with speed and time left, optional preview.
* "Before you start" page (iCloud, HEIC vs JPEG, iPhone settings) with
  "Don't show this again".
* Terminal mode `dcimdock --cli`.
* AppImage, RPM, `install.sh` for Fedora, Debian/Ubuntu, Arch and openSUSE.
