# Builds dist\DCIMDock-<version>-windows-x64.exe: one file, no installer, no
# admin rights. Meant for CI (see .github/workflows/release.yml), works on any
# Windows 10/11 with Python 3.12 on the PATH.
#
# The .exe brings Python, Qt and pymobiledevice3. Apple's driver (the
# "Apple Devices" app or iTunes) must be installed on the PC: it provides the
# Apple Mobile Device Service, the Windows counterpart of usbmuxd.
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$root = (Resolve-Path "$here\..\..").Path
$version = (Select-String -Path "$root\dcimdock\__init__.py" -Pattern '__version__ = "(.*)"').Matches[0].Groups[1].Value
$work = "$root\build\windows"
$name = "DCIMDock-$version-windows-x64"

if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory -Force $work, "$root\dist" | Out-Null

python -m pip install --disable-pip-version-check -q -r "$here\requirements.txt"
if ($LASTEXITCODE) { throw "pip failed" }
python -m pip install --disable-pip-version-check -q --no-deps "$root"
if ($LASTEXITCODE) { throw "pip install of dcimdock failed" }

python "$here\make_icon.py" "$work\dcimdock.ico"
if ($LASTEXITCODE) { throw "icon failed" }

# Only the Qt modules a QtWidgets app loads; pymobiledevice3's lazy parts
# (tunnels, web inspector, IPython shell) are never imported by DCIMDock.
python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name $name `
    --icon "$work\dcimdock.ico" `
    --workpath "$work\pyi" --specpath $work --distpath "$root\dist" `
    --collect-data dcimdock `
    --collect-data pymobiledevice3 `
    --hidden-import pymobiledevice3.services.afc `
    --hidden-import pymobiledevice3.lockdown `
    --hidden-import pymobiledevice3.usbmux `
    --exclude-module tkinter --exclude-module IPython `
    --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick `
    --exclude-module PySide6.QtNetwork `
    "$here\launcher.py"
if ($LASTEXITCODE) { throw "PyInstaller failed" }

Get-Item "$root\dist\$name.exe" | Format-Table Name, Length
