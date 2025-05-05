# The MIT License (MIT)

# Copyright (c) 2021-2024 Krux contributors

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

# This code an adaptation of Coinkite's BBQr python implementation for Krux environment
# https://github.com/coinkite/BBQr

import gc

# BBQR
KNOWN_ENCODINGS = {"H", "2", "Z"}

# File types
# P='PSBT', T='Transaction', J='JSON', C='CBOR'
# U='Unicode Text', X='Executable', B='Binary'
KNOWN_FILETYPES = {"P", "T", "J", "U"}

BBQR_ALWAYS_COMPRESS_THRESHOLD = 5000  # bytes

B32CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
assert len(B32CHARS) == 32

BBQR_PREFIX_LENGTH = 8

QR_CAPACITY_ALPHANUMERIC = [
    25,
    47,
    77,
    114,
    154,
    195,
    224,
    279,
    335,
    395,
    468,
    535,
    619,
    667,
    758,
    854,
    938,
    1046,
    1153,
    1249,
]

class BBQrCode:
    """A BBQr code, containing the data, encoding, and file type"""


    def __init__(self, payload, encoding=None, file_type=None):
        """Initializes the BBQr code with the given data, encoding, and file type"""

        if encoding not in KNOWN_ENCODINGS:
            raise ValueError("Invalid BBQr encoding")
        if file_type not in KNOWN_FILETYPES:
            raise ValueError("Invalid BBQr file type")
        self.payload = payload
        self.encoding = encoding
        self.file_type = file_type

    def find_min_num_parts(self, max_width):
        qr_capacity = self.max_qr_bytes(max_width)
        data_length = len(self.payload)
        max_part_size = qr_capacity - BBQR_PREFIX_LENGTH
        if data_length < max_part_size:
            return 1, data_length
        # Round max_part_size to the nearest lower multiple of 8
        max_part_size = (max_part_size // 8) * 8
        # Calculate the number of parts required (rounded up)
        num_parts = (data_length + max_part_size - 1) // max_part_size
        # Calculate the optimal part size
        part_size = data_length // num_parts
        # Round to the nearest higher multiple of 8
        part_size = ((part_size + 7) // 8) * 8
        # Check if the part size is within the limits
        if part_size > max_part_size:
            num_parts += 1
            part_size = data_length // num_parts
            # Round to the nearest higher multiple of 8 again
            part_size = ((part_size + 7) // 8) * 8
        return num_parts, part_size

    def max_qr_bytes(self, max_width):
        """Calculates the maximum length, in bytes, a QR code of a given size can store"""
        # Given qr_size = 17 + 4 * version + 2 * frame_size
        max_width -= 2  # Subtract frame width
        qr_version = (max_width - 17) // 4
        capacity_list = QR_CAPACITY_ALPHANUMERIC

        try:
            return capacity_list[qr_version - 1]
        except:
            # Limited to version 20
            return capacity_list[-1]
        
    def to_qr_code(self, max_width):
        num_parts, part_size = self.find_min_num_parts(max_width)
        part_index = 0
        while True:
            header = "B$%s%s%s%s" % (
                self.encoding,
                self.file_type,
                int2base36(num_parts),
                int2base36(part_index),
            )
            part = None
            if part_index == num_parts - 1:
                part = header + self.payload[part_index * part_size :]
                part_index = 0
            else:
                part = (
                    header
                    + self.payload[
                        part_index * part_size : (part_index + 1) * part_size
                    ]
                )
                part_index += 1
            yield (part, num_parts)

    def parse(self, data):
        part, index, total = parse_bbqr(data)
        self.parts[index] = part
        self.total = total
        return index



def parse_bbqr(data):
    """
    Parses the QR as a BBQR part, extracting the part's content,
    encoding, file format, index, and total
    """
    if len(data) < 8:
        raise ValueError("Invalid BBQR format")

    encoding = data[2]
    if encoding not in KNOWN_ENCODINGS:
        raise ValueError("Invalid encoding")

    file_type = data[3]
    if file_type not in KNOWN_FILETYPES:
        raise ValueError("Invalid file type")

    try:
        part_total = int(data[4:6], 36)
        part_index = int(data[6:8], 36)
    except ValueError:
        raise ValueError("Invalid BBQR format")

    if part_index >= part_total:
        raise ValueError("Invalid part index")

    return data[8:], part_index, part_total


def deflate_compress(data):
    """Compresses the given data using deflate module"""
    try:
        import deflate
        from io import BytesIO

        stream = BytesIO()
        with deflate.DeflateIO(stream) as d:
            d.write(data)
        return stream.getvalue()
    except Exception as e:
        print(e)
        raise ValueError("Error compressing BBQR")


def deflate_decompress(data):
    """Decompresses the given data using deflate module"""
    try:
        import deflate
        from io import BytesIO

        with deflate.DeflateIO(BytesIO(data)) as d:
            return d.read()
    except:
        raise ValueError("Error decompressing BBQR")


def decode_bbqr(parts, encoding, file_type):
    """Decodes the given data as BBQR, returning the decoded data"""

    if encoding == "H":
        from binascii import unhexlify

        data_bytes = bytearray()
        for _, part in sorted(parts.items()):
            data_bytes.extend(unhexlify(part))
        return bytes(data_bytes)

    binary_data = b""
    for _, part in sorted(parts.items()):
        padding = (8 - (len(part) % 8)) % 8
        padded_part = part + (padding * "=")
        binary_data += base32_decode_stream(padded_part)

    if encoding == "Z":
        if file_type in "JU":
            return deflate_decompress(binary_data).decode("utf-8")
        return deflate_decompress(binary_data)
    if file_type in "JU":
        return binary_data.decode("utf-8")
    return binary_data


def encode_bbqr(data, encoding="Z", file_type="P"):
    """Encodes the given data as BBQR, returning the encoded data and format"""

    if encoding == "H":
        from binascii import hexlify

        data = hexlify(data).decode()
        return BBQrCode(data.upper(), encoding, file_type)

    if encoding == "Z":
        if len(data) > BBQR_ALWAYS_COMPRESS_THRESHOLD:
            # RAM won't be enough to have both compressed and not compressed data
            # It will always be beneficial to compress large data
            data = deflate_compress(data)
        else:
            # Check if compression is beneficial
            cmp = deflate_compress(data)
            if len(cmp) >= len(data):
                encoding = "2"
            else:
                encoding = "Z"
                data = cmp

    data = data.encode("utf-8") if isinstance(data, str) else data
    gc.collect()
    return BBQrCode("".join(base32_encode_stream(data)), encoding, file_type)


# Base 32 encoding/decoding, used in BBQR only


def base32_decode_stream(encoded_str):
    """Decodes a Base32 string"""
    base32_index = {ch: index for index, ch in enumerate(B32CHARS)}

    # Strip padding
    encoded_str = encoded_str.rstrip("=")

    buffer = 0
    bits_left = 0
    decoded_bytes = bytearray()

    for char in encoded_str:
        if char not in base32_index:
            raise ValueError("Invalid Base32 character: %s" % char)
        index = base32_index[char]
        buffer = (buffer << 5) | index
        bits_left += 5

        while bits_left >= 8:
            bits_left -= 8
            decoded_bytes.append((buffer >> bits_left) & 0xFF)
            buffer &= (1 << bits_left) - 1  # Keep only the remaining bits

    return bytes(decoded_bytes)


def base32_encode_stream(data, add_padding=False):
    """A streaming base32 encoder"""
    buffer = 0
    bits_left = 0

    for byte in data:
        buffer = (buffer << 8) | byte
        bits_left += 8

        while bits_left >= 5:
            bits_left -= 5
            yield B32CHARS[(buffer >> bits_left) & 0x1F]
            buffer &= (1 << bits_left) - 1  # Keep only the remaining bits

    if bits_left > 0:
        buffer <<= 5 - bits_left
        yield B32CHARS[buffer & 0x1F]

    # Padding
    if add_padding:
        encoded_length = (len(data) * 8 + 4) // 5
        padding_length = (8 - (encoded_length % 8)) % 8
        for _ in range(padding_length):
            yield "="


def int2base36(n):
    """Convert integer n to a base36 string."""
    if not 0 <= n <= 1295:  # ensure the number is within the valid range
        raise ValueError("Number out of range")

    def tostr(x):
        """Convert integer x to a base36 character."""
        return chr(48 + x) if x < 10 else chr(65 + x - 10)

    quotient, remainder = divmod(n, 36)
    return tostr(quotient) + tostr(remainder)

