"""把插件取回的字幕写到视频旁边."""

from __future__ import annotations

import codecs
from pathlib import Path

from ..plugins.api import SubtitleFile
from ..utils.threads import in_thread

#: 单份字幕的大小上限; 文本字幕远小于此, 超出多半是插件交错了文件.
MAX_SUBTITLE_BYTES = 10 * 1024 * 1024


class SubtitlePlacementError(Exception):
    """无法落盘; 消息是给终端用户的中文原因."""


def decode_subtitle(content: bytes) -> str:
    """按 BOM → UTF-8 → GB18030 的顺序识别正文.

    GB18030 能解码绝大多数字节串, 因此必须排在 UTF-8 之后, 否则 UTF-8 正文会被解成乱码.
    两种 BOM 都在解码时去掉, 落盘为无 BOM 的 UTF-8.
    """
    if content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encodings: tuple[str, ...] = ("utf-16",)
    else:
        encodings = ("utf-8-sig", "gb18030")
    for encoding in encodings:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SubtitlePlacementError("无法识别字幕编码")


def subtitle_path(video: Path, subtitle: SubtitleFile) -> Path:
    """``<视频主名>.<语言>.<格式>``: 播放源与库字幕发现都按视频主名配对同目录字幕."""
    language = f".{subtitle.language}" if subtitle.language else ""
    return video.with_name(f"{video.stem}{language}.{subtitle.format}")


@in_thread
def write_subtitle(video: Path, subtitle: SubtitleFile, *, overwrite: bool) -> Path:
    """写到视频同目录并返回落盘路径; 已存在且不允许覆盖时抛 ``FileExistsError``.

    先写同目录临时文件再整体替换: 写到一半失败不会留下半截字幕, 也不会破坏已有的同名文件.
    """
    if len(subtitle.content) > MAX_SUBTITLE_BYTES:
        raise SubtitlePlacementError("字幕文件过大")
    text = decode_subtitle(subtitle.content)
    target = subtitle_path(video, subtitle)
    if not target.parent.is_dir():
        raise SubtitlePlacementError("视频所在目录不存在")
    if target.exists() and not overwrite:
        raise FileExistsError(target)
    temp = target.with_name(f".{target.name}.amane-tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        temp.replace(target)
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise SubtitlePlacementError("无法写入字幕文件, 请检查目录的写入权限") from exc
    return target
