"""字幕落盘: 编码识别、文件名、覆盖与失败路径."""

import codecs
from pathlib import Path

import pytest
from pydantic import ValidationError

from amane.plugins.api import SubtitleFile
from amane.subtitles.placement import (
    MAX_SUBTITLE_BYTES,
    SubtitlePlacementError,
    decode_subtitle,
    subtitle_path,
    write_subtitle,
)

_TEXT = "1\n00:00:01,000 --> 00:00:02,000\n中文字幕\n"


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(_TEXT.encode("utf-8"), id="utf-8"),
        pytest.param(codecs.BOM_UTF8 + _TEXT.encode("utf-8"), id="utf-8-bom"),
        pytest.param(_TEXT.encode("utf-16"), id="utf-16-bom"),
        pytest.param(_TEXT.encode("gbk"), id="gbk"),
        pytest.param(_TEXT.encode("gb18030"), id="gb18030"),
    ],
)
def test_decode_subtitle_recognizes_common_encodings(content: bytes) -> None:
    assert decode_subtitle(content) == _TEXT


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(codecs.BOM_UTF16_LE + b"\x00", id="truncated-utf-16"),
        pytest.param(b"\x81\x30", id="truncated-gb18030"),
    ],
)
def test_decode_subtitle_rejects_unknown_bytes(content: bytes) -> None:
    with pytest.raises(SubtitlePlacementError, match="无法识别字幕编码"):
        decode_subtitle(content)


@pytest.mark.parametrize(
    ("video", "language", "fmt", "expected"),
    [
        ("/m/ABC-123.mp4", "zh", "srt", "/m/ABC-123.zh.srt"),
        ("/m/ABC-123.strm", "zh-hant", "ass", "/m/ABC-123.zh-hant.ass"),
        ("/m/ABC-123.C.mkv", None, "vtt", "/m/ABC-123.C.vtt"),
    ],
)
def test_subtitle_path_pairs_with_video_stem(video: str, language: str | None, fmt: str, expected: str) -> None:
    subtitle = SubtitleFile.model_validate({"content": b"x", "format": fmt, "language": language})
    assert subtitle_path(Path(video), subtitle) == Path(expected)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"content": b"", "format": "srt"}, id="empty"),
        pytest.param({"content": b"x", "format": "sub"}, id="unknown-format"),
        pytest.param({"content": b"x", "format": "srt", "language": "Chinese"}, id="language-name"),
        pytest.param({"content": b"x", "format": "srt", "language": "../zh"}, id="language-path"),
    ],
)
def test_subtitle_file_rejects_invalid_payload(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SubtitleFile.model_validate(payload)


@pytest.mark.asyncio
async def test_write_subtitle_respects_existing_file(tmp_path: Path) -> None:
    video = tmp_path / "ABC-123.mp4"
    subtitle = SubtitleFile(content=_TEXT.encode("gbk"), format="srt", language="zh")

    written = await write_subtitle(video, subtitle, overwrite=False)
    assert written == tmp_path / "ABC-123.zh.srt"
    assert written.read_bytes() == _TEXT.encode("utf-8")

    written.write_text("old", encoding="utf-8")
    with pytest.raises(FileExistsError):
        await write_subtitle(video, subtitle, overwrite=False)
    assert written.read_text(encoding="utf-8") == "old"

    await write_subtitle(video, subtitle, overwrite=True)
    assert written.read_text(encoding="utf-8") == _TEXT
    assert sorted(path.name for path in tmp_path.iterdir()) == ["ABC-123.zh.srt"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("video_parent", "content", "message"),
    [
        pytest.param("missing", b"x", "视频所在目录不存在", id="missing-dir"),
        pytest.param(".", b"x" * (MAX_SUBTITLE_BYTES + 1), "字幕文件过大", id="too-large"),
    ],
)
async def test_write_subtitle_failures(tmp_path: Path, video_parent: str, content: bytes, message: str) -> None:
    video = tmp_path / video_parent / "ABC-123.mp4"
    with pytest.raises(SubtitlePlacementError, match=message):
        await write_subtitle(video, SubtitleFile(content=content, format="srt"), overwrite=False)
    assert list(tmp_path.iterdir()) == []
