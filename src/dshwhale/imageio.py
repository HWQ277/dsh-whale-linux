"""Minimal PNG and GIF decoding on top of the standard library.

The widget needs three things from its image assets:

1. the whale sprite's **alpha channel**, to build the X11 window silhouette;
2. RGB pixels **flattened onto the window background colour**, so the rectangle
   outside the silhouette is invisible even when the X server refuses to apply a
   shape mask;
3. animated GIF playback for the "rua" pet-pet bubble.

Doing this with ``zlib`` + ``struct`` keeps the package dependency-free, which
matters for an AUR package that should install on a bare Arch system.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ImageError(Exception):
    """Raised when an image cannot be decoded."""


@dataclass
class Image:
    """A decoded RGBA image."""

    width: int
    height: int
    pixels: bytearray  # RGBA, row-major, len == width*height*4

    def alpha_at(self, x: int, y: int) -> int:
        return self.pixels[(y * self.width + x) * 4 + 3]

    def rgba_at(self, x: int, y: int) -> tuple[int, int, int, int]:
        off = (y * self.width + x) * 4
        return tuple(self.pixels[off : off + 4])  # type: ignore[return-value]


@dataclass
class Animation:
    """A sequence of frames plus per-frame delays in milliseconds."""

    frames: list[Image] = field(default_factory=list)
    delays: list[int] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.frames)


# ---------------------------------------------------------------------------
# PNG
# ---------------------------------------------------------------------------
def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter(raw: bytes, width: int, height: int, bpp: int, stride: int) -> bytearray:
    out = bytearray(height * stride)
    pos = 0
    prev = bytearray(stride)
    for row in range(height):
        if pos >= len(raw):
            raise ImageError("PNG 数据不完整")
        filter_type = raw[pos]
        pos += 1
        line = bytearray(raw[pos : pos + stride])
        if len(line) != stride:
            raise ImageError("PNG 行数据不完整")
        pos += stride

        if filter_type == 0:
            pass
        elif filter_type == 1:  # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                upleft = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], upleft)) & 0xFF
        else:
            raise ImageError(f"未知 PNG 过滤器 {filter_type}")

        out[row * stride : (row + 1) * stride] = line
        prev = line
    return out


def decode_png(data: bytes) -> Image:
    """Decode a PNG into RGBA (8-bit, non-interlaced, palette/gray/RGB/alpha)."""
    if data[:8] != PNG_SIGNATURE:
        raise ImageError("不是 PNG 文件")

    pos = 8
    width = height = depth = colour = interlace = 0
    palette = b""
    transparency = b""
    idat = bytearray()

    while pos + 8 <= len(data):
        length, chunk_type = struct.unpack(">I4s", data[pos : pos + 8])
        pos += 8
        chunk = data[pos : pos + length]
        pos += length + 4  # skip CRC
        if chunk_type == b"IHDR":
            width, height, depth, colour, _comp, _filt, interlace = struct.unpack(">IIBBBBB", chunk)
        elif chunk_type == b"PLTE":
            palette = chunk
        elif chunk_type == b"tRNS":
            transparency = chunk
        elif chunk_type == b"IDAT":
            idat += chunk
        elif chunk_type == b"IEND":
            break

    if width <= 0 or height <= 0:
        raise ImageError("PNG 缺少 IHDR")
    if depth != 8:
        raise ImageError(f"仅支持 8-bit PNG（当前 {depth}-bit）")
    if interlace:
        raise ImageError("不支持隔行 PNG")

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colour)
    if channels is None:
        raise ImageError(f"不支持的 PNG 颜色类型 {colour}")

    stride = width * channels
    raw = zlib.decompress(bytes(idat))
    flat = _unfilter(raw, width, height, channels, stride)

    out = bytearray(width * height * 4)
    for y in range(height):
        row = y * stride
        dst = y * width * 4
        for x in range(width):
            src = row + x * channels
            o = dst + x * 4
            if colour == 6:  # RGBA
                out[o : o + 4] = flat[src : src + 4]
            elif colour == 2:  # RGB
                out[o : o + 3] = flat[src : src + 3]
                out[o + 3] = 255
            elif colour == 0:  # grayscale
                v = flat[src]
                out[o] = out[o + 1] = out[o + 2] = v
                out[o + 3] = 255
            elif colour == 4:  # gray + alpha
                v = flat[src]
                out[o] = out[o + 1] = out[o + 2] = v
                out[o + 3] = flat[src + 1]
            else:  # palette
                index = flat[src]
                if palette:
                    out[o : o + 3] = palette[index * 3 : index * 3 + 3]
                out[o + 3] = transparency[index] if index < len(transparency) else 255
    return Image(width, height, out)


# ---------------------------------------------------------------------------
# GIF
# ---------------------------------------------------------------------------
def decode_gif(data: bytes) -> Animation:
    """Decode a GIF87a/GIF89a file into frames with delays."""
    if data[:6] not in (b"GIF87a", b"GIF89a"):
        raise ImageError("不是 GIF 文件")

    width, height, flags, _bg, _aspect = struct.unpack("<HHBBB", data[6:13])
    pos = 13

    global_palette = b""
    if flags & 0x80:
        size = 2 << (flags & 0x07)
        global_palette = data[pos : pos + size * 3]
        pos += size * 3

    canvas = bytearray(width * height * 4)
    frames: list[Image] = []
    delays: list[int] = []
    transparent_index: int | None = None
    delay = 100
    disposal = 0
    saved: bytearray | None = None

    def read_sub_blocks(start: int) -> tuple[bytes, int]:
        chunks = bytearray()
        while start < len(data):
            size = data[start]
            start += 1
            if size == 0:
                break
            chunks += data[start : start + size]
            start += size
        return bytes(chunks), start

    while pos < len(data):
        marker = data[pos]
        pos += 1

        if marker == 0x21:  # extension
            if pos >= len(data):
                break
            label = data[pos]
            pos += 1
            if label == 0xF9:  # graphics control
                block_size = data[pos]
                block = data[pos + 1 : pos + 1 + block_size]
                pos += 1 + block_size
                if len(block) >= 4:
                    packed = block[0]
                    delay = struct.unpack("<H", block[1:3])[0] * 10
                    transparent_index = block[3] if packed & 0x01 else None
                    disposal = (packed >> 2) & 0x07
                pos += 1  # block terminator
            else:
                _, pos = read_sub_blocks(pos)

        elif marker == 0x2C:  # image descriptor
            left, top, iw, ih, lflags = struct.unpack("<HHHHB", data[pos : pos + 9])
            pos += 9
            palette = global_palette
            if lflags & 0x80:
                size = 2 << (lflags & 0x07)
                palette = data[pos : pos + size * 3]
                pos += size * 3
            interlaced = bool(lflags & 0x40)
            min_code = data[pos]
            pos += 1
            payload, pos = read_sub_blocks(pos)

            if disposal == 3 and saved is None:
                saved = bytearray(canvas)

            indices = _gif_lzw(payload, min_code, iw * ih)
            if interlaced:
                indices = _deinterlace(indices, iw, ih)

            for row in range(ih):
                y = top + row
                if y >= height:
                    break
                for col in range(iw):
                    x = left + col
                    if x >= width:
                        break
                    index = indices[row * iw + col]
                    if transparent_index is not None and index == transparent_index:
                        continue
                    o = (y * width + x) * 4
                    if palette:
                        canvas[o : o + 3] = palette[index * 3 : index * 3 + 3]
                    canvas[o + 3] = 255

            frames.append(Image(width, height, bytearray(canvas)))
            delays.append(delay or 100)

            if disposal == 2:  # restore to background
                for row in range(ih):
                    y = top + row
                    if y >= height:
                        break
                    for col in range(iw):
                        x = left + col
                        if x >= width:
                            break
                        o = (y * width + x) * 4
                        canvas[o : o + 4] = b"\x00\x00\x00\x00"
            elif disposal == 3 and saved is not None:  # restore to previous
                canvas = bytearray(saved)
            if disposal != 3:
                saved = None

        elif marker == 0x3B:  # trailer
            break

    if not frames:
        raise ImageError("GIF 没有帧")
    return Animation(frames, delays)


def _deinterlace(indices: list[int], width: int, height: int) -> list[int]:
    out = [0] * (width * height)
    rows = list(range(0, height, 8)) + list(range(4, height, 8)) + \
        list(range(2, height, 4)) + list(range(1, height, 2))
    for dst_row, src_row in enumerate(rows):
        if src_row >= height:
            continue
        out[dst_row * width : (dst_row + 1) * width] = \
            indices[src_row * width : (src_row + 1) * width]
    return out


def _gif_lzw(payload: bytes, min_code_size: int, expected: int) -> list[int]:
    """Decode GIF LZW into a list of palette indices."""
    clear = 1 << min_code_size
    end = clear + 1
    code_size = min_code_size + 1
    table: list[list[int]] = [[i] for i in range(clear)] + [[], []]
    out: list[int] = []
    bit_buffer = 0
    bit_count = 0
    prev: list[int] | None = None

    for byte in payload:
        bit_buffer |= byte << bit_count
        bit_count += 8
        while bit_count >= code_size:
            code = bit_buffer & ((1 << code_size) - 1)
            bit_buffer >>= code_size
            bit_count -= code_size

            if code == clear:
                table = [[i] for i in range(clear)] + [[], []]
                code_size = min_code_size + 1
                prev = None
                continue
            if code == end:
                return out

            if code < len(table):
                entry = table[code]
            elif prev is not None:
                entry = prev + [prev[0]]
            else:
                return out

            out += entry
            if prev is not None:
                table.append(prev + [entry[0]])
                if len(table) == (1 << code_size) and code_size < 12:
                    code_size += 1
            prev = entry
            if len(out) >= expected:
                return out[:expected]
    return out[:expected]


# ---------------------------------------------------------------------------
# Tk-facing helpers
# ---------------------------------------------------------------------------
def flatten_on(image: Image, background: tuple[int, int, int]) -> bytes:
    """Composite an RGBA image onto a solid colour, returning RGB bytes.

    Tk's ``PhotoImage`` cannot show partial alpha, so anything that is not fully
    transparent would otherwise pick up a black or white halo. Blending onto the
    known window background makes the sprite edges look clean.
    """
    br, bg, bb = background
    out = bytearray(image.width * image.height * 3)
    px = image.pixels
    for i in range(image.width * image.height):
        o = i * 4
        a = px[o + 3]
        if a == 255:
            out[i * 3] = px[o]
            out[i * 3 + 1] = px[o + 1]
            out[i * 3 + 2] = px[o + 2]
        elif a == 0:
            out[i * 3] = br
            out[i * 3 + 1] = bg
            out[i * 3 + 2] = bb
        else:
            inv = 255 - a
            out[i * 3] = (px[o] * a + br * inv) // 255
            out[i * 3 + 1] = (px[o + 1] * a + bg * inv) // 255
            out[i * 3 + 2] = (px[o + 2] * a + bb * inv) // 255
    return bytes(out)


def scale_nearest(image: Image, width: int, height: int) -> Image:
    """Nearest-neighbour scale (fast enough for widget-sized sprites)."""
    if width == image.width and height == image.height:
        return image
    out = bytearray(width * height * 4)
    src = image.pixels
    sw, sh = image.width, image.height
    for y in range(height):
        sy = min(sh - 1, y * sh // height)
        srow = sy * sw * 4
        drow = y * width * 4
        for x in range(width):
            sx = min(sw - 1, x * sw // width)
            so = srow + sx * 4
            do = drow + x * 4
            out[do : do + 4] = src[so : so + 4]
    return Image(width, height, out)


def load_image(path: str) -> Image:
    with open(path, "rb") as handle:
        return decode_png(handle.read())


def load_animation(path: str) -> Animation:
    with open(path, "rb") as handle:
        return decode_gif(handle.read())
