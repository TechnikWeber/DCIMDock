"""Tiny translation table: English is the key, German follows the system locale.

Set DCIMDOCK_LANG=en or =de to override.
"""
from __future__ import annotations

import locale
import os
import time

DE = {
    # device states
    "Connect your iPhone with a USB cable.": "Schließe dein iPhone per USB-Kabel an.",
    "Connecting…": "Verbinde …",
    "Unlock your iPhone.": "Entsperre dein iPhone.",
    "Unlock your iPhone and tap “Trust”, then enter your passcode.":
        "Entsperre dein iPhone und tippe auf „Vertrauen“, dann den Code eingeben.",
    "You tapped “Don’t Trust”. Unplug the iPhone and plug it in again.":
        "Du hast „Nicht vertrauen“ gewählt. Zieh das iPhone ab und steck es wieder an.",
    "The iPhone does not answer: {msg}": "Das iPhone antwortet nicht: {msg}",
    "Could not open the photos: {msg}": "Die Fotos lassen sich nicht öffnen: {msg}",
    "Reading the photo list…": "Lese die Fotoliste …",
    "Reading the photo list… {n} files": "Lese die Fotoliste … {n} Dateien",
    "Folder": "Ordner",
    "Missing programs: {tools}.\nInstall them with:\n\n{cmd}":
        "Es fehlen Programme: {tools}.\nInstallieren mit:\n\n{cmd}",
    "Check again": "Erneut prüfen",
    # options
    "Save to": "Speichern in",
    "Change…": "Ändern …",
    "Choose the backup folder": "Sicherungsordner wählen",
    "Sort": "Sortieren",
    "By date (2026/2026-11)": "Nach Datum (2026/2026-11)",
    "Like on the iPhone (100APPLE …)": "Wie auf dem iPhone (100APPLE …)",
    "Own folder per iPhone": "Eigener Ordner pro iPhone",
    "Preview": "Vorschau",
    # summary
    "{n} new files ({size}) · {k} already saved": "{n} neue Dateien ({size}) · {k} schon gesichert",
    "Everything is saved ({k} files).": "Alles ist gesichert ({k} Dateien).",
    "No photos on the iPhone.": "Keine Fotos auf dem iPhone.",
    "Only {free} free in the backup folder, {need} needed.":
        "Im Sicherungsordner sind nur {free} frei, gebraucht werden {need}.",
    # copying
    "File {i} of {n} · {name}": "Datei {i} von {n} · {name}",
    "{speed}/s · {left} left": "{speed}/s · noch {left}",
    "Preparing…": "Vorbereiten …",
    "Stopping…": "Halte an …",
    "Back up": "Sichern",
    "Ready.": "Bereit.",
    "Backing up – keep the iPhone connected and unlocked.":
        "Sicherung läuft – iPhone angeschlossen und entsperrt lassen.",
    "Stop": "Anhalten",
    "Open folder": "Ordner öffnen",
    "Before you start": "Bevor du anfängst",
    "Video": "Video",
    # results
    "Backup finished": "Sicherung fertig",
    "Backup stopped": "Sicherung angehalten",
    "{n} files saved ({size}) in {time}.": "{n} Dateien gesichert ({size}) in {time}.",
    "Stopped after {n} files. Next time it continues where it stopped.":
        "Nach {n} Dateien angehalten. Beim nächsten Mal geht es dort weiter.",
    "{n} files could not be read:": "{n} Dateien ließen sich nicht lesen:",
    "From this iPhone, {k} files taken between {a} and {b} are safe on this computer.":
        "Von diesem iPhone sind {k} Dateien aus der Zeit vom {a} bis {b} sicher auf diesem Computer.",
    "DCIMDock does not delete anything on the iPhone. To free up space, delete the photos in the Photos app and empty “Recently Deleted”. With iCloud Photos turned on, this deletes them from iCloud and all your devices too.":
        "DCIMDock löscht nichts auf dem iPhone. Um Platz zu schaffen, lösche die Fotos in der Fotos-App und leere „Zuletzt gelöscht“. Mit eingeschalteten iCloud-Fotos verschwinden sie dabei auch aus der iCloud und von allen deinen Geräten.",
    "The iPhone was unplugged during the backup.": "Das iPhone wurde während der Sicherung abgezogen.",
    "A backup is running. Stop it and quit?": "Eine Sicherung läuft. Anhalten und beenden?",
    "Stop and quit": "Anhalten und beenden",
    "Cancel": "Abbrechen",
    "OK": "OK",
    # intro dialog
    "Don’t show this again": "Nicht mehr anzeigen",
    "INTRO_HTML": None,  # filled below
}

INTRO_EN = """
<h3>Before you start</h3>
<p>DCIMDock copies the photos and videos from your iPhone's camera roll to this
computer. It only reads: nothing on the iPhone is changed or deleted.</p>

<h4>1. Connect and trust</h4>
<p>Plug in the iPhone with a cable and unlock it. The first time, tap
<b>Trust</b> and enter your passcode. Keep the iPhone unlocked or on power
while it copies, so it does not go to sleep halfway.</p>

<h4>2. iCloud Photos: get the originals onto the iPhone first</h4>
<p>If iCloud Photos is on with <b>Optimize iPhone Storage</b>, many originals
live only in iCloud and the iPhone keeps a small preview. DCIMDock can only
copy what is really on the iPhone. For a complete backup:
<i>Settings → [your name] → iCloud → Photos → Download and Keep Originals</i>,
wait until the Photos app has finished downloading, then back up.</p>
<p>Deleting a photo on the iPhone with iCloud Photos turned on deletes it in
iCloud and on all your other devices, too.</p>

<h4>3. HEIC or JPEG?</h4>
<p><i>Settings → Camera → Formats</i>. <b>High Efficiency</b> (HEIC photos,
HEVC videos) is the better choice: half the size of JPEG at the same or
better quality, 10-bit color and HDR, and Live Photos and portrait depth
stay complete. Linux opens HEIC almost everywhere today (KDE, GNOME, GIMP,
darktable). Pick <b>Most Compatible</b> (JPEG/H.264) only if old programs or
devices must open the files.</p>

<h4>4. “Transfer to Mac or PC”</h4>
<p><i>Settings → Apps → Photos</i>. This only matters for the camera import
(PTP) other programs use. DCIMDock always gets the original files, so
<b>Keep Originals</b> and <b>Automatic</b> both work. Keep Originals does no
harm.</p>

<h4>5. Deleting on the iPhone</h4>
<p>DCIMDock tells you up to which date everything is safe. Delete in the
Photos app, then empty <i>Recently Deleted</i>. Deleting the files directly
over USB would leave grey ghost pictures in the Photos app, so DCIMDock does
not offer it.</p>
"""

INTRO_DE = """
<h3>Bevor du anfängst</h3>
<p>DCIMDock kopiert die Fotos und Videos aus der Mediathek deines iPhones auf
diesen Computer. Es liest nur: Auf dem iPhone wird nichts verändert oder
gelöscht.</p>

<h4>1. Anschließen und vertrauen</h4>
<p>iPhone per Kabel anschließen und entsperren. Beim ersten Mal auf
<b>Vertrauen</b> tippen und den Code eingeben. Während der Übertragung das
iPhone entsperrt lassen oder ans Ladegerät hängen, damit es nicht mittendrin
in den Ruhezustand geht.</p>

<h4>2. iCloud-Fotos: zuerst die Originale aufs iPhone holen</h4>
<p>Ist iCloud-Fotos mit <b>iPhone-Speicher optimieren</b> eingeschaltet,
liegen viele Originale nur in der iCloud, das iPhone hat nur eine kleine
Vorschau. DCIMDock kann nur kopieren, was wirklich auf dem iPhone liegt. Für
eine vollständige Sicherung:
<i>Einstellungen → [dein Name] → iCloud → Fotos → Laden und Originale
behalten</i>, warten, bis die Fotos-App alles geladen hat, dann sichern.</p>
<p>Wer mit eingeschalteten iCloud-Fotos ein Foto auf dem iPhone löscht,
löscht es auch in der iCloud und auf allen anderen Geräten.</p>

<h4>3. HEIC oder JPEG?</h4>
<p><i>Einstellungen → Kamera → Formate</i>. <b>High Efficiency</b>
(HEIC-Fotos, HEVC-Videos) ist die bessere Wahl: halb so groß wie JPEG bei
gleicher oder besserer Qualität, 10 Bit Farbtiefe und HDR, Live Photos und
Porträt-Tiefendaten bleiben vollständig. Linux öffnet HEIC heute fast überall
(KDE, GNOME, GIMP, darktable). <b>Maximale Kompatibilität</b> (JPEG/H.264)
nur wählen, wenn alte Programme oder Geräte die Dateien öffnen müssen.</p>

<h4>4. „Auf Mac oder PC übertragen“</h4>
<p><i>Einstellungen → Apps → Fotos</i>. Das betrifft nur den Kamera-Import
(PTP), den andere Programme nutzen. DCIMDock bekommt immer die
Originaldateien, <b>Originale behalten</b> und <b>Automatisch</b>
funktionieren beide. Originale behalten schadet nicht.</p>

<h4>5. Löschen auf dem iPhone</h4>
<p>DCIMDock sagt dir, bis zu welchem Datum alles sicher ist. Lösche dann in
der Fotos-App und leere anschließend <i>Zuletzt gelöscht</i>. Die Dateien
direkt über USB zu löschen hinterlässt graue Geisterbilder in der Fotos-App,
deshalb bietet DCIMDock das nicht an.</p>
"""


def _pick() -> str:
    forced = os.environ.get("DCIMDOCK_LANG", "").lower()
    if forced in ("de", "en"):
        return forced
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        val = os.environ.get(var)
        if val:
            return "de" if val.lower().startswith("de") else "en"
    lang = (locale.getlocale()[0] or "").lower()
    return "de" if lang.startswith("de") else "en"


LANG = _pick()


def tr(text: str, **kw) -> str:
    if text == "INTRO_HTML":
        return INTRO_DE if LANG == "de" else INTRO_EN
    out = (DE.get(text) or text) if LANG == "de" else text
    return out.format(**kw) if kw else out


def num(n: int) -> str:
    s = f"{n:,}"
    return s.replace(",", ".") if LANG == "de" else s


def size(b: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1000 or unit == "TB":
            text = f"{b:.0f} {unit}" if unit in ("B", "KB") else f"{b:.1f} {unit}"
            return text.replace(".", ",") if LANG == "de" else text
        b /= 1000
    return ""


def duration(s: float) -> str:
    s = int(max(0, s))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    return f"{s // 3600} h {s % 3600 // 60:02d} min"


def date(t: float) -> str:
    lt = time.localtime(t)
    return time.strftime("%d.%m.%Y" if LANG == "de" else "%Y-%m-%d", lt)
