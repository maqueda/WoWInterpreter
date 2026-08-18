from PIL import Image, ImageDraw

from Bridge.kt08_protocol import encode_frame


LEVELS = (31, 92, 163, 224)


def render_kt08(payload="hello", sequence=1, x=12.0, y=24.0, pitch_x=4.0, pitch_y=4.0,
                size=(420, 350), mutate=None, pilots=True, anchor=True, anchor_gap=None):
    raw = bytearray(encode_frame(payload, sequence))
    if mutate is not None:
        mutate(raw)
    image = Image.new("RGB", size, (10, 12, 14))
    draw = ImageDraw.Draw(image)
    if anchor and pilots:
        gap = pitch_y if anchor_gap is None else anchor_gap
        grid_left = x - 2 * pitch_x
        grid_top = y - 2 * pitch_y
        anchor_bottom = grid_top - gap
        anchor_top = anchor_bottom - 2 * pitch_y
        anchor_colors = (
            (255, 0, 0), (0, 255, 0), (0, 0, 255),
            (255, 255, 0), (0, 255, 255), (255, 0, 255),
        )
        for index, color in enumerate(anchor_colors):
            draw.rectangle((
                round(grid_left + index * 2 * pitch_x), round(anchor_top),
                round(grid_left + (index + 1) * 2 * pitch_x) - 1,
                round(anchor_bottom) - 1,
            ), fill=color)
    if pilots:
        tl = (x - pitch_x, y - pitch_y)
        centers = (
            (tl[0], tl[1], (255, 0, 0)),
            (tl[0] + 34 * pitch_x, tl[1], (0, 255, 0)),
            (tl[0], tl[1] + 27 * pitch_y, (0, 0, 255)),
            (tl[0] + 34 * pitch_x, tl[1] + 27 * pitch_y, (255, 255, 0)),
        )
        for cx, cy, color in centers:
            draw.rectangle((
                round(cx - pitch_x), round(cy - pitch_y),
                round(cx + pitch_x) - 1, round(cy + pitch_y) - 1,
            ), fill=color)
    symbols = []
    for value in raw:
        symbols.extend(((value >> 6) & 3, (value >> 4) & 3, (value >> 2) & 3, value & 3))
    for index, symbol in enumerate(symbols):
        row, col = divmod(index, 32)
        left = round(x + col * pitch_x)
        right = round(x + (col + 1) * pitch_x) - 1
        top = round(y + row * pitch_y)
        bottom = round(y + (row + 1) * pitch_y) - 1
        value = LEVELS[symbol]
        draw.rectangle((left, top, right, bottom), fill=(value, value, value))
    return image
