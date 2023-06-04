SeedQReader
---

SeedQReader is a simple tool i made for communicate with my SeedSigner.

![SeedQReader](screenshot.png)

It actually can send/receive:
- 1 Frame QRCodes
- Multiframes QRCodes using the `Specter` format (1of3 dddddddddddddddddddddddddddddddddddddddddddd)

The 'split' size can be set with `MAX_LEN`

Delay between 2 frames can be set with `QR_DELAY`

Install:
Go into this repo and run:
```
pip install -r requirements.txt 
```

Run under Linux/MacOS:
```
python3 seedqreader.py
```

Run under Windows:
```
python seedqreader.py
```

TODO:
- Let user choose QR code size (slider?)
- Add clear buttons on send input field
- Support UR format

