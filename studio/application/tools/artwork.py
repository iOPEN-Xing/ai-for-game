import io
import math
import struct
import wave

from PIL import Image, ImageDraw

from studio.infra.art_files import png_bytes


def png(image):
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()


def sprite(art, asset_id=None):
    entities = art.get("sprites") or []
    if art.get("rendered"):
        selected = asset_id or entities[0]["id"]
        if selected in art["rendered"]:
            return png_bytes(art["rendered"][selected])
    if entities:
        entity = (
            next((item for item in entities if item["id"] == asset_id), None)
            if asset_id
            else entities[0]
        )
        if entity is None:
            raise KeyError("图形资源不存在")
        image = Image.new("RGBA", (336, 336))
        draw = ImageDraw.Draw(image)
        for layer in entity["layers"]:
            points = [
                (round(8 + x * 319), round(8 + y * 319)) for x, y in layer["points"]
            ]
            shape, color = layer["shape"], layer["color"]
            if shape in ("rect", "ellipse"):
                (x1, y1), (x2, y2) = points[:2]
                bounds = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
                if shape == "rect":
                    draw.rectangle(bounds, fill=color)
                else:
                    draw.ellipse(bounds, fill=color)
            elif shape == "polygon":
                draw.polygon(points, fill=color)
            else:
                draw.line(points, fill=color, width=12, joint="curve")
        return png(image.resize((112, 112), Image.Resampling.LANCZOS))
    im = Image.new("RGBA", (144, 144))
    d = ImageDraw.Draw(im)
    ink, accent = art["ink"], art["accent"]
    motif = art["motif"]
    if motif == "leaf":
        d.ellipse((27, 15, 121, 124), fill=accent, outline=ink, width=7)
        d.line((45, 119, 95, 43), fill=ink, width=8)
        d.line((78, 75, 55, 65), fill=ink, width=5)
    elif motif == "planet":
        d.ellipse((31, 29, 117, 115), fill=accent, outline=ink, width=7)
        d.arc((6, 51, 137, 97), 0, 360, fill=ink, width=8)
    elif motif == "crystal":
        d.polygon(
            [(72, 10), (127, 60), (91, 128), (49, 128), (16, 60)],
            fill=accent,
            outline=ink,
            width=7,
        )
        d.line([(72, 10), (52, 62), (72, 123), (93, 62), (72, 10)], fill=ink, width=5)
    else:
        d.rounded_rectangle((43, 63, 100, 125), 8, fill=accent, outline=ink, width=7)
        d.ellipse((48, 31, 96, 78), fill=accent, outline=ink, width=7)
        for box in [(31, 16, 113, 98), (17, 2, 127, 112)]:
            d.arc(box, 211, 330, fill=ink, width=5)
    return png(im.resize((112, 112), Image.Resampling.LANCZOS))


def sound(art, event):
    root, tempo = art["root_hz"], art["tempo"]
    notes = {
        "hit": [1, 1.5],
        "miss": [0.8, 0.55],
        "win": [1, 1.25, 1.5, 2],
        "ui": [1.25],
        "bgm": [1, 1.5, 1.25, 1.5, 0.75, 1.125, 1.25, 1.5],
    }[event]
    if art.get("melody", {}).get(event):
        notes = [2 ** (semitones / 12) for semitones in art["melody"][event]]
    step = 60 / tempo / (2 if event == "bgm" else 5)
    rate = 11025
    frames = bytearray()
    for note in notes:
        for i in range(int(step * rate)):
            t = i / rate
            envelope = min(1, t / 0.012) * max(0, 1 - t / step) ** 1.4
            signal = math.sin(2 * math.pi * root * note * t) + 0.15 * math.sin(
                4 * math.pi * root * note * t
            )
            frames.extend(struct.pack("<h", int(5200 * signal * envelope)))
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        w.writeframes(frames)
    return out.getvalue()
