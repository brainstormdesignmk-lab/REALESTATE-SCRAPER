# _shared/media.py
# Deal-close image pipeline (scraper images -> hosted, unbranded, fast).
#
# Design (agreed with the operator):
#   - Scrape time stores only image URLs (cheap).
#   - On deal close, `scrape_images.py` downloads the originals, crops the
#     Reklama5 watermark off the top, resizes for the web, and writes
#     JPEG + WebP into a per-property folder on the T60 disk. The Lovable app
#     points at those files (served from the T60 via a Cloudflare tunnel).
#
# Nothing here talks to Supabase: hosting is the operator's job. This module
# only produces files + a manifest.json that the app can reference.

from __future__ import annotations

import io
import json
import os
import re
from typing import Iterable, Optional

DEFAULT_MAX_WIDTH = 1600
DEFAULT_QUALITY = 82

# Reklama5 stamps the same watermark logo into the top-left corner of every
# uploaded photo (it sits at y≈12..31 px on the standard uploads and is a fixed
# pixel size, independent of the image width). Auto-detecting it was unreliable
# across heterogeneous uploads, so the crop is now a constant: strip the top
# strip that always contains the watermark. Measured from the live
# `photos/xbig/*.jpg` files (2026-10); 36 px clears the watermark with a small
# safety margin. Override per run with `--crop-top-px`, disable with `--no-crop`.
REKLAMA5_LOGO_CROP_TOP_PX = 36


def images_root(variant_dir: Optional[str] = None) -> str:
    """Where processed images are written. Override with METROPOLIS_IMAGES_DIR."""
    env = os.environ.get("METROPOLIS_IMAGES_DIR")
    if env:
        return env
    base = variant_dir or os.getcwd()
    return os.path.join(base, "output", "images")


def fetch_bytes(url: str, session=None, timeout: float = 30.0) -> bytes:
    """Download a binary resource through the shared Scrapling client."""
    if session is not None:
        resp = session.get(url)
    else:
        from scrapling_fetch import http_get
        resp = http_get(url, timeout=timeout)
    data = getattr(resp, "body", None)
    if data:
        return data
    for attr in ("content", "body"):
        value = getattr(resp, attr, None)
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
    raise RuntimeError(f"could not read bytes from {url}")




def process_image(data: bytes, crop_top: int = 0,
                  max_width: int = DEFAULT_MAX_WIDTH,
                  quality: int = DEFAULT_QUALITY,
                  want_webp: bool = True) -> dict:
    """Crop/resize/encode one image.

    Returns a dict with the encoded `jpeg`, optional `webp`, and metadata.
    """
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    original_size = img.size

    cropped = 0
    if crop_top and 0 < crop_top < img.height - 20:
        img = img.crop((0, crop_top, img.width, img.height))
        cropped = crop_top

    if img.width > max_width:
        ratio = max_width / float(img.width)
        img = img.resize((max_width, max(1, int(img.height * ratio))), Image.LANCZOS)

    jpeg_buf = io.BytesIO()
    img.save(jpeg_buf, "JPEG", quality=quality, optimize=True, progressive=True)

    webp_buf = None
    if want_webp:
        try:
            webp_buf = io.BytesIO()
            img.save(webp_buf, "WEBP", quality=quality, method=4)
        except Exception:
            webp_buf = None

    return {
        "jpeg": jpeg_buf.getvalue(),
        "webp": webp_buf.getvalue() if webp_buf is not None else None,
        "original_width": original_size[0],
        "original_height": original_size[1],
        "width": img.width,
        "height": img.height,
        "cropped_top": cropped,
    }


def property_key(site: str, ad_id: str, property_number: Optional[str] = None) -> str:
    """Folder name for a property: its number when known, else site-adid."""
    if property_number:
        safe = re.sub(r"[^A-Za-z0-9_\-]", "_", str(property_number))
        return safe
    safe_site = re.sub(r"[^A-Za-z0-9_\-]", "_", str(site))
    safe_id = re.sub(r"[^A-Za-z0-9_\-]", "_", str(ad_id))
    return f"{safe_site}-{safe_id}"


def process_property(site: str, ad_id: str, image_urls: Iterable[str],
                     out_root: Optional[str] = None,
                     property_number: Optional[str] = None,
                     session=None,
                     crop_logo: bool = False,
                     crop_top_px: Optional[int] = None,
                     max_width: int = DEFAULT_MAX_WIDTH,
                     quality: int = DEFAULT_QUALITY,
                     want_webp: bool = True,
                     limit: int = 40) -> dict:
    """Download + process every image of one ad into a per-property folder.

    `crop_logo` applies the fixed Reklama5 watermark crop
    (`REKLAMA5_LOGO_CROP_TOP_PX`); `crop_top_px` overrides it with an explicit
    value. Returns a manifest dict.
    """
    out_root = out_root or images_root()
    key = property_key(site, ad_id, property_number)
    dest = os.path.join(out_root, key)
    os.makedirs(dest, exist_ok=True)

    entries = []
    errors = []
    for index, url in enumerate(list(image_urls)[:limit], start=1):
        try:
            data = fetch_bytes(url, session=session)
            if crop_top_px is not None:
                crop, crop_mode = max(0, int(crop_top_px)), "explicit"
            elif crop_logo:
                crop, crop_mode = REKLAMA5_LOGO_CROP_TOP_PX, "reklama5-fixed"
            else:
                crop, crop_mode = 0, "none"
            processed = process_image(data, crop_top=crop, max_width=max_width,
                                      quality=quality, want_webp=want_webp)

            jpg_name = f"{index:02d}.jpg"
            with open(os.path.join(dest, jpg_name), "wb") as fh:
                fh.write(processed["jpeg"])
            files = [jpg_name]

            webp_name = None
            if processed["webp"]:
                webp_name = f"{index:02d}.webp"
                with open(os.path.join(dest, webp_name), "wb") as fh:
                    fh.write(processed["webp"])
                files.append(webp_name)

            entries.append({
                "order": index,
                "source_url": url,
                "files": files,
                "jpeg": jpg_name,
                "webp": webp_name,
                "width": processed["width"],
                "height": processed["height"],
                "cropped_top": processed["cropped_top"],
                "crop_mode": crop_mode,
            })
        except Exception as exc:  # one bad image must not kill the batch
            errors.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})

    manifest = {
        "site": site,
        "ad_id": ad_id,
        "property_number": property_number,
        "key": key,
        "dir": dest,
        "count": len(entries),
        "images": entries,
        "errors": errors,
    }
    with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    return manifest


def write_preview(urls: Iterable[str], out_path: str, session=None,
                  max_width: int = 420, per_row: int = 4,
                  crop_top_px: int = REKLAMA5_LOGO_CROP_TOP_PX) -> str:
    """Build a contact sheet with a red line at the fixed crop mark.

    Used to visually confirm the Reklama5 watermark crop. Returns the path.
    """
    from PIL import Image, ImageDraw

    thumbs = []
    for url in list(urls)[:16]:
        try:
            data = fetch_bytes(url, session=session)
            img = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            continue
        ratio = max_width / float(img.width)
        thumb = img.resize((max_width, max(1, int(img.height * ratio))), Image.LANCZOS)
        draw = ImageDraw.Draw(thumb)
        y = int(crop_top_px * ratio)
        draw.line([(0, y), (thumb.width, y)], fill=(255, 0, 0), width=3)
        label = f"fixed crop y={crop_top_px}px"
        draw.rectangle([(0, thumb.height - 16), (thumb.width, thumb.height)], fill=(0, 0, 0))
        draw.text((4, thumb.height - 13), label, fill=(255, 255, 255))
        thumbs.append(thumb)

    if not thumbs:
        raise RuntimeError("no images could be downloaded for the preview")

    cols = max(1, per_row)
    rows = (len(thumbs) + cols - 1) // cols
    cell_w = max_width
    cell_h = max(t.height for t in thumbs)
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), (255, 255, 255))
    for i, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((i % cols) * cell_w, (i // cols) * cell_h))

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    sheet.save(out_path, "JPEG", quality=85)
    return out_path
