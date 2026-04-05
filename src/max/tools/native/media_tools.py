"""Media tools — image manipulation, audio transcription, video metadata.

Supports image resize/convert/info via Pillow, audio transcription via
openai-whisper, and video metadata via ffmpeg-python. All tools degrade
gracefully when optional dependencies are not installed.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from max.tools.registry import ToolDefinition

# ── Graceful imports ─────────────────────────────────────────────────

try:
    from PIL import Image

    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

try:
    import whisper  # type: ignore[import-untyped]

    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

try:
    import ffmpeg  # type: ignore[import-untyped]

    HAS_FFMPEG = True
except ImportError:
    HAS_FFMPEG = False

# ── Tool definitions ─────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="media.image_resize",
        category="media",
        description="Resize an image to the given width and height.",
        permissions=["fs.read", "fs.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the source image"},
                "width": {"type": "integer", "description": "Target width in pixels"},
                "height": {"type": "integer", "description": "Target height in pixels"},
                "output_path": {
                    "type": "string",
                    "description": "Output path (optional, overwrites source if omitted)",
                },
            },
            "required": ["path", "width", "height"],
        },
    ),
    ToolDefinition(
        tool_id="media.image_convert",
        category="media",
        description="Convert an image to a different format (auto-detects from extension).",
        permissions=["fs.read", "fs.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the source image"},
                "output_path": {
                    "type": "string",
                    "description": "Output path with desired extension (e.g. .jpg, .png, .webp)",
                },
                "format": {
                    "type": "string",
                    "description": "Format override (JPEG, PNG, WEBP). Auto-detected if omitted.",
                },
            },
            "required": ["path", "output_path"],
        },
    ),
    ToolDefinition(
        tool_id="media.image_info",
        category="media",
        description="Get image metadata: dimensions, format, mode, and file size.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the image file"},
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        tool_id="media.audio_transcribe",
        category="media",
        description="Transcribe audio to text using OpenAI Whisper (CPU-bound).",
        permissions=["fs.read"],
        provider_id="native",
        cost_tier="high",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the audio file"},
                "model": {
                    "type": "string",
                    "description": "Whisper model size (tiny, base, small, medium, large)",
                    "default": "base",
                },
                "language": {
                    "type": "string",
                    "description": "Language code (e.g. en, es, fr). Auto-detected if omitted.",
                },
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        tool_id="media.video_info",
        category="media",
        description="Get video metadata: duration, dimensions, codec, format, and file size.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the video file"},
            },
            "required": ["path"],
        },
    ),
]

# ── Error helpers ────────────────────────────────────────────────────


def _no_pillow_error() -> dict[str, Any]:
    return {"error": "Pillow not installed. Run: pip install Pillow"}


def _no_whisper_error() -> dict[str, Any]:
    return {"error": "openai-whisper not installed. Run: pip install openai-whisper"}


def _no_ffmpeg_error() -> dict[str, Any]:
    return {"error": "ffmpeg-python not installed. Run: pip install ffmpeg-python"}


# ── Format mapping ───────────────────────────────────────────────────

_EXT_TO_FORMAT: dict[str, str] = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".gif": "GIF",
    ".bmp": "BMP",
    ".tiff": "TIFF",
    ".tif": "TIFF",
    ".ico": "ICO",
}

# ── Handlers ─────────────────────────────────────────────────────────


async def handle_media_image_resize(inputs: dict[str, Any]) -> dict[str, Any]:
    """Resize an image to the given dimensions."""
    if not HAS_PILLOW:
        return _no_pillow_error()

    path = inputs["path"]
    width = inputs["width"]
    height = inputs["height"]
    output_path = inputs.get("output_path", path)

    def _resize() -> dict[str, Any]:
        img = Image.open(path)
        resized = img.resize((width, height))
        resized.save(output_path)
        return {"path": output_path, "width": width, "height": height}

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _resize)
    except FileNotFoundError:
        return {"error": f"File not found: {path}"}
    except Exception as exc:
        return {"error": f"Image resize failed: {exc}"}


async def handle_media_image_convert(inputs: dict[str, Any]) -> dict[str, Any]:
    """Convert an image to a different format."""
    if not HAS_PILLOW:
        return _no_pillow_error()

    path = inputs["path"]
    output_path = inputs["output_path"]
    fmt = inputs.get("format")

    # Auto-detect format from extension if not explicitly provided
    if not fmt:
        ext = os.path.splitext(output_path)[1].lower()
        fmt = _EXT_TO_FORMAT.get(ext)
        if not fmt:
            return {"error": f"Cannot determine format from extension: {ext}"}

    final_fmt = fmt

    def _convert() -> dict[str, Any]:
        img = Image.open(path)
        # Convert RGBA to RGB for formats that don't support alpha
        if final_fmt in ("JPEG", "BMP") and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(output_path, format=final_fmt)
        return {"path": output_path, "format": final_fmt}

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _convert)
    except FileNotFoundError:
        return {"error": f"File not found: {path}"}
    except Exception as exc:
        return {"error": f"Image conversion failed: {exc}"}


async def handle_media_image_info(inputs: dict[str, Any]) -> dict[str, Any]:
    """Get image metadata."""
    if not HAS_PILLOW:
        return _no_pillow_error()

    path = inputs["path"]

    def _info() -> dict[str, Any]:
        size_bytes = os.path.getsize(path)
        img = Image.open(path)
        # Access .size to get dimensions, .format and .mode for metadata
        width, height = img.size
        return {
            "width": width,
            "height": height,
            "format": img.format,
            "mode": img.mode,
            "size_bytes": size_bytes,
        }

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _info)
    except FileNotFoundError:
        return {"error": f"File not found: {path}"}
    except Exception as exc:
        return {"error": f"Image info failed: {exc}"}


async def handle_media_audio_transcribe(inputs: dict[str, Any]) -> dict[str, Any]:
    """Transcribe audio to text using Whisper. Runs in thread executor (CPU-bound)."""
    if not HAS_WHISPER:
        return _no_whisper_error()

    path = inputs["path"]
    model_name = inputs.get("model", "base")
    language = inputs.get("language")

    if not os.path.isfile(path):
        return {"error": f"File not found: {path}"}

    def _sync_transcribe() -> dict[str, Any]:
        model = whisper.load_model(model_name)
        options: dict[str, Any] = {}
        if language:
            options["language"] = language
        result = model.transcribe(path, **options)
        return {
            "text": result.get("text", ""),
            "language": result.get("language", ""),
            "duration": result.get("duration", 0.0),
        }

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync_transcribe)
    except Exception as exc:
        return {"error": f"Audio transcription failed: {exc}"}


async def handle_media_video_info(inputs: dict[str, Any]) -> dict[str, Any]:
    """Get video metadata using ffmpeg.probe."""
    if not HAS_FFMPEG:
        return _no_ffmpeg_error()

    path = inputs["path"]

    if not os.path.isfile(path):
        return {"error": f"File not found: {path}"}

    def _probe() -> dict[str, Any]:
        probe = ffmpeg.probe(path)

        # Find the first video stream
        video_stream = None
        for stream in probe.get("streams", []):
            if stream.get("codec_type") == "video":
                video_stream = stream
                break

        fmt_info = probe.get("format", {})
        size_bytes = int(fmt_info.get("size", 0))
        duration = float(fmt_info.get("duration", 0.0))
        format_name = fmt_info.get("format_name", "")

        result: dict[str, Any] = {
            "duration": duration,
            "format": format_name,
            "size_bytes": size_bytes,
        }

        if video_stream:
            result["width"] = int(video_stream.get("width", 0))
            result["height"] = int(video_stream.get("height", 0))
            result["codec"] = video_stream.get("codec_name", "")
        else:
            result["width"] = 0
            result["height"] = 0
            result["codec"] = ""

        return result

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _probe)
    except Exception as exc:
        return {"error": f"Video info failed: {exc}"}
