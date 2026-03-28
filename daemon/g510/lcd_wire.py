"""
g510.lcd_wire — G510 LCD HID wire format encoder.

The G510 uses a 160x43 monochrome GamePanel display.
Wire format (reverse-engineered from libg15 and kernel hid-lg-g15.c):

  43 rows / 7 rows-per-page = 6 full pages + 1 partial = 7 pages total.

  Report structure (256 bytes per page):
    Byte  0:    Report ID = 0x03
    Byte  1:    0x00
    Byte  2:    Page index (0-6)
    Byte  3:    0x00
    Bytes 4-163: 160 column bytes.
                 Each byte encodes up to 7 rows for that column:
                   bit 0 = topmost row of this page
                   bit 6 = 7th row (or unused if partial page)
                   bit 7 = always 0

Full frame = 7 reports x 256 bytes = 1792 bytes.
Pages 0-5: 7 rows each (rows 0-41). Page 6: 1 row (row 42).
"""

from typing import List

LCD_WIDTH     = 160
LCD_HEIGHT    = 43
ROWS_PER_PAGE = 7
PAGES         = (LCD_HEIGHT + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE  # = 7

REPORT_ID  = 0x03
REPORT_LEN = 256


def encode_frame(pixels) -> List[bytes]:
    """
    Convert a 160x43 pixel array to a list of 7 HID page reports.

    pixels: PIL Image (mode "1"/"L", 0=black=lit) or list-of-lists [row][col] (1=lit).
    Returns: list of 7 bytes objects, each 256 bytes.
    """
    if hasattr(pixels, 'getpixel'):
        def px(col, row):
            v = pixels.getpixel((col, row))
            if isinstance(v, (list, tuple)):
                v = v[0]
            return 1 if (v == 0) else 0
    elif hasattr(pixels, 'load'):
        pix = pixels.load()
        def px(col, row):
            v = pix[col, row]
            if isinstance(v, (list, tuple)):
                v = v[0]
            return 1 if (v == 0) else 0
    else:
        def px(col, row):
            return pixels[row][col]

    reports = []
    for page in range(PAGES):
        data = bytearray(REPORT_LEN)
        data[0] = REPORT_ID
        data[1] = 0x00
        data[2] = page
        data[3] = 0x00
        for col in range(LCD_WIDTH):
            byte = 0
            for bit in range(ROWS_PER_PAGE):
                row = page * ROWS_PER_PAGE + bit
                if row < LCD_HEIGHT:
                    if px(col, row):
                        byte |= (1 << bit)
            data[4 + col] = byte
        reports.append(bytes(data))
    return reports


def send_frame(hidraw_path: str, reports: List[bytes]) -> bool:
    """Write all page reports to the hidraw device. Returns True on success."""
    try:
        with open(hidraw_path, 'wb') as f:
            for report in reports:
                f.write(report)
        return True
    except OSError:
        return False


def frame_from_pil(img) -> List[bytes]:
    """Convenience: PIL Image -> list of reports."""
    img = img.convert('1').resize((LCD_WIDTH, LCD_HEIGHT))
    return encode_frame(img)
