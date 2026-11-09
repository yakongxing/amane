"""POST /metadata/{id}/translate: 复用运行时 translator 与热配置, 译文写库并覆盖已有 NFO."""

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from amane.enums import Language, MetadataField
from amane.llm import LLMTranslator

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx2 import AsyncClient

    from amane.db.repository import Repository


JP_TITLE = "日本語のタイトル"
JP_PLOT = "これはあらすじです"
ZH_TITLE = "中文标题"
ZH_PLOT = "这是简介"


class _FakeTranslator:
    """按原文查表; 表中值为异常时抛出, 未登记的原文返回 None (等同已是目标语言)."""

    def __init__(self, table: dict[str, str | Exception]) -> None:
        self._table = table
        self.calls: list[tuple[str, Language, MetadataField]] = []

    async def translate(
        self, text: str, target: Language, field: MetadataField, *, use_cache: bool = True
    ) -> str | None:
        self.calls.append((text, target, field))
        value = self._table.get(text)
        if isinstance(value, Exception):
            raise value
        return value


async def _seed(
    repo: Repository, root: Path, *, video_template: str, video_rel: str, nfo: bool = True
) -> tuple[int, Path]:
    """条目挂两个文件, 两者按模板渲染到同一个 NFO; 返回条目 id 与该 NFO 路径."""
    library = await repo.create_library(name="lib", path=str(root), video_template=video_template)
    assert library.id is not None
    meta = await repo.upsert_metadata(number="ABC-123", title=JP_TITLE, plot=JP_PLOT)
    assert meta.id is not None
    video = root / video_rel
    video.parent.mkdir(parents=True)
    video.write_bytes(b"x")
    nfo_path = video.with_suffix(".nfo")
    if nfo:
        nfo_path.write_text("<movie><title>old</title></movie>", encoding="utf-8")
    await repo.create_media_file(library_id=library.id, path=str(video), metadata_id=meta.id)
    bare = root / "elsewhere" / "ABC-123-cd2.mp4"
    bare.parent.mkdir(parents=True)
    bare.write_bytes(b"x")
    await repo.create_media_file(library_id=library.id, path=str(bare), metadata_id=meta.id)
    return meta.id, nfo_path


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("video_template", "video_rel", "nfo"),
    [
        pytest.param("{number}/{number}.{ext}", "ABC-123/ABC-123.mp4", True, id="plain-template"),
        # 模板引用标题: NFO 按翻译前的标题整理在旧目录里, 必须按旧值定位而不是新建
        pytest.param(
            "{number} {title}/{number}.{ext}", f"ABC-123 {JP_TITLE}/ABC-123.mp4", True, id="title-in-template"
        ),
        pytest.param("{number}/{number}.{ext}", "ABC-123/ABC-123.mp4", False, id="no-existing-nfo"),
    ],
)
async def test_translate_writes_db_and_existing_nfo(
    client: AsyncClient,
    repo: Repository,
    app: FastAPI,
    tmp_path: Path,
    video_template: str,
    video_rel: str,
    nfo: bool,
) -> None:
    root = tmp_path / "files" / "lib"
    meta_id, nfo_path = await _seed(repo, root, video_template=video_template, video_rel=video_rel, nfo=nfo)
    fake = _FakeTranslator({JP_TITLE: ZH_TITLE, JP_PLOT: ZH_PLOT})
    app.state.runtime.translator = fake

    resp = await client.post(f"metadata/{meta_id}/translate")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["translated_fields"] == ["title", "plot"]
    assert (body["metadata"]["title"], body["metadata"]["plot"]) == (ZH_TITLE, ZH_PLOT)
    # 两个文件共用一个 NFO 时只写一次; 没有现存 NFO 时逐文件计入 missing
    assert body["nfo_paths"] == ([str(nfo_path)] if nfo else [])
    assert body["nfo_failed"] == []
    assert body["nfo_missing"] == (0 if nfo else 2)
    # 目标语言来自 scraping.field_language (默认简体中文)
    assert {(c[0], c[1]) for c in fake.calls} == {(JP_TITLE, Language.ZH_CN), (JP_PLOT, Language.ZH_CN)}
    if nfo:
        text = nfo_path.read_text(encoding="utf-8")
        assert f"<title>ABC-123 {ZH_TITLE}</title>" in text
        assert f"<plot>{ZH_PLOT}</plot>" in text
    # 只覆盖已有 NFO, 不移动视频, 也不新建
    assert nfo_path.exists() is nfo
    assert not (root / "elsewhere" / "ABC-123-cd2.nfo").exists()
    assert (root / video_rel).exists()
    stored = await repo.get_metadata(meta_id)
    assert stored is not None
    assert (stored.title, stored.plot) == (ZH_TITLE, ZH_PLOT)
    assert {MetadataField.TITLE, MetadataField.PLOT} <= set(stored.locked_fields or [])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("table", "expected_fields", "expected_title", "expected_plot"),
    [
        pytest.param({}, [], JP_TITLE, JP_PLOT, id="already-target-or-failed"),
        pytest.param(
            {JP_TITLE: RuntimeError("boom"), JP_PLOT: ZH_PLOT}, ["plot"], JP_TITLE, ZH_PLOT, id="one-field-raises"
        ),
        pytest.param({JP_TITLE: JP_TITLE}, [], JP_TITLE, JP_PLOT, id="echoes-source"),
    ],
)
async def test_translate_keeps_original_on_failure(
    client: AsyncClient,
    repo: Repository,
    app: FastAPI,
    tmp_path: Path,
    table: dict[str, str | Exception],
    expected_fields: list[str],
    expected_title: str,
    expected_plot: str,
) -> None:
    root = tmp_path / "files" / "lib"
    meta_id, nfo_path = await _seed(repo, root, video_template="{number}/{number}.{ext}", video_rel="ABC-123/A.mp4")
    app.state.runtime.translator = _FakeTranslator(table)

    resp = await client.post(f"metadata/{meta_id}/translate")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["translated_fields"] == expected_fields
    assert (body["metadata"]["title"], body["metadata"]["plot"]) == (expected_title, expected_plot)
    stored = await repo.get_metadata(meta_id)
    assert stored is not None
    assert (stored.title, stored.plot) == (expected_title, expected_plot)
    # 未翻译的字段不加锁; 没有任何译文时 NFO 原样保留
    assert (MetadataField.TITLE in (stored.locked_fields or [])) is (expected_title != JP_TITLE)
    if not expected_fields:
        assert nfo_path.read_text(encoding="utf-8") == "<movie><title>old</title></movie>"
        assert body["nfo_paths"] == []


@pytest.mark.asyncio
async def test_translate_rejects_unusable_requests(client: AsyncClient, repo: Repository, app: FastAPI) -> None:
    meta = await repo.upsert_metadata(number="ABC-123", title=JP_TITLE)
    assert meta.id is not None

    # 默认未启用 LLM: 运行时没有 translator
    assert app.state.runtime.translator is None
    resp = await client.post(f"metadata/{meta.id}/translate")
    assert resp.status_code == 503
    assert "未启用" in resp.json()["detail"]

    # 热配置启用并给出密钥后, 重建出的 translator 立即对端点生效
    patched = await client.patch("config", json={"llm": {"enabled": True, "api_key": "sk-test"}})
    assert patched.status_code == 200, patched.text
    assert isinstance(app.state.runtime.translator, LLMTranslator)

    app.state.runtime.translator = _FakeTranslator({JP_TITLE: ZH_TITLE})
    missing = await client.post("metadata/999999/translate")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "影片不存在"

    patched = await client.patch("config", json={"llm": {"translate_fields": []}})
    assert patched.status_code == 200, patched.text
    app.state.runtime.translator = _FakeTranslator({JP_TITLE: ZH_TITLE})
    empty = await client.post(f"metadata/{meta.id}/translate")
    assert empty.status_code == 400
    assert empty.json()["detail"] == "未配置需要翻译的字段"
