from __future__ import annotations

from pathlib import Path as FsPath
from typing import Annotated

import structlog
from fastapi import APIRouter, HTTPException, Path

from ...handlers._common import refresh_external_subtitle
from ...net.errors import SourceError
from ...plugins.api import SubtitleFile, SubtitleProvider
from ...subtitles.placement import SubtitlePlacementError, write_subtitle
from ..deps import RepoDep, RuntimeDep
from ..models.subtitles import (
    SubtitleCandidateItem,
    SubtitleCandidateListResponse,
    SubtitleDownloadRequest,
    SubtitleDownloadResponse,
    SubtitleSourceListResponse,
    SubtitleSourceOption,
)
from ..support.playback_query import load_playback_query

logger = structlog.get_logger()

router = APIRouter(prefix="/subtitles", tags=["subtitles"])


def _require_provider(source_id: str, runtime: RuntimeDep) -> SubtitleProvider:
    factory = runtime.subtitle_factory
    if factory is None:
        raise HTTPException(status_code=503, detail="字幕源未初始化")
    try:
        provider = factory.provider(source_id)
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=exc.detail or "字幕源失败") from exc
    if provider is None:
        raise HTTPException(status_code=404, detail="字幕源不存在")
    return provider


@router.get("/sources", response_model=SubtitleSourceListResponse)
async def list_subtitle_sources(runtime: RuntimeDep) -> SubtitleSourceListResponse:
    """列出已启用的字幕源; 不调用插件."""
    factory = runtime.subtitle_factory
    options = [] if factory is None else factory.source_options()
    return SubtitleSourceListResponse(
        items=[SubtitleSourceOption(source_id=option.source_id, name=option.name) for option in options]
    )


@router.get("/{source_id}/{metadata_id}/candidates", response_model=SubtitleCandidateListResponse)
async def search_subtitles(
    source_id: str,
    metadata_id: Annotated[int, Path(ge=1)],
    repo: RepoDep,
    runtime: RuntimeDep,
) -> SubtitleCandidateListResponse:
    """让一个字幕源按条目快照搜索; 插件失败以 502 与插件给出的原因返回."""
    provider = _require_provider(source_id, runtime)
    query = await load_playback_query(repo, metadata_id, None)
    try:
        candidates = await provider.search(query)
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=exc.detail or "字幕源失败") from exc
    except Exception as exc:
        logger.exception("subtitle search crashed", source=source_id)
        raise HTTPException(status_code=502, detail="字幕源失败") from exc
    return SubtitleCandidateListResponse(
        items=[
            SubtitleCandidateItem(
                id=item.id, name=item.name, language=item.language, format=item.format, detail=item.detail
            )
            for item in candidates
        ]
    )


@router.post("/{source_id}/{metadata_id}/download", response_model=SubtitleDownloadResponse)
async def download_subtitle(
    source_id: str,
    metadata_id: Annotated[int, Path(ge=1)],
    body: SubtitleDownloadRequest,
    repo: RepoDep,
    runtime: RuntimeDep,
) -> SubtitleDownloadResponse:
    """取回一份字幕并写到所选视频旁边.

    同名字幕已存在且未要求覆盖时返回 409, 已有文件不受影响. 落盘后刷新该文件的中字标记, 并丢弃
    这个条目的播放探测缓存, 让播放源下次探测时列出新字幕.
    """
    provider = _require_provider(source_id, runtime)
    query = await load_playback_query(repo, metadata_id, None)
    media = await repo.get_media_file(body.media_id)
    if media is None or media.metadata_id != metadata_id:
        raise HTTPException(status_code=404, detail="该影片没有这个文件")
    try:
        subtitle = await provider.download(query, body.candidate_id)
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=exc.detail or "字幕源失败") from exc
    except Exception as exc:
        logger.exception("subtitle download crashed", source=source_id)
        raise HTTPException(status_code=502, detail="字幕源失败") from exc
    if subtitle is None:
        raise HTTPException(status_code=404, detail="字幕不存在")
    if not isinstance(subtitle, SubtitleFile):
        logger.error("subtitle download returned unexpected type", source=source_id)
        raise HTTPException(status_code=502, detail="字幕源失败")
    try:
        target = await write_subtitle(FsPath(media.path), subtitle, overwrite=body.overwrite)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="同名字幕已存在") from exc
    except SubtitlePlacementError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    library = await repo.get_library(media.library_id)
    if library is not None:
        await refresh_external_subtitle(repo, media, library)
    if runtime.playback_factory is not None:
        runtime.playback_factory.forget_probes(metadata_id)
    return SubtitleDownloadResponse(path=str(target))
