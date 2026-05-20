# GridLAB-D Installation for OS X

In OS X El Capitan and later, System Integrity Protection prevents any attempts to install GridLAB-D (latest version 4.0.0) using the official dmg. A successful workaround is to manually extract the files from the dmg and move them into the appropriate local directories.

## Extracting files from official GridLAB-D .dmg

1. Download latest version of [GridLAB-D](https://sourceforge.net/projects/gridlab-d/?source=navbar).

1. Double-click the DMG file. This will open the file with DiskImageMounter utility. A dialog window will appear, verifying the file and mounting it. Once mounted, the DMG will appear in the Finder sidebar under the "Devices" header along with the hard drive.

1. Open a Finder window (click the "Finder" icon in the dock). Highlight the mounted image file within Finder's sidebar. A file named "gridlabd.mpkg" will appear in the main Finder window pane.

1. Right-click "gridlabd.mpkg" and select "Show Package Contents" on the dropdown menu. A folder named "Contents" will appear in the Finder window. Navigate directory to "Contents" > "Packages".

1. Right-click core.pkg and select "Show Package Contents" on the dropdown menu. Open "Contents" folder. Unzip "Archive.pax.gz" file.

1. Drag the files you wish to extract to the desired destination on your computer.

### File List

* /usr/local/share/gridlabd/gridlabd.htm
* /usr/local/share/gridlabd
* /usr/local/share/gridlabd/gridlabd.syn
* /usr/local/share/gridlabd/gridlabd.js
* /usr/local/share/gridlabd/gridlabd.jpg
* /usr/local/share/gridlabd/gridlabd.h
* /usr/local/share/gridlabd/gridlabd.css
* /usr/local/share/gridlabd/gridlabd.conf
* /usr/local/share/doc/gridlabd
* /usr/local/lib/gridlabd
* /usr/local/bin/gridlabd
* /usr/local/bin/gridlabd.bin
* /usr/local/include/gridlabd

Check installation path by typing in terminal:
`$ mdfind -name gridlabd -onlyin /usr`