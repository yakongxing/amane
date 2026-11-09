"""文本字段翻译: 刮削后处理与详情页手动翻译共用同一套字段与目标语言判定."""

from collections.abc import Collection, Mapping
from typing import TYPE_CHECKING

from pydantic import BaseModel

from ..enums import Language, MetadataField
from ..observability import current

if TYPE_CHECKING:
    from ..llm import Translator


class TranslatedFields(BaseModel):
    """只填入译文与原文不同的字段; 为 None 表示保留原值."""

    title: str | None = None
    plot: str | None = None

    def fields(self) -> list[MetadataField]:
        out: list[MetadataField] = []
        if self.title is not None:
            out.append(MetadataField.TITLE)
        if self.plot is not None:
            out.append(MetadataField.PLOT)
        return out


async def translate_text_fields(
    translator: Translator,
    *,
    title: str | None,
    plot: str | None,
    fields: Collection[MetadataField],
    field_language: Mapping[MetadataField, Language],
    use_cache: bool,
) -> TranslatedFields:
    """翻译 ``fields`` 中的文本标量. 单字段失败不影响其余, 全程不抛.

    覆盖字段须在此显式列出 (项目禁反射); ``use_cache`` 为 False 时跳过译文缓存读取, 但仍刷新缓存.
    """
    out = TranslatedFields()
    if MetadataField.TITLE in fields and title:
        out.title = await _translate_field(translator, title, field_language, MetadataField.TITLE, use_cache)
    if MetadataField.PLOT in fields and plot:
        out.plot = await _translate_field(translator, plot, field_language, MetadataField.PLOT, use_cache)
    return out


async def _translate_field(
    translator: Translator,
    value: str,
    field_language: Mapping[MetadataField, Language],
    field: MetadataField,
    use_cache: bool,
) -> str | None:
    """无目标语言、无需翻译、失败或译文与原文相同时返回 None."""
    target = field_language.get(field)
    if target is None:
        return None
    try:
        result = await translator.translate(value, target, field, use_cache=use_cache)
    except Exception as e:
        current().warning("translation failed, keeping original", field=str(field), error=str(e))
        return None
    if not result or result == value:
        return None
    current().debug("field translated", field=str(field), target=str(target))
    return result
