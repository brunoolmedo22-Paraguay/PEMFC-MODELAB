"""Carga segura de imágenes de gráficos (PNG, JPEG, WebP) sin escribir en disco.

Reglas: solo formatos rasterizados identificados por su firma binaria (no por la
extensión); SVG y otros formatos con contenido activo se rechazan; límites de
tamaño en bytes y en píxeles (protección contra bombas de descompresión); toda
transformación aplicada a la imagen decodificada queda registrada.
"""
from __future__ import annotations

import base64
import hashlib
import io
import re
import warnings
from dataclasses import dataclass, field
from functools import cached_property

import numpy as np
from PIL import Image, ImageOps

MAX_BYTES = 10 * 1024 * 1024          # igual que server.maxUploadSize (10 MB)
MAX_PIXELS = 25_000_000               # 25 MP
MIN_SIDE_PX = 64                      # por debajo no hay información útil
LOW_RES_SIDE_PX = 300                 # aviso de baja resolución
DISPLAY_MAX_SIDE_PX = 2400            # copia de visualización para el navegador
FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
ACCEPTED_EXTENSIONS = ["png", "jpg", "jpeg", "webp"]


class ImageLoadError(ValueError):
    """Imagen rechazada o ilegible (mensaje accionable para el usuario)."""


def sniff_format(data: bytes) -> str | None:
    """Formato por firma binaria; None si no es PNG/JPEG/WebP."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def safe_filename(name: str, default: str = "imagen") -> str:
    """Nombre de archivo sin rutas ni caracteres problemáticos (para exportaciones)."""
    base = re.split(r"[\\/]", str(name or ""))[-1].strip()
    base = re.sub(r"[^\w.\-() ]+", "_", base, flags=re.UNICODE).strip(" .")
    return base[:120] or default


@dataclass
class LoadedImage:
    filename: str
    sha256: str
    format: str
    mime: str
    width: int
    height: int
    rgb: np.ndarray                      # uint8 (alto, ancho, 3): lo que analiza el detector y ve el usuario
    original_bytes: bytes = field(repr=False)
    transformations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def n_pixels(self) -> int:
        return self.width * self.height

    @cached_property
    def display(self) -> tuple[str, float]:
        """(data URL PNG, escala de visualización) de la imagen DECODIFICADA.

        Se envía la imagen decodificada (no los bytes originales) para que el
        navegador muestre exactamente los píxeles analizados (sin reorientación
        EXIF adicional). Si la imagen es muy grande se reduce SOLO la copia de
        visualización; el lienzo la dibuja en el espacio de píxeles original.
        """
        img = Image.fromarray(self.rgb)
        scale = 1.0
        side = max(self.width, self.height)
        if side > DISPLAY_MAX_SIDE_PX:
            scale = DISPLAY_MAX_SIDE_PX / side
            img = img.resize((max(1, round(self.width * scale)), max(1, round(self.height * scale))),
                             Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=False)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii"), scale

    def describe(self) -> dict:
        return {"filename": self.filename, "sha256": self.sha256, "format": self.format, "mime": self.mime,
                "width_px": self.width, "height_px": self.height, "bytes": len(self.original_bytes),
                "decoding_transformations": list(self.transformations), "warnings": list(self.warnings)}


def load_image(data: bytes, filename: str) -> LoadedImage:
    """Valida y decodifica una imagen. Lanza ImageLoadError con mensaje claro."""
    if not data:
        raise ImageLoadError("El archivo está vacío.")
    if len(data) > MAX_BYTES:
        raise ImageLoadError(f"La imagen ocupa {len(data) / 1e6:.1f} MB; el máximo admitido es "
                             f"{MAX_BYTES / 1024 / 1024:.0f} MB. Recorte o reduzca la imagen.")
    fmt = sniff_format(data)
    if fmt is None:
        head = data[:200].lstrip().lower()
        if head.startswith(b"<") or b"<svg" in head:
            raise ImageLoadError("SVG/HTML no admitido (puede contener contenido activo). "
                                 "Exporte el gráfico como PNG, JPEG o WebP.")
        raise ImageLoadError("El archivo no es una imagen PNG, JPEG o WebP válida (firma binaria no reconocida).")
    log: list[str] = []
    warns: list[str] = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            im = Image.open(io.BytesIO(data))
            if im.format != fmt:
                raise ImageLoadError(f"Formato declarado {im.format!r} distinto de la firma {fmt!r}.")
            w, h = im.size
            if w * h > MAX_PIXELS:
                raise ImageLoadError(f"La imagen tiene {w}×{h} = {w * h / 1e6:.1f} MP; el máximo es "
                                     f"{MAX_PIXELS / 1e6:.0f} MP.")
            if min(w, h) < MIN_SIDE_PX:
                raise ImageLoadError(f"Imagen demasiado pequeña ({w}×{h} px) para digitalizar con fiabilidad.")
            if getattr(im, "n_frames", 1) > 1:
                warns.append(f"Imagen animada/multipágina ({im.n_frames} fotogramas): se usa solo el primero.")
                log.append("Se usa el primer fotograma de una imagen animada.")
            im.load()
            orientation = im.getexif().get(0x0112, 1) if fmt in ("JPEG", "WEBP", "PNG") else 1
            if orientation not in (1, None):
                im = ImageOps.exif_transpose(im)
                log.append(f"Orientación EXIF {orientation} aplicada (rotación/espejo de la imagen).")
                warns.append("La imagen tenía orientación EXIF: se aplicó antes de analizar; las coordenadas "
                             "se refieren a la imagen reorientada.")
            mode = im.mode
            if mode in ("RGBA", "LA") or (mode == "P" and "transparency" in im.info):
                rgba = im.convert("RGBA")
                alpha = np.asarray(rgba)[..., 3]
                if (alpha < 255).any():
                    log.append("Transparencia compuesta sobre fondo blanco.")
                bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                im = Image.alpha_composite(bg, rgba).convert("RGB")
            elif mode != "RGB":
                log.append(f"Modo de color {mode} convertido a RGB.")
                im = im.convert("RGB")
            rgb = np.asarray(im, dtype=np.uint8).copy()
    except ImageLoadError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageLoadError(f"Imagen rechazada por tamaño excesivo de descompresión: {exc}") from exc
    except Exception as exc:  # Pillow lanza tipos diversos para archivos corruptos
        raise ImageLoadError(f"No se pudo decodificar la imagen (¿archivo corrupto o truncado?): {exc}") from exc
    h, w = rgb.shape[:2]
    if min(w, h) < LOW_RES_SIDE_PX:
        warns.append(f"Resolución baja ({w}×{h} px): la incertidumbre de digitalización será alta.")
    if fmt == "JPEG":
        warns.append("JPEG con compresión con pérdida: los bordes del trazo pueden tener artefactos.")
    return LoadedImage(filename=safe_filename(filename), sha256=hashlib.sha256(data).hexdigest(), format=fmt,
                       mime=FORMATS[fmt], width=int(w), height=int(h), rgb=rgb, original_bytes=bytes(data),
                       transformations=log, warnings=warns)
