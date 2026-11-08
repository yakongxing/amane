"""Subtitle source HTTP: search, download placement, failure mapping."""

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from amane.playback.factory import _probe_key
from tests.plugins.test_plugin_system import playback_plugin_source, write_plugin

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx2 import AsyncClient

    from amane.db.repository import Repository


SUBTITLE_PLUGIN = """
from pydantic import BaseModel, ConfigDict

from amane.plugin import (
    FailureReason,
    PlaybackQuery,
    PluginContext,
    SourceCapability,
    SourceDescriptor,
    SourceError,
    SubtitleCandidate,
    SubtitleFile,
    SubtitlePlugin,
    SubtitleProvider,
)


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    behavior: str = "ok"


class _Provider(SubtitleProvider):
    def __init__(self, config: _Config) -> None:
        self._config = config

    def _fail(self) -> None:
        if self._config.behavior == "error":
            raise SourceError(FailureReason.NETWORK, detail="字幕站登录失败")
        if self._config.behavior == "crash":
            raise RuntimeError("boom")

    async def search(self, query: PlaybackQuery) -> tuple[SubtitleCandidate, ...]:
        self._fail()
        return (
            SubtitleCandidate(id="c1", name=f"[{query.number}] 中文", language="Chinese", format="SRT"),
            SubtitleCandidate(id="raw", name="no language", format="SRT"),
        )

    async def download(self, query: PlaybackQuery, candidate_id: str) -> SubtitleFile | None:
        self._fail()
        if candidate_id == "c1":
            body = "1\\n00:00:01,000 --> 00:00:02,000\\n你好\\n"
            return SubtitleFile(content=body.encode("gb18030"), format="srt", language="zh")
        if candidate_id == "raw":
            return SubtitleFile(content=b"\\xff\\xfe\\x00", format="srt")
        return None


class Plugin(SubtitlePlugin):
    config_model = _Config

    @classmethod
    def descriptor(cls) -> SourceDescriptor:
        return SourceDescriptor(
            id="acme.subs",
            name="Fake subtitles",
            version="0.1.0",
            capabilities=frozenset({SourceCapability.SUBTITLE}),
        )

    def build_subtitle(self, context: PluginContext, config: BaseModel) -> SubtitleProvider:
        assert isinstance(config, _Config)
        return _Provider(config)
"""


async def _seed(repo: Repository, root: Path) -> tuple[int, int, int, int]:
    """一个条目挂一个视频; 另建一个条目与文件, 用于「文件不属于该影片」."""
    library = await repo.create_library(name="subs", path=str(root), subtitle_extensions=[".srt"])
    assert library.id is not None
    meta = await repo.upsert_metadata(number="SUB-001", title="Subs")
    other = await repo.upsert_metadata(number="SUB-002", title="Other")
    assert meta.id is not None and other.id is not None
    video = root / "SUB-001.strm"
    video.write_text("http://example.test/v.mp4", encoding="utf-8")
    media = await repo.create_media_file(library_id=library.id, path=str(video), metadata_id=meta.id)
    foreign_path = root / "SUB-002.mp4"
    foreign_path.write_bytes(b"x")
    foreign = await repo.create_media_file(library_id=library.id, path=str(foreign_path), metadata_id=other.id)
    assert media.id is not None and foreign.id is not None
    return meta.id, media.id, other.id, foreign.id


@pytest.mark.asyncio
async def test_subtitle_search_and_download(
    client: AsyncClient, repo: Repository, app: FastAPI, tmp_path: Path
) -> None:
    data_dir = app.state.runtime.config.cold.data_dir
    write_plugin(data_dir, "acme.subs", body=SUBTITLE_PLUGIN)
    # 仅播放的插件不出现在字幕源里, 字幕插件也不出现在播放源里.
    write_plugin(data_dir, "acme.play", body=playback_plugin_source("acme.play"))
    assert (await client.post("plugins/reload")).status_code == 200
    root = tmp_path / "media"
    root.mkdir()
    meta_id, media_id, other_id, foreign_id = await _seed(repo, root)

    sources = await client.get("subtitles/sources")
    assert sources.json()["items"] == [{"source_id": "acme.subs", "name": "Fake subtitles"}]
    playback_sources = await client.get("playback/sources")
    assert [row["source_id"] for row in playback_sources.json()["items"]] == ["acme.play"]

    found = await client.get(f"subtitles/acme.subs/{meta_id}/candidates")
    assert found.status_code == 200, found.text
    assert [(row["id"], row["name"]) for row in found.json()["items"]] == [
        ("c1", "[SUB-001] 中文"),
        ("raw", "no language"),
    ]

    # 两个条目的探测结果都进了缓存; 落盘只丢弃本条目的那份, 让播放源重新列出字幕轨道.
    for probed in (meta_id, other_id):
        assert (await client.get(f"playback/acme.play/{probed}/streams")).status_code == 200
    probes = app.state.runtime.playback_factory.caches.probe_hits

    url = f"subtitles/acme.subs/{meta_id}/download"
    saved = await client.post(url, json={"candidate_id": "c1", "media_id": media_id})
    assert saved.status_code == 200, saved.text
    target = root / "SUB-001.zh.srt"
    assert saved.json() == {"path": str(target)}
    # GB18030 正文统一转成 UTF-8 落盘.
    assert target.read_text(encoding="utf-8") == "1\n00:00:01,000 --> 00:00:02,000\n你好\n"
    media = await repo.get_media_file(media_id)
    assert media is not None and media.has_external_subtitle
    assert probes.get(_probe_key("acme.play", meta_id)) is None
    assert probes.get(_probe_key("acme.play", other_id)) is not None

    target.write_text("keep", encoding="utf-8")
    exists = await client.post(url, json={"candidate_id": "c1", "media_id": media_id})
    assert (exists.status_code, exists.json()["detail"]) == (409, "同名字幕已存在")
    assert target.read_text(encoding="utf-8") == "keep"
    replaced = await client.post(url, json={"candidate_id": "c1", "media_id": media_id, "overwrite": True})
    assert replaced.status_code == 200
    assert "你好" in target.read_text(encoding="utf-8")

    cases: list[tuple[str, dict[str, object], int, str]] = [
        (url, {"candidate_id": "c1", "media_id": foreign_id}, 404, "该影片没有这个文件"),
        (url, {"candidate_id": "c1", "media_id": 9999}, 404, "该影片没有这个文件"),
        (url, {"candidate_id": "gone", "media_id": media_id}, 404, "字幕不存在"),
        (url, {"candidate_id": "raw", "media_id": media_id}, 502, "无法识别字幕编码"),
        ("subtitles/acme.subs/9999/download", {"candidate_id": "c1", "media_id": media_id}, 404, "影片不存在"),
        (f"subtitles/acme.play/{meta_id}/download", {"candidate_id": "c1", "media_id": media_id}, 404, "字幕源不存在"),
    ]
    for path, body, status, detail in cases:
        response = await client.post(path, json=body)
        assert (response.status_code, response.json()["detail"]) == (status, detail), path
    # 无语言、解码失败的那份没有落盘.
    assert not (root / "SUB-001.srt").exists()
    assert sorted(p.name for p in root.iterdir()) == ["SUB-001.strm", "SUB-001.zh.srt", "SUB-002.mp4"]

    invalid = await client.post(url, json={"candidate_id": "..", "media_id": media_id})
    assert invalid.status_code == 422

    for behavior, detail in (("error", "字幕站登录失败"), ("crash", "字幕源失败")):
        configured = await client.patch("plugins/acme.subs", json={"enabled": True, "config": {"behavior": behavior}})
        assert configured.status_code == 200, configured.text
        searched = await client.get(f"subtitles/acme.subs/{meta_id}/candidates")
        assert (searched.status_code, searched.json()["detail"]) == (502, detail)
        downloaded = await client.post(url, json={"candidate_id": "c1", "media_id": media_id, "overwrite": True})
        assert (downloaded.status_code, downloaded.json()["detail"]) == (502, detail)

    disabled = await client.patch("plugins/acme.subs", json={"enabled": False, "config": {}})
    assert disabled.status_code == 200
    assert (await client.get("subtitles/sources")).json()["items"] == []
    assert (await client.get(f"subtitles/acme.subs/{meta_id}/candidates")).status_code == 404
