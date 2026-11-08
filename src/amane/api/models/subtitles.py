from pydantic import BaseModel, ConfigDict, Field

from ...plugins.api import PathSegment


class SubtitleSourceOption(BaseModel):
    """一个已启用的字幕源. 只有名字: 打开下载对话框时才去搜索."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    name: str


class SubtitleSourceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SubtitleSourceOption] = Field(default_factory=list)


class SubtitleCandidateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    language: str | None = None
    format: str | None = None
    detail: str | None = None


class SubtitleCandidateListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SubtitleCandidateItem] = Field(default_factory=list)


class SubtitleDownloadRequest(BaseModel):
    """把一份字幕写到条目某个已入库视频的旁边."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: PathSegment
    media_id: int = Field(ge=1)
    #: 同名字幕已存在时是否覆盖; 为假时返回 409.
    overwrite: bool = False


class SubtitleDownloadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
