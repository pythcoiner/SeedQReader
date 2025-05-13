# SeedQReader

<img src="assets/icon.png" width="64"/>

**SeedQReader** is a simple tool made for communicate with airgapped Bitcoin Signer.

![SeedQReader](screenshot.png)

It actually can send/receive:
- 1 Frame QRCodes
- Multiframes QRCodes using the `Specter` format (_p M of N_)
- Multiframes QRCodes using the `UR` format are partially supported (PSBT and Bytes)
- Multiframes QRCodes using the `BBQR` format are partially supported (PSBT)

## Download the latest releases
[<img src="assets/badge_github.png" alt="github releases page" width="186">](https://github.com/tadeubas/seedQReader/releases)

## Install

To install on **Linux**, enter the repo folder and run:
```
# create environment to install dependencies
python3 -m venv .seedqrenv

# activate the environment on the current terminal
source .seedqrenv/bin/activate

# install python dependencies on this environment
pip install -r requirements.txt 
```

If you get this error on **Linux**, please install libxcb-cursor:
```
# qt.qpa.plugin: From 6.5.0, xcb-cursor0 or libxcb-cursor0 is needed to load the Qt xcb platform plugin.
sudo apt install libxcb-cursor0
```

To install on **Windows**:
```
# create environment to install dependencies
python -m venv .seedqrenv

# activate the environment on the current cmd
.seedqrenv\Scripts\activate

# install python dependencies on this environment
pip install -r requirements.txt
```

If you get this error on **Windows**, install `vcredist_x64.exe` [Visual C++ Redistributable Packages for Visual Studio 2013](https://www.microsoft.com/en-US/download/details.aspx?id=40784). Then uninstall and install `pyzbar` lib again:
```
FileNotFoundError: Could not find module 'libiconv.dll' (or one of its dependencies). Try using the full path with constructor syntax.
pyimod03_ctypes.install.<locals>.PyInstallerImportError: Failed to load dynlib/dll 'libiconv.dll'. Most likely this dynlib/dll was not found when the application was frozen.
[PYI-5780:ERROR] Failed to execute script 'seedqreader' due to unhandled exception!
```

## Run

**Linux/MacOS**:
```
python3 seedqreader.py
```

**Windows**:
```
python seedqreader.py
```


## Build binaries

```
pip install PyInstaller
python3 .ci/create-spec.py
python3 -m PyInstaller seedqreader.spec
```

## Acknowledgements & Alternatives

Big thanks to [pythcoiner](https://github.com/pythcoiner) for originally creating SeedQReader! 🙌

If SeedQReader isn’t your vibe, check out [bitcoin-qr-tools](https://github.com/andreasgriffin/bitcoin-qr-tools) for another awesome QR code tool for BTC stuff. 😄
