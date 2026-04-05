"""Tests for media tools — image, audio, video."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from max.tools.native.media_tools import (
    TOOL_DEFINITIONS,
    handle_media_audio_transcribe,
    handle_media_image_convert,
    handle_media_image_info,
    handle_media_image_resize,
    handle_media_video_info,
)


# ── Tool definition tests ───────────────────────────────────────────


class TestToolDefinitions:
    def test_has_five_definitions(self):
        assert len(TOOL_DEFINITIONS) == 5

    def test_all_category_media(self):
        for td in TOOL_DEFINITIONS:
            assert td.category == "media", f"{td.tool_id} has category {td.category}"

    def test_all_provider_native(self):
        for td in TOOL_DEFINITIONS:
            assert td.provider_id == "native", f"{td.tool_id} has provider {td.provider_id}"

    def test_tool_ids(self):
        ids = {td.tool_id for td in TOOL_DEFINITIONS}
        expected = {
            "media.image_resize",
            "media.image_convert",
            "media.image_info",
            "media.audio_transcribe",
            "media.video_info",
        }
        assert ids == expected

    def test_all_have_input_schemas(self):
        for td in TOOL_DEFINITIONS:
            assert td.input_schema["type"] == "object"
            assert "properties" in td.input_schema

    def test_audio_transcribe_high_cost_tier(self):
        td = next(t for t in TOOL_DEFINITIONS if t.tool_id == "media.audio_transcribe")
        assert td.cost_tier == "high"


# ── Image resize tests ──────────────────────────────────────────────


class TestImageResize:
    @pytest.mark.asyncio
    async def test_resize_with_pillow(self, tmp_path):
        """Use real Pillow to create and resize a tiny image."""
        from PIL import Image

        src = tmp_path / "input.png"
        Image.new("RGB", (10, 10), "red").save(str(src))

        result = await handle_media_image_resize({
            "path": str(src),
            "width": 5,
            "height": 5,
        })

        assert result["width"] == 5
        assert result["height"] == 5
        assert result["path"] == str(src)

        # Verify the file was actually resized
        img = Image.open(str(src))
        assert img.size == (5, 5)

    @pytest.mark.asyncio
    async def test_resize_with_output_path(self, tmp_path):
        """Resize to a separate output path."""
        from PIL import Image

        src = tmp_path / "input.png"
        out = tmp_path / "output.png"
        Image.new("RGB", (20, 20), "blue").save(str(src))

        result = await handle_media_image_resize({
            "path": str(src),
            "width": 8,
            "height": 8,
            "output_path": str(out),
        })

        assert result["path"] == str(out)
        assert result["width"] == 8
        assert result["height"] == 8
        assert out.exists()

        # Original should remain unchanged
        orig = Image.open(str(src))
        assert orig.size == (20, 20)

    @pytest.mark.asyncio
    async def test_resize_file_not_found(self):
        result = await handle_media_image_resize({
            "path": "/nonexistent/image.png",
            "width": 10,
            "height": 10,
        })
        assert "error" in result
        assert "not found" in result["error"].lower() or "No such file" in result["error"]

    @pytest.mark.asyncio
    async def test_resize_no_pillow(self):
        with patch("max.tools.native.media_tools.HAS_PILLOW", False):
            result = await handle_media_image_resize({
                "path": "/any/path.png",
                "width": 10,
                "height": 10,
            })
            assert "error" in result
            assert "Pillow" in result["error"]


# ── Image convert tests ─────────────────────────────────────────────


class TestImageConvert:
    @pytest.mark.asyncio
    async def test_convert_png_to_jpeg(self, tmp_path):
        """Convert PNG to JPEG using real Pillow."""
        from PIL import Image

        src = tmp_path / "input.png"
        out = tmp_path / "output.jpg"
        Image.new("RGB", (10, 10), "green").save(str(src))

        result = await handle_media_image_convert({
            "path": str(src),
            "output_path": str(out),
        })

        assert result["path"] == str(out)
        assert result["format"] == "JPEG"
        assert out.exists()

    @pytest.mark.asyncio
    async def test_convert_with_explicit_format(self, tmp_path):
        """Convert with explicitly specified format."""
        from PIL import Image

        src = tmp_path / "input.png"
        out = tmp_path / "output.img"
        Image.new("RGB", (10, 10), "yellow").save(str(src))

        result = await handle_media_image_convert({
            "path": str(src),
            "output_path": str(out),
            "format": "BMP",
        })

        assert result["format"] == "BMP"
        assert out.exists()

    @pytest.mark.asyncio
    async def test_convert_rgba_to_jpeg(self, tmp_path):
        """RGBA images should be auto-converted to RGB for JPEG."""
        from PIL import Image

        src = tmp_path / "rgba.png"
        out = tmp_path / "output.jpg"
        Image.new("RGBA", (10, 10), (255, 0, 0, 128)).save(str(src))

        result = await handle_media_image_convert({
            "path": str(src),
            "output_path": str(out),
        })

        assert result["format"] == "JPEG"
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_convert_unknown_extension(self, tmp_path):
        """Unknown extension without explicit format should error."""
        from PIL import Image

        src = tmp_path / "input.png"
        out = tmp_path / "output.xyz"
        Image.new("RGB", (10, 10), "red").save(str(src))

        result = await handle_media_image_convert({
            "path": str(src),
            "output_path": str(out),
        })

        assert "error" in result
        assert "extension" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_convert_file_not_found(self):
        result = await handle_media_image_convert({
            "path": "/nonexistent/image.png",
            "output_path": "/tmp/output.jpg",
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_convert_no_pillow(self):
        with patch("max.tools.native.media_tools.HAS_PILLOW", False):
            result = await handle_media_image_convert({
                "path": "/any/path.png",
                "output_path": "/tmp/out.jpg",
            })
            assert "error" in result
            assert "Pillow" in result["error"]


# ── Image info tests ────────────────────────────────────────────────


class TestImageInfo:
    @pytest.mark.asyncio
    async def test_info_real_image(self, tmp_path):
        """Get metadata from a real image."""
        from PIL import Image

        src = tmp_path / "test.png"
        Image.new("RGB", (42, 17), "purple").save(str(src))

        result = await handle_media_image_info({"path": str(src)})

        assert result["width"] == 42
        assert result["height"] == 17
        assert result["format"] == "PNG"
        assert result["mode"] == "RGB"
        assert result["size_bytes"] > 0

    @pytest.mark.asyncio
    async def test_info_rgba_image(self, tmp_path):
        """RGBA image should report correct mode."""
        from PIL import Image

        src = tmp_path / "rgba.png"
        Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(str(src))

        result = await handle_media_image_info({"path": str(src)})

        assert result["mode"] == "RGBA"

    @pytest.mark.asyncio
    async def test_info_file_not_found(self):
        result = await handle_media_image_info({"path": "/nonexistent/image.png"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_info_no_pillow(self):
        with patch("max.tools.native.media_tools.HAS_PILLOW", False):
            result = await handle_media_image_info({"path": "/any/path.png"})
            assert "error" in result
            assert "Pillow" in result["error"]


# ── Audio transcribe tests ──────────────────────────────────────────


class TestAudioTranscribe:
    @pytest.mark.asyncio
    async def test_transcribe_success(self, tmp_path):
        """Mock whisper to simulate successful transcription."""
        # Create a dummy file so the path check passes
        audio_file = tmp_path / "speech.wav"
        audio_file.write_bytes(b"\x00" * 100)

        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "text": "Hello world",
            "language": "en",
            "duration": 3.5,
        }

        mock_whisper = MagicMock()
        mock_whisper.load_model.return_value = mock_model

        with (
            patch("max.tools.native.media_tools.HAS_WHISPER", True),
            patch("max.tools.native.media_tools.whisper", mock_whisper, create=True),
        ):
            result = await handle_media_audio_transcribe({
                "path": str(audio_file),
                "model": "base",
            })

        assert result["text"] == "Hello world"
        assert result["language"] == "en"
        assert result["duration"] == 3.5
        mock_whisper.load_model.assert_called_once_with("base")

    @pytest.mark.asyncio
    async def test_transcribe_with_language(self, tmp_path):
        """Verify language option is passed to whisper."""
        audio_file = tmp_path / "spanish.wav"
        audio_file.write_bytes(b"\x00" * 100)

        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "text": "Hola mundo",
            "language": "es",
            "duration": 2.0,
        }

        mock_whisper = MagicMock()
        mock_whisper.load_model.return_value = mock_model

        with (
            patch("max.tools.native.media_tools.HAS_WHISPER", True),
            patch("max.tools.native.media_tools.whisper", mock_whisper, create=True),
        ):
            result = await handle_media_audio_transcribe({
                "path": str(audio_file),
                "model": "small",
                "language": "es",
            })

        assert result["text"] == "Hola mundo"
        assert result["language"] == "es"
        mock_model.transcribe.assert_called_once_with(str(audio_file), language="es")

    @pytest.mark.asyncio
    async def test_transcribe_default_model(self, tmp_path):
        """Default model should be 'base'."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"\x00" * 100)

        mock_model = MagicMock()
        mock_model.transcribe.return_value = {"text": "", "language": "", "duration": 0.0}

        mock_whisper = MagicMock()
        mock_whisper.load_model.return_value = mock_model

        with (
            patch("max.tools.native.media_tools.HAS_WHISPER", True),
            patch("max.tools.native.media_tools.whisper", mock_whisper, create=True),
        ):
            await handle_media_audio_transcribe({"path": str(audio_file)})

        mock_whisper.load_model.assert_called_once_with("base")

    @pytest.mark.asyncio
    async def test_transcribe_file_not_found(self):
        with patch("max.tools.native.media_tools.HAS_WHISPER", True):
            result = await handle_media_audio_transcribe({
                "path": "/nonexistent/audio.wav",
            })
            assert "error" in result
            assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_transcribe_no_whisper(self):
        with patch("max.tools.native.media_tools.HAS_WHISPER", False):
            result = await handle_media_audio_transcribe({
                "path": "/any/audio.wav",
            })
            assert "error" in result
            assert "whisper" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_transcribe_exception_handling(self, tmp_path):
        """Whisper errors should be caught and returned."""
        audio_file = tmp_path / "bad.wav"
        audio_file.write_bytes(b"\x00" * 100)

        mock_whisper = MagicMock()
        mock_whisper.load_model.side_effect = RuntimeError("model load failed")

        with (
            patch("max.tools.native.media_tools.HAS_WHISPER", True),
            patch("max.tools.native.media_tools.whisper", mock_whisper, create=True),
        ):
            result = await handle_media_audio_transcribe({"path": str(audio_file)})

        assert "error" in result
        assert "transcription failed" in result["error"].lower()


# ── Video info tests ─────────────────────────────────────────────────


class TestVideoInfo:
    @pytest.mark.asyncio
    async def test_video_info_success(self, tmp_path):
        """Mock ffmpeg.probe to return video metadata."""
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"\x00" * 100)

        mock_probe_result = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                },
            ],
            "format": {
                "duration": "120.5",
                "size": "5242880",
                "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            },
        }

        with (
            patch("max.tools.native.media_tools.HAS_FFMPEG", True),
            patch("max.tools.native.media_tools.ffmpeg") as mock_ffmpeg,
        ):
            mock_ffmpeg.probe.return_value = mock_probe_result
            result = await handle_media_video_info({"path": str(video_file)})

        assert result["duration"] == 120.5
        assert result["width"] == 1920
        assert result["height"] == 1080
        assert result["codec"] == "h264"
        assert result["format"] == "mov,mp4,m4a,3gp,3g2,mj2"
        assert result["size_bytes"] == 5242880

    @pytest.mark.asyncio
    async def test_video_info_audio_only(self, tmp_path):
        """File with no video stream should return zero dimensions."""
        audio_file = tmp_path / "audio.mp3"
        audio_file.write_bytes(b"\x00" * 100)

        mock_probe_result = {
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "mp3",
                },
            ],
            "format": {
                "duration": "60.0",
                "size": "1024000",
                "format_name": "mp3",
            },
        }

        with (
            patch("max.tools.native.media_tools.HAS_FFMPEG", True),
            patch("max.tools.native.media_tools.ffmpeg") as mock_ffmpeg,
        ):
            mock_ffmpeg.probe.return_value = mock_probe_result
            result = await handle_media_video_info({"path": str(audio_file)})

        assert result["width"] == 0
        assert result["height"] == 0
        assert result["codec"] == ""
        assert result["duration"] == 60.0

    @pytest.mark.asyncio
    async def test_video_info_file_not_found(self):
        with patch("max.tools.native.media_tools.HAS_FFMPEG", True):
            result = await handle_media_video_info({
                "path": "/nonexistent/video.mp4",
            })
            assert "error" in result
            assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_video_info_no_ffmpeg(self):
        with patch("max.tools.native.media_tools.HAS_FFMPEG", False):
            result = await handle_media_video_info({
                "path": "/any/video.mp4",
            })
            assert "error" in result
            assert "ffmpeg" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_video_info_probe_error(self, tmp_path):
        """ffmpeg.probe errors should be caught."""
        video_file = tmp_path / "corrupt.mp4"
        video_file.write_bytes(b"\x00" * 100)

        with (
            patch("max.tools.native.media_tools.HAS_FFMPEG", True),
            patch("max.tools.native.media_tools.ffmpeg") as mock_ffmpeg,
        ):
            mock_ffmpeg.probe.side_effect = Exception("Invalid data found")
            result = await handle_media_video_info({"path": str(video_file)})

        assert "error" in result
        assert "Video info failed" in result["error"]


# ── Missing dependency integration tests ─────────────────────────────


class TestMissingDependencies:
    """Verify all tools return clear error messages when deps are missing."""

    @pytest.mark.asyncio
    async def test_all_image_tools_without_pillow(self):
        with patch("max.tools.native.media_tools.HAS_PILLOW", False):
            r1 = await handle_media_image_resize({"path": "x", "width": 1, "height": 1})
            r2 = await handle_media_image_convert({"path": "x", "output_path": "y"})
            r3 = await handle_media_image_info({"path": "x"})

            for r in [r1, r2, r3]:
                assert "error" in r
                assert "Pillow" in r["error"]

    @pytest.mark.asyncio
    async def test_audio_tool_without_whisper(self):
        with patch("max.tools.native.media_tools.HAS_WHISPER", False):
            r = await handle_media_audio_transcribe({"path": "x"})
            assert "error" in r
            assert "whisper" in r["error"].lower()

    @pytest.mark.asyncio
    async def test_video_tool_without_ffmpeg(self):
        with patch("max.tools.native.media_tools.HAS_FFMPEG", False):
            r = await handle_media_video_info({"path": "x"})
            assert "error" in r
            assert "ffmpeg" in r["error"].lower()
