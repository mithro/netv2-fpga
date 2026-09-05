"""Test-pattern definitions shared by the source agent (rpiz-3, py3.13) and the
runner (rpi3-netv2, py3.5).  Keep this file python-3.5 compatible: no f-strings,
no variable annotations.

All geometry is defined in *source* pixels for a WxH frame (default
1920x1080).  Decoders receive a captured frame of arbitrary size and scale
coordinates with scale_x = cap_w / W, scale_y = cap_h / H.

Frame-counter strip
-------------------
A row of NBLOCKS square blocks (BLOCK px each) starting at x=0, encoding:

    [1, 0, b15..b0 (Gray code of counter), parity(b15..b0), 1]

That is 2 sync blocks, 16 data blocks, 1 parity block, 1 trailing sync block
= 20 blocks = 1920 px when BLOCK = 96.  Blocks are white (1) or black (0).

Two strips exist: SRC_STRIP_Y (drawn by the source, passthrough path) and
OVL_STRIP_Y (drawn by the overlay Pi, overlay path).  The source keeps the
OVL strip area black so that transparent overlay pixels read as black.
"""

W = 1920
H = 1080

BLOCK = 96
NBLOCKS = 20
STRIP_H = 96
SRC_STRIP_Y = 200
OVL_STRIP_Y = 400

# Colour bars (top 2/3) and grey ramp (bottom 1/3) for the fidelity test.
BAR_COLOURS = [
    (255, 255, 255),
    (255, 255, 0),
    (0, 255, 255),
    (0, 255, 0),
    (255, 0, 255),
    (255, 0, 0),
    (0, 0, 255),
    (0, 0, 0),
]
GREY_STEPS = [0, 36, 73, 109, 146, 182, 219, 255]
BARS_SPLIT_Y = 720  # bars above, greys below

# Geometry pattern: white squares on black.
GEO_CORNER = 64            # corner square size
GEO_CENTRE = (860, 440, 200, 200)   # x, y, w, h
GEO_MARK = (300, 600, 100, 100)     # off-centre marker
GEO_BORDER = 4             # white border width


def gray_encode(n):
    return n ^ (n >> 1)


def gray_decode(g):
    n = 0
    while g:
        n ^= g
        g >>= 1
    return n


def counter_bits(counter):
    """Return the list of NBLOCKS 0/1 values encoding `counter` (16-bit)."""
    g = gray_encode(counter & 0xFFFF)
    bits = [(g >> (15 - i)) & 1 for i in range(16)]
    parity = sum(bits) & 1
    return [1, 0] + bits + [parity, 1]


def decode_counter_bits(bits):
    """Inverse of counter_bits.  Returns counter or None if framing/parity fail."""
    if len(bits) != NBLOCKS:
        return None
    if bits[0] != 1 or bits[1] != 0 or bits[19] != 1:
        return None
    data = bits[2:18]
    if (sum(data) & 1) != bits[18]:
        return None
    g = 0
    for b in data:
        g = (g << 1) | b
    return gray_decode(g)


def strip_sample_points(strip_y, cap_w, cap_h, w=W, h=H):
    """Centre sample coordinates (x, y) of each block in a captured frame."""
    sx = float(cap_w) / w
    sy = float(cap_h) / h
    y = int((strip_y + STRIP_H / 2.0) * sy)
    pts = []
    for i in range(NBLOCKS):
        x = int((i * BLOCK + BLOCK / 2.0) * sx)
        pts.append((x, y))
    return pts


def strip_sample_box(strip_y, cap_w, cap_h, i, w=W, h=H):
    """A small box (x0, y0, x1, y1) in the centre of block i for averaging."""
    sx = float(cap_w) / w
    sy = float(cap_h) / h
    bw = BLOCK * sx
    bh = STRIP_H * sy
    cx = i * bw + bw / 2.0
    cy = strip_y * sy + bh / 2.0
    hw = max(1, int(bw * 0.25))
    hh = max(1, int(bh * 0.25))
    return (int(cx - hw), int(cy - hh), int(cx + hw), int(cy + hh))


def bars_region(i, cap_w, cap_h, w=W, h=H):
    """Centre box of colour bar i (0..7) in captured coordinates."""
    sx = float(cap_w) / w
    sy = float(cap_h) / h
    bw = w / 8.0
    x0 = int((i * bw + bw * 0.25) * sx)
    x1 = int((i * bw + bw * 0.75) * sx)
    y0 = int((BARS_SPLIT_Y * 0.25) * sy)
    y1 = int((BARS_SPLIT_Y * 0.75) * sy)
    return (x0, y0, x1, y1)


def grey_region(i, cap_w, cap_h, w=W, h=H):
    sx = float(cap_w) / w
    sy = float(cap_h) / h
    bw = w / 8.0
    x0 = int((i * bw + bw * 0.25) * sx)
    x1 = int((i * bw + bw * 0.75) * sx)
    y0 = int((BARS_SPLIT_Y + (h - BARS_SPLIT_Y) * 0.25) * sy)
    y1 = int((BARS_SPLIT_Y + (h - BARS_SPLIT_Y) * 0.75) * sy)
    return (x0, y0, x1, y1)


def scale_box(box, cap_w, cap_h, w=W, h=H):
    x, y, bw, bh = box
    sx = float(cap_w) / w
    sy = float(cap_h) / h
    return (int(x * sx), int(y * sy), int((x + bw) * sx), int((y + bh) * sy))
