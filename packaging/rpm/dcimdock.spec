Name:           dcimdock
Version:        0.5.3
Release:        1%{?dist}
Summary:        Copy the photos and videos from an iPhone to this computer
License:        MIT
URL:            https://github.com/TechnikWeber/DCIMDock
Source0:        %{url}/archive/v%{version}/%{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  desktop-file-utils
Requires:       python3-pyside6
Requires:       ifuse
Requires:       libimobiledevice-utils
Requires:       usbmuxd
# HEIC previews
Recommends:     kf6-kimageformats
Recommends:     libheif-tools

%description
A small window that copies the camera roll of an iPhone over USB: only new
files, never overwriting, with a progress bar and an optional preview.
Nothing on the iPhone is changed.

%prep
%autosetup

%build
# pure Python, nothing to build

%install
install -d %{buildroot}%{python3_sitelib}/dcimdock
install -m644 dcimdock/*.py dcimdock/dcimdock.svg %{buildroot}%{python3_sitelib}/dcimdock/
install -Dm755 /dev/stdin %{buildroot}%{_bindir}/dcimdock <<'SH'
#!/usr/bin/python3 -s
from dcimdock.app import main
raise SystemExit(main())
SH
desktop-file-install --dir=%{buildroot}%{_datadir}/applications share/dcimdock.desktop
install -Dm644 dcimdock/dcimdock.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/dcimdock.svg
install -Dm644 share/io.github.technikweber.dcimdock.metainfo.xml \
    %{buildroot}%{_metainfodir}/io.github.technikweber.dcimdock.metainfo.xml

%check
%{python3} -m unittest discover -s tests -t .

%files
%license LICENSE
%doc README.md CHANGELOG.md
%{_bindir}/dcimdock
%{python3_sitelib}/dcimdock/
%{_datadir}/applications/dcimdock.desktop
%{_datadir}/icons/hicolor/scalable/apps/dcimdock.svg
%{_metainfodir}/io.github.technikweber.dcimdock.metainfo.xml

%changelog
* Thu Nov 12 2026 Philipp Weber - 0.5.3-1
- Windows: start the Apple Devices driver right after installing it

* Thu Nov 12 2026 Philipp Weber - 0.5.2-1
- Windows: link to the Apple Devices app in the Microsoft Store

* Thu Nov 12 2026 Philipp Weber - 0.5.0-1
- Beta: read the Photos library (Recently Deleted, iCloud-only, favorites, albums)

* Thu Nov 12 2026 Philipp Weber - 0.4.0-1
- Automatic backup, rename by capture time, JPEG next to HEIC, update notice

* Thu Nov 12 2026 Philipp Weber - 0.3.0-1
- Choose what to copy: period, kinds, Live Photo videos, edits

* Thu Nov 12 2026 Philipp Weber - 0.2.0-1
- Windows build (no change on Linux)

* Wed Nov 11 2026 Philipp Weber - 0.1.1-1
- First release
