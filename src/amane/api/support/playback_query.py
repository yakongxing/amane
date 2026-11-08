"""播放源与字幕源共用的条目快照装配."""

from __future__ import annotations

from fastapi import HTTPException

from ...db.repository import Repository
from ...playback.query import playback_query
from ...plugins.api import PlaybackQuery


async def load_playback_query(
    repo: Repository,
    metadata_id: int,
    selected_key: str | None,
) -> PlaybackQuery:
    """装配查询快照.

    ``selected_key`` 逐字交给插件: 主机不解释它, 也不核对它对应哪个文件 (那是插件的标识), 认不出来
    的 key 由插件以自身原因拒绝.
    """
    metadata = await repo.get_metadata(metadata_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="影片不存在")
    files = await repo.get_media_by_metadata_id(metadata_id)
    library_paths: dict[int, str] = {}
    for item in files:
        if item.library_id in library_paths:
            continue
        library = await repo.get_library(item.library_id)
        if library is not None:
            library_paths[item.library_id] = library.path
    return playback_query(metadata, files, selected_key=selected_key, library_paths=library_paths)
