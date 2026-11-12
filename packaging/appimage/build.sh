#!/usr/bin/env bash
# Builds dist/dcimdock-<version>-x86_64.AppImage (+ .zsync for Gear Lever /
# AppImageUpdate). Meant for CI (see .github/workflows/release.yml), works on
# any x86_64 Linux with curl and FUSE or the extract-and-run fallback.
#
# Base: a relocatable Python from niess/python-appimage, PySide6-Essentials
# from PyPI, then everything Qt Quick/QML/designer is pruned away.
set -euo pipefail

PY=3.12
here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
root="$(cd "$here/../.." && pwd)"
version="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$root/dcimdock/__init__.py")"
work="$root/build/appimage"
dist="$root/dist"
out="$dist/dcimdock-$version-x86_64.AppImage"
update_info="gh-releases-zsync|TechnikWeber|DCIMDock|latest|dcimdock-*-x86_64.AppImage.zsync"

rm -rf "$work"
mkdir -p "$work" "$dist"
cd "$work"
export APPIMAGE_EXTRACT_AND_RUN=1   # no FUSE needed on CI runners

# ---- 1. relocatable Python ------------------------------------------------
# Anonymous API calls share a small limit per IP (CI runners hit it: 403);
# with the workflow's token they count against the repository instead.
auth=()
[ -n "${GITHUB_TOKEN:-}" ] && auth=(-H "Authorization: Bearer $GITHUB_TOKEN")
asset=$(curl -fsSL --retry 3 "${auth[@]}" "https://api.github.com/repos/niess/python-appimage/releases/tags/python$PY" \
    | grep -o "\"name\": *\"python${PY}[^\"]*manylinux_2_28_x86_64.AppImage\"" \
    | head -1 | sed 's/.*"\(python[^"]*\)"/\1/')
[ -n "$asset" ] || { echo "no python $PY AppImage found" >&2; exit 1; }
echo "base: $asset"
curl -fsSL -o python.AppImage "https://github.com/niess/python-appimage/releases/download/python$PY/$asset"
chmod +x python.AppImage
./python.AppImage --appimage-extract >/dev/null
mv squashfs-root AppDir
python_rel="$(cd AppDir && ls -d opt/python$PY/bin/python$PY)"
py="AppDir/$python_rel"

# ---- 2. PySide6 + the app -------------------------------------------------
"$py" -m pip install --no-compile --no-warn-script-location -q -r "$here/requirements.txt"
"$py" -m pip install --no-compile --no-warn-script-location --no-deps -q "$root"

# ---- 3. prune what a QtWidgets app never loads ----------------------------
site="$("$py" -c 'import PySide6, os; print(os.path.dirname(PySide6.__file__))')"
(
    cd "$site"
    rm -rf Qt/qml Qt/translations Qt/libexec include typesystems glue scripts \
           designer linguist assistant lupdate lrelease qmllint qmlformat qmlls \
           qmlcachegen qmltyperegistrar qmlimportscanner rcc uic balsam* \
           Qt/plugins/{qmltooling,sqldrivers,designer,qmllint,multimedia}
    for lib in Quick Qml Pdf Designer Help Sql Test ShaderTools VirtualKeyboard \
               LabsAnimation LabsFolderListModel LabsQmlModels LabsSettings \
               LabsSharedImage LabsWavefrontMesh LabsPlatform QmlModels; do
        rm -f Qt/lib/libQt6"$lib"*.so* Qt"$lib"*.abi3.so Qt"$lib"*.pyi
    done
)
find AppDir -name '__pycache__' -prune -exec rm -rf {} +
rm -rf AppDir/opt/python$PY/lib/python$PY/{test,idlelib,tkinter,ensurepip,lib2to3}

# ---- 4. AppImage metadata -------------------------------------------------
rm -f AppDir/*.desktop AppDir/*.png AppDir/*.svg AppDir/.DirIcon AppDir/usr/share/metainfo/*.xml
# python-appimage ships AppRun as a symlink into usr/bin; writing through it
# would clobber the target, so replace the link with a real file
rm -f AppDir/AppRun
cat > AppDir/AppRun <<EOF
#!/bin/bash
# -I: ignore PYTHONPATH and user site-packages, only use what is bundled
here="\${APPDIR:-\$(dirname "\$(readlink -f "\${0}")")}"
exec "\$here/$python_rel" -I -m dcimdock "\$@"
EOF
chmod +x AppDir/AppRun
install -Dm644 "$root/share/dcimdock.desktop" AppDir/dcimdock.desktop
install -Dm644 "$root/share/dcimdock.desktop" AppDir/usr/share/applications/dcimdock.desktop
# file managers want a PNG for the AppImage's own icon
install -Dm644 "$root/share/dcimdock.png" AppDir/dcimdock.png
install -Dm644 "$root/share/dcimdock.png" AppDir/usr/share/icons/hicolor/256x256/apps/dcimdock.png
install -Dm644 "$root/dcimdock/dcimdock.svg" AppDir/usr/share/icons/hicolor/scalable/apps/dcimdock.svg
ln -sf dcimdock.png AppDir/.DirIcon
install -Dm644 "$root/share/io.github.technikweber.dcimdock.metainfo.xml" \
    AppDir/usr/share/metainfo/io.github.technikweber.dcimdock.appdata.xml

# python-appimage extracts with 0700 directories; the AppImage must be
# readable for every user
chmod -R a+rX AppDir

# ---- 5. pack --------------------------------------------------------------
curl -fsSL -o appimagetool \
    https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x appimagetool
rm -f "$out" "$out.zsync"
ARCH=x86_64 ./appimagetool --no-appstream -u "$update_info" AppDir "$out"
mv -f "$(basename "$out").zsync" "$dist/" 2>/dev/null || true
ls -lh "$dist"
