"""Tiny translation table: English is the key, German follows the system locale.

Set DCIMDOCK_LANG=en or =de to override.
"""
from __future__ import annotations

import locale
import os
import sys
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
    "1 new file ({size}) · {k} already saved": "1 neue Datei ({size}) · {k} schon gesichert",
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
    # 0.2.0 – folders, full copy, check, troubleshooting
    "Folders": "Ordner",
    "Year / month (2026/2026-11)": "Jahr / Monat (2026/2026-11)",
    "Year / month / day (2026/2026-11/2026-11-03)": "Jahr / Monat / Tag (2026/2026-11/2026-11-03)",
    "Month (2026-11)": "Monat (2026-11)",
    "Year (2026)": "Jahr (2026)",
    "All in one folder": "Alles in einen Ordner",
    "Photos and videos apart": "Fotos und Videos trennen",
    "Photos": "Fotos",
    "Videos": "Videos",
    "Example": "Beispiel",
    "More": "Mehr",
    "Copy everything again (new folder)…": "Alles neu kopieren (neuer Ordner) …",
    "Copy everything again": "Alles neu kopieren",
    "Copy everything": "Alles kopieren",
    "Full copy": "Komplettkopie",
    "(without “Recently Deleted”)": "(ohne „Zuletzt gelöscht“)",
    "Beta features": "Beta-Funktionen",
    "Leaves out “Recently Deleted”, warns about photos that are only in iCloud, and adds hidden photos, favorites and albums to “What to copy”. Still new: if the library cannot be read, DCIMDock works as without it.": "Lässt „Zuletzt gelöscht“ weg, warnt vor Fotos, die nur in iCloud liegen, und ergänzt „Was kopiert wird“ um ausgeblendete Fotos, Favoriten und Alben. Noch neu: Ist die Mediathek nicht lesbar, arbeitet DCIMDock wie ohne.",
    "Only from these albums (none ticked: any):": "Nur aus diesen Alben (keins angehakt: alle):",
    "Photos library (beta)": "Fotos-Mediathek (Beta)",
    "Photos library not readable, working without it: {msg}": "Fotos-Mediathek nicht lesbar, es geht ohne weiter: {msg}",
    "Read the iPhone's Photos library": "Fotos-Mediathek des iPhones lesen",
    "Your albums appear here once an iPhone is connected.": "Deine Alben erscheinen hier, sobald ein iPhone verbunden ist.",
    "albums: {names}": "Alben: {names}",
    "only favorites": "nur Favoriten",
    "without hidden": "ohne ausgeblendete",
    "{n} photos and videos are only in iCloud and cannot be backed up. On the iPhone: Settings → Photos → “Download and Keep Originals”.": "{n} Fotos und Videos liegen nur in iCloud und lassen sich nicht sichern. Auf dem iPhone: Einstellungen → Fotos → „Laden und Originale behalten“.",
    "Leave out “Recently Deleted”": "„Zuletzt gelöscht“ weglassen",
    "Leave out hidden photos": "Ausgeblendete Fotos weglassen",
    "Only favorites": "Nur Favoriten",
    "2026-11-03_14-22-05_IMG_0001.HEIC instead of IMG_0001.HEIC: every program sorts them by time, and a new IMG_0001 never meets an old one.": "2026-11-03_14-22-05_IMG_0001.HEIC statt IMG_0001.HEIC: Jedes Programm sortiert sie nach Zeit, und ein neues IMG_0001 trifft nie auf ein altes.",
    "Also save a JPEG next to every HEIC photo": "Zu jedem HEIC-Foto zusätzlich ein JPEG speichern",
    "Automatic": "Automatisch",
    "Back up automatically when an iPhone is plugged in": "Automatisch sichern, sobald ein iPhone angesteckt wird",
    "Backing up {n} files…": "Sichere {n} Dateien …",
    "Check for new versions (once a day, asks GitHub)": "Nach neuen Versionen suchen (einmal am Tag, fragt GitHub)",
    "Could not change the autostart: {msg}": "Der Autostart ließ sich nicht ändern: {msg}",
    "DCIMDock keeps running here and backs up the iPhone when it is plugged in. Quit from this icon's menu.": "DCIMDock läuft hier weiter und sichert das iPhone, sobald es angesteckt wird. Beenden über das Menü dieses Symbols.",
    "Example: 2026-11-03_14-22-05_IMG_0001.HEIC": "Beispiel: 2026-11-03_14-22-05_IMG_0001.HEIC",
    "Files": "Dateien",
    "IMG_0001.HEIC stays as it is, IMG_0001.jpg is added for programs that cannot open HEIC.": "IMG_0001.HEIC bleibt, wie es ist; IMG_0001.jpg kommt dazu, für Programme, die kein HEIC öffnen.",
    "Name files by the time they were taken": "Dateien nach Aufnahmezeit benennen",
    "Needs a HEIC converter: {cmd}": "Braucht einen HEIC-Umwandler: {cmd}",
    "Not enough free space in the backup folder.": "Im Sicherungsordner ist nicht genug Platz frei.",
    "Open DCIMDock": "DCIMDock öffnen",
    "Other": "Sonstiges",
    "Quit": "Beenden",
    "Settings": "Einstellungen",
    "Settings…": "Einstellungen …",
    "Start in the background when I log in": "Bei der Anmeldung im Hintergrund starten",
    "This desktop shows no tray icons: DCIMDock then only works while its window is open.": "Diese Arbeitsfläche zeigt keine Symbole neben der Uhr: DCIMDock arbeitet dann nur bei offenem Fenster.",
    "Uses the folder, the folders and the selection set in the window. Closing the window keeps DCIMDock running next to the clock.": "Nutzt Zielordner, Ordnerschema und Auswahl aus dem Fenster. Schließen des Fensters lässt DCIMDock neben der Uhr weiterlaufen.",
    "Version {v} is available": "Version {v} ist da",
    "{n} JPEG copies failed (the HEIC files are saved):": "{n} JPEG-Kopien schlugen fehl (die HEIC-Dateien sind gesichert):",
    "{n} JPEG copies made.": "{n} JPEG-Kopien erstellt.",
    "{n} with problems – open DCIMDock for details.": "{n} mit Problemen – Details in DCIMDock.",
    "Any date": "Jedes Datum",
    "Last 7 days": "Letzte 7 Tage",
    "Last 30 days": "Letzte 30 Tage",
    "Last 90 days": "Letzte 90 Tage",
    "This year": "Dieses Jahr",
    "Last year": "Letztes Jahr",
    "From … to …": "Von … bis …",
    "Everything": "Alles",
    "only {what}": "nur {what}",
    "without Live Photo videos": "ohne Live-Photo-Videos",
    "without edits": "ohne Bearbeitungen",
    "to": "bis",
    "What to copy": "Was kopiert wird",
    "Date": "Datum",
    "Period": "Zeitraum",
    "From": "Von",
    "Uses the date the photo was taken (EXIF), else the file date.": "Zählt das Aufnahmedatum (EXIF), sonst das Dateidatum.",
    "Uses the file date (“Sort by the date the photo was taken” is off).": "Zählt das Dateidatum („Nach Aufnahmedatum sortieren“ ist aus).",
    "Kinds": "Arten",
    "Pictures from the camera and saved pictures.": "Bilder der Kamera und gespeicherte Bilder.",
    "Videos of their own. The short video of a Live Photo is set below.": "Eigenständige Videos. Das kurze Video eines Live Photos steht weiter unten.",
    "Recognised by the “Screenshot” mark iOS writes into them.": "Erkannt an der Markierung „Screenshot“, die iOS hineinschreibt.",
    "Live Photo videos (.MOV next to the photo)": "Live-Photo-Videos (.MOV neben dem Foto)",
    "Off: only the still image of a Live Photo.": "Aus: nur das Standbild eines Live Photos.",
    "Edits (IMG_E… and .AAE files)": "Bearbeitungen (IMG_E… und .AAE-Dateien)",
    "The edited version and the file with the edit steps. The original is always copied.": "Die bearbeitete Fassung und die Datei mit den Bearbeitungsschritten. Das Original wird immer kopiert.",
    "Files that are already saved are never copied again. What is left out stays on the iPhone and can be copied later.": "Bereits gesicherte Dateien werden nie erneut kopiert. Was weggelassen wird, bleibt auf dem iPhone und lässt sich später kopieren.",
    "Copy": "Kopieren",
    "Choose…": "Auswählen …",
    "Only a period, only photos or videos, without Live Photo videos or edits.": "Nur ein Zeitraum, nur Fotos oder Videos, ohne Live-Photo-Videos oder Bearbeitungen.",
    "{n} not selected": "{n} nicht ausgewählt",
    "{n} files on the iPhone are not in this backup (not selected or not readable).": "{n} Dateien auf dem iPhone sind nicht in dieser Sicherung (nicht ausgewählt oder nicht lesbar).",
    "Selection": "Auswahl",
    "Nothing new in the selection · {k} already saved": "Nichts Neues in der Auswahl · {k} schon gesichert",
    "Selection: {what}": "Auswahl: {what}",
    "Uses the selection, if one is set.": "Berücksichtigt die Auswahl, falls eine gesetzt ist.",
    "Copies all {n} files ({size}) from the iPhone into a new folder, without comparing with earlier backups:\n\n{folder}\n\nThe normal backup is not touched.":
        "Kopiert alle {n} Dateien ({size}) vom iPhone in einen neuen Ordner, ohne Abgleich mit früheren Sicherungen:\n\n{folder}\n\nDie normale Sicherung bleibt unberührt.",
    "Check the backup…": "Sicherung prüfen …",
    "Check the backup": "Sicherung prüfen",
    "There is no backup in {folder} yet.": "In {folder} gibt es noch keine Sicherung.",
    "Reading every saved file again and comparing it with its checksum…":
        "Lese jede gesicherte Datei erneut und vergleiche sie mit ihrer Prüfsumme …",
    "File {i} of {n}": "Datei {i} von {n}",
    "{n} files are intact ({size}).": "{n} Dateien sind in Ordnung ({size}).",
    "Missing:": "Fehlen:",
    "Changed or damaged:": "Verändert oder beschädigt:",
    "Missing files are copied again on the next backup, as long as they are still on the iPhone.":
        "Fehlende Dateien werden bei der nächsten Sicherung erneut kopiert, solange sie noch auf dem iPhone sind.",
    "Troubleshooting": "Problemlösung",
    "Release stuck iPhone folders": "Hängende iPhone-Ordner lösen",
    "Pair again (ask for Trust again)": "Neu koppeln (Vertrauen erneut abfragen)",
    "Restart the iPhone service (usbmuxd)": "iPhone-Dienst neu starten (usbmuxd)",
    "Restart the iPhone service (Apple Mobile Device Service)":
        "iPhone-Dienst neu starten (Apple Mobile Device Service)",
    "“Apple Devices” from the Microsoft Store (or iTunes from apple.com)":
        "„Apple Geräte“ aus dem Microsoft Store (oder iTunes von apple.com)",
    "Open Microsoft Store": "Microsoft Store öffnen",
    "Update now": "Jetzt aktualisieren",
    "Check now": "Jetzt prüfen",
    "Installed: {v}": "Installiert: {v}",
    "Check for updates…": "Nach Updates suchen …",
    "Could not ask GitHub: {msg}": "GitHub ließ sich nicht fragen: {msg}",
    "You have the newest version ({v}).": "Du hast die neueste Version ({v}).",
    "Open download page": "Download-Seite öffnen",
    "Later": "Später",
    "Checking the HEIC converter…": "Prüfe HEIC-Konverter …",
    "Downloads the new version, checks it and restarts DCIMDock.":
        "Lädt die neue Version herunter, prüft sie und startet DCIMDock neu.",
    "Please wait until the backup is finished.": "Bitte warte, bis die Sicherung fertig ist.",
    "Downloading…": "Lade herunter …",
    "The update did not work: {msg}": "Das Update hat nicht geklappt: {msg}",
    "You can download it by hand: {page}": "Du kannst es von Hand herunterladen: {page}",
    "Start the iPhone service": "iPhone-Dienst starten",
    "Could not start the service: {msg}": "Der Dienst ließ sich nicht starten: {msg}",
    "“Apple Devices” is installed, but its driver did not start. Sign out of Windows and in again, or restart the PC.":
        "„Apple Geräte“ ist installiert, aber sein Treiber ist nicht gestartet. Melde dich bei Windows ab und wieder an oder starte den PC neu.",
    "Diagnosis…": "Diagnose …",
    "Diagnosis": "Diagnose",
    "Paste this into a bug report:": "Für eine Fehlermeldung hier herauskopieren:",
    "Copy": "Kopieren",
    "Working…": "Arbeite …",
    "Released: {where}": "Gelöst: {where}",
    "No iPhone folder was mounted.": "Es war kein iPhone-Ordner eingehängt.",
    "Paired again.": "Neu gekoppelt.",
    "The iPhone service was restarted. Unplug the iPhone and plug it in again.":
        "Der iPhone-Dienst wurde neu gestartet. Zieh das iPhone ab und steck es wieder an.",
    "Could not restart the service: {msg}": "Der Dienst ließ sich nicht neu starten: {msg}",
    "Released a stuck iPhone folder: {where}": "Hängenden iPhone-Ordner gelöst: {where}",
    "The photos are not visible yet. Unlock your iPhone. (If it has no photos at all, this stays.)":
        "Die Fotos sind noch nicht sichtbar. Entsperre dein iPhone. (Hat es gar keine Fotos, bleibt das so.)",
    # 0.1.0 – capture date, screenshots, several iPhones
    "Sort by the date the photo was taken (EXIF)": "Nach Aufnahmedatum sortieren (EXIF)",
    "Reads the capture date from the photo or video. Off: the file date is used, which for saved or imported pictures is the day they were saved.":
        "Liest das Aufnahmedatum aus Foto oder Video. Aus: Es zählt das Dateidatum, bei gespeicherten oder importierten Bildern also der Tag des Speicherns.",
    "Screenshots apart": "Screenshots trennen",
    "Screenshots": "Screenshots",
    "Reading capture dates… {i} of {n}": "Lese Aufnahmedaten … {i} von {n}",
    "Several iPhones are connected. Pick the one to back up.":
        "Mehrere iPhones sind angeschlossen. Wähle das, das gesichert werden soll.",
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
stay complete. {heic} Pick <b>Most Compatible</b> (JPEG/H.264) only if old programs or
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
Porträt-Tiefendaten bleiben vollständig. {heic} <b>Maximale Kompatibilität</b> (JPEG/H.264)
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
    if sys.platform == "win32":
        try:
            import ctypes
            # primary language of the UI language: 0x07 is German
            return "de" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x07 else "en"
        except (AttributeError, OSError):
            pass
    lang = (locale.getlocale()[0] or "").lower()
    return "de" if lang.startswith("de") else "en"


HEIC = {
    ("en", False): "Linux opens HEIC almost everywhere today (KDE, GNOME, GIMP, darktable).",
    ("de", False): "Linux öffnet HEIC heute fast überall (KDE, GNOME, GIMP, darktable).",
    ("en", True): "Windows opens HEIC with the free <i>HEIF Image Extensions</i> from the "
                  "Microsoft Store; HEVC videos need the <i>HEVC Video Extensions</i> (or VLC).",
    ("de", True): "Windows öffnet HEIC mit den kostenlosen <i>HEIF-Bilderweiterungen</i> aus dem "
                  "Microsoft Store; HEVC-Videos brauchen die <i>HEVC-Videoerweiterungen</i> (oder VLC).",
}


LANG = _pick()


def tr(text: str, **kw) -> str:
    if text == "INTRO_HTML":
        intro = INTRO_DE if LANG == "de" else INTRO_EN
        return intro.replace("{heic}", HEIC[(LANG, sys.platform == "win32")])
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
