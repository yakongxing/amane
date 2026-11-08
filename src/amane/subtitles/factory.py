"""SubtitleFactory: enabled subtitle plugins."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from ..net.errors import FailureReason, SourceError
from ..plugins.api import PluginContext, SubtitleProvider
from ..plugins.models import PluginConfig, SourceCapability

if TYPE_CHECKING:
    from ..crawlers.http import HttpClient
    from ..net.http import WebClient
    from ..plugins.manager import PluginManager

logger = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class SubtitleSourceOption:
    source_id: str
    name: str


class SubtitleFactory:
    """按来源 ID 延迟构造并缓存字幕 provider; 随热配置 rebuild 整个替换, 缓存不跨 rebuild."""

    def __init__(
        self,
        *,
        plugin_manager: PluginManager | None,
        plugin_configs: dict[str, PluginConfig],
        http_client: HttpClient,
        web_client: WebClient,
        data_dir: Path,
    ) -> None:
        self._plugin_manager = plugin_manager
        self._plugin_configs = plugin_configs
        self._http_client = http_client
        self._web_client = web_client
        self._data_dir = data_dir
        self._providers: dict[str, SubtitleProvider] = {}

    def enabled(self, source_id: str) -> bool:
        if self._plugin_manager is None or not self._plugin_manager.has_subtitle_plugin(source_id):
            return False
        return self._plugin_configs.get(source_id, PluginConfig()).enabled

    def source_options(self) -> list[SubtitleSourceOption]:
        """列出已启用的字幕源, 不调用插件."""
        if self._plugin_manager is None:
            return []
        return [
            SubtitleSourceOption(source_id=descriptor.id, name=descriptor.name)
            for descriptor in self._plugin_manager.plugin_descriptors()
            if descriptor.supports(SourceCapability.SUBTITLE) and self.enabled(descriptor.id)
        ]

    def provider(self, source_id: str) -> SubtitleProvider | None:
        """``None`` 表示未安装或未启用; 构造期的插件异常归为 ``SourceError``, 不让路由返回 500."""
        if self._plugin_manager is None or not self.enabled(source_id):
            return None
        cached = self._providers.get(source_id)
        if cached is not None:
            return cached
        plugin_dir = self._data_dir / "plugins" / source_id
        try:
            plugin_dir.mkdir(parents=True, exist_ok=True)
            built = self._plugin_manager.build_subtitle_provider(
                source_id,
                context=PluginContext(
                    source_id=source_id,
                    http_client=self._http_client,
                    web_client=self._web_client,
                    data_dir=plugin_dir,
                ),
                config=self._plugin_configs.get(source_id, PluginConfig()),
            )
        except Exception as exc:
            logger.exception("subtitle provider build failed", source=source_id)
            raise SourceError(FailureReason.NETWORK, detail="构建字幕源失败") from exc
        self._providers[source_id] = built
        return built
