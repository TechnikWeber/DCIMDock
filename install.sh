#!/usr/bin/env bash
# Puts DCIMDock into the application menu (for your user only) and offers to
# install what it needs from your distribution: PySide6, ifuse,
# libimobiledevice and usbmuxd. Only the package install uses sudo.
set -euo pipefail

here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
cd "$here"

apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
icons="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
bin="$HOME/.local/bin"

# shellcheck disable=SC1091
. /etc/os-release 2>/dev/null || true
ids=" ${ID:-} ${ID_LIKE:-} "
case "$ids" in
    *" fedora "*|*" rhel "*)
        pm="sudo dnf install -y"
        pkgs="python3-pyside6 ifuse libimobiledevice-utils usbmuxd" ;;
    *" debian "*|*" ubuntu "*)
        pm="sudo apt install -y"
        pkgs="python3-pyside6.qtwidgets ifuse libimobiledevice-utils usbmuxd" ;;
    *" arch "*)
        pm="sudo pacman -S --needed"
        pkgs="pyside6 ifuse libimobiledevice usbmuxd" ;;
    *" opensuse"*|*" suse "*)
        pm="sudo zypper install -y"
        pkgs="python3-pyside6 ifuse imobiledevice-tools usbmuxd" ;;
    *)
        pm=""
        pkgs="" ;;
esac

need=0
python3 -c "import PySide6.QtWidgets" 2>/dev/null || need=1
for tool in ifuse idevice_id idevicepair; do
    command -v "$tool" >/dev/null || need=1
done

if [ "$need" = 0 ]; then
    echo "PySide6, ifuse and libimobiledevice: already installed."
elif [ -n "$pm" ]; then
    read -r -p "Install the missing packages now with '$pm $pkgs'? [Y/n] " reply
    case "$reply" in
        [nN]*) echo "Skipped. Install them, then run this script again."; exit 1 ;;
        *)     # shellcheck disable=SC2086
               $pm $pkgs ;;
    esac
else
    echo "Please install PySide6, ifuse, libimobiledevice (tools) and usbmuxd from your distribution."
    exit 1
fi

mkdir -p "$apps" "$bin" "$icons/scalable/apps" "$icons/256x256/apps"
install -m644 dcimdock/dcimdock.svg "$icons/scalable/apps/dcimdock.svg"
install -m644 share/dcimdock.png "$icons/256x256/apps/dcimdock.png"
# the menu does not see ~/.local/bin on every system, so bake in the full path
sed "s|^Exec=.*|Exec=$here/bin/dcimdock|" share/dcimdock.desktop > "$apps/dcimdock.desktop"
chmod 644 "$apps/dcimdock.desktop"
ln -sf "$here/bin/dcimdock" "$bin/dcimdock"

command -v update-desktop-database >/dev/null && update-desktop-database "$apps" 2>/dev/null || true
command -v gtk-update-icon-cache   >/dev/null && gtk-update-icon-cache -qtf "$icons" 2>/dev/null || true
command -v kbuildsycoca6           >/dev/null && kbuildsycoca6 --noincremental 2>/dev/null || true

cat <<MSG

Done.

  * Application menu: search for "DCIMDock".
  * Terminal:         dcimdock          (window)
                      dcimdock --cli    (no window)

Remove again with ./uninstall.sh
MSG
