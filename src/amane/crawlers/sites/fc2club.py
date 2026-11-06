"""FC2 索引站 javten.com (FC2hub 改名而来, 沿用 fc2club 来源 ID).

全站受 Cloudflare managed challenge 保护, 直连拿到的是挑战页, 依赖 ``use_browser`` 的 auto 切换.
"""

from datetime import timedelta
from urllib.parse import quote, urljoin

from parsel import Selector
from pydantic import Field, ValidationError

from ...enums import SiteName
from ..base import Crawler, CrawlerProfile
from ..models import FetchOptions, MediaMetadata, ResponseModel, SearchQuery, film_actors
from ..parsing import extract_all_texts, extract_text, fc2_article_id, fc2_number, is_same_number

_FC2_ID = '//h1[contains(@class, "fc2-id")]/text()'
_DESCRIPTION = '//div[contains(concat(" ", @class, " "), " des ")]'
# 卖家简介是原样转载的 HTML, 夹带站点插入的不可见水印与结尾的关键词堆砌.
_INVISIBLE = (
    './/*[@hidden or re:test(@style, "display:\\s*none|visibility:\\s*hidden'
    '|(opacity|height|font-size):\\s*0(\\.0*)?(px)?\\s*(;|$)", "i")]'
)


class _Rating(ResponseModel):
    rating_value: float | None = Field(default=None, alias="ratingValue")
    rating_count: int = Field(default=0, alias="ratingCount")


class _Movie(ResponseModel):
    """详情页的 schema.org ``Movie`` 块. ``director`` 是 FC2 卖家; ``description`` 被站点截断, 不取."""

    name: str = ""
    image: str | None = None
    date_published: str | None = Field(default=None, alias="datePublished")
    duration: timedelta | None = None
    actor: list[str] = Field(default_factory=list)
    genre: list[str] = Field(default_factory=list)
    director: str | None = None
    aggregate_rating: _Rating | None = Field(default=None, alias="aggregateRating")


def _movie(html: Selector) -> _Movie | None:
    for block in html.xpath('//script[@type="application/ld+json"]/text()').getall():
        if '"Movie"' not in block:
            continue
        try:
            return _Movie.model_validate_json(block)
        except ValidationError:
            return None
    return None


class FC2ClubCrawler(Crawler):
    @classmethod
    def profile(cls) -> CrawlerProfile:
        return CrawlerProfile(name=SiteName.FC2CLUB, base_url="https://javten.com")

    async def _search(self, query: SearchQuery, options: FetchOptions | None = None) -> str | None:
        """详情地址带站内序号, 不能由商品 ID 拼出. 检索词是已收录的商品 ID 时站点直接跳转到详情页, 未收录
        则停留在检索页 (按标题模糊匹配的列表), 因此只按跳转后的番号栏确认, 不从列表取条目."""
        article_id = fc2_article_id(query.number)
        if article_id is None:
            return None
        keyword = quote(fc2_number(article_id, ppv=True))
        html = Selector(text=await self.client.get_html(f"{self.base_url}/search?kw={keyword}"))
        if not is_same_number(extract_text(html, _FC2_ID), query.number):
            return None
        return extract_text(html, '//link[@rel="canonical"]/@href') or None

    async def _scrape(self, url: str, options: FetchOptions | None = None) -> MediaMetadata | None:
        html = Selector(text=await self.client.get_html(url))
        article_id = fc2_article_id(extract_text(html, _FC2_ID))
        movie = _movie(html)
        if article_id is None or movie is None or not movie.name:
            return None

        rating = movie.aggregate_rating
        # 画廊在桌面与移动布局各渲染一份, 地址可能省略协议.
        gallery = [
            urljoin(url, href) for href in dict.fromkeys(extract_all_texts(html, '//a[@data-fancybox="gallery"]/@href'))
        ]
        # 简介保留 HTML 片段, 换行与实体由聚合归一. drop 改动文档树, 放在其余字段之后.
        plot = ""
        if description := html.xpath(_DESCRIPTION):
            for invisible in description[0].xpath(_INVISIBLE):
                invisible.drop()
            plot = "".join(description[0].xpath("node()").getall())

        return MediaMetadata(
            number=fc2_number(article_id, ppv=False),
            title=movie.name,
            actors=film_actors(movie.actor),
            studio=movie.director,
            release=movie.date_published,
            runtime=int(movie.duration.total_seconds() // 60) if movie.duration else None,
            tags=movie.genre,
            plot=plot.strip() or None,
            thumb_urls=[movie.image] if movie.image else [],
            extrafanart=gallery,
            # 评分为站内 5 分制; 评价数为 0 时评分没有意义.
            score=rating.rating_value if rating and rating.rating_count else None,
            source_url=url,
        )
