"""Canonical photo normalization and location validation shared by app and experiment."""
import io
from PIL import Image, ImageOps

def prepare_image(path, max_edge=1600):
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        if image.mode in ("RGBA", "LA") or "transparency" in image.info:
            rgba = image.convert("RGBA")
            image = Image.new("RGB", rgba.size, "white")
            image.paste(rgba, mask=rgba.getchannel("A"))
        else:
            image = image.convert("RGB")
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=92)
    data = buffer.getvalue()
    # Render the exact encoded image submitted to the model, with metadata stripped.
    return Image.open(io.BytesIO(data)).convert("RGB"), data


def validate_box(box):
    if not isinstance(box, list) or len(box) != 4:
        raise ValueError("A box must have exactly four coordinates.")
    if any(type(v) is not int or not 0 <= v <= 1000 for v in box):
        raise ValueError("Coordinates must be integers in 0..1000.")
    if box[0] >= box[2] or box[1] >= box[3]:
        raise ValueError("Box edges must have positive width and height.")


def pixel_box(box, size):
    validate_box(box)
    width, height = size
    return tuple(min(bound - 1, max(0, round(value * bound / 1000)))
                 for value, bound in zip(box, (width, height, width, height)))

