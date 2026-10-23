"""直连播放目标的地址与请求头约束."""

import pytest
from fastapi import HTTPException

from amane.api.routes.playback import _redirect_response
from amane.plugins.api import UpstreamPlaybackTarget


@pytest.mark.parametrize(
    "url,headers,message",
    [
        ("file:///etc/passwd", {}, "地址无效"),
        ("https://user:pass@example.com/a", {}, "地址无效"),
        ("https://example.com:invalid/a", {}, "地址无效"),
        ("https://example.com/a\n", {}, "地址无效"),
        ("https://example.com/a\\b", {}, "地址无效"),
        ("https://example.com/a", {"Authorization": "private"}, "自定义请求头"),
    ],
)
def test_redirect_rejects_invalid_target(url: str, headers: dict[str, str], message: str) -> None:
    with pytest.raises(HTTPException, match=message) as error:
        _redirect_response(UpstreamPlaybackTarget(url=url, headers=headers, delivery="redirect"))
    assert error.value.status_code == 502


def test_redirect_preserves_signed_url() -> None:
    url = "https://example.com/a%20b.mp4?sign=a%2Fb%3D"
    response = _redirect_response(UpstreamPlaybackTarget(url=url, delivery="redirect"))
    assert response is not None
    assert response.status_code == 302
    assert response.headers["location"] == url
    assert response.headers["cache-control"] == "private, no-store"
    assert _redirect_response(UpstreamPlaybackTarget(url=url)) is None
