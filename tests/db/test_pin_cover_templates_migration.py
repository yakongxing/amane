"""迁移: 存量库沿用缺省的封面 / 海报模板被固定为旧缺省, 已写的模板不动."""

from pathlib import Path

from alembic import command
from sqlalchemy import Connection, create_engine, text

from tests.helpers import alembic_config

_PREVIOUS = "fb4fd486708c"
_TARGET = "6f7f96674f11"
_INSERT_LIBRARY = (
    "INSERT INTO libraries "
    "(name, path, automation, recursive, patterns, move_mode, video_template, write_nfo, "
    "copy_resources, trailer_pattern, blacklist_patterns, subtitle_extensions, min_file_size, "
    "thumb_template, poster_template) "
    "VALUES (:name, :path, 'SCRAPE', 1, '[]', 'MOVE', '{number}.{ext}', 1, "
    "'[]', '', '[]', '[]', 0, :thumb, :poster)"
)

# (库名, 迁移前 thumb / poster, 升级后 thumb / poster, 降级后 thumb / poster)
_CASES: list[tuple[str, tuple[str | None, str | None], tuple[str, str], tuple[str | None, str | None]]] = [
    ("null", (None, None), ("{link_dir}/thumb.jpg", "{link_dir}/poster.jpg"), (None, None)),
    ("blank", ("", ""), ("{link_dir}/thumb.jpg", "{link_dir}/poster.jpg"), (None, None)),
    (
        "custom",
        ("{video_dir}/cover.jpg", "{video_dir}/{video_name}-poster.jpg"),
        ("{video_dir}/cover.jpg", "{video_dir}/{video_name}-poster.jpg"),
        ("{video_dir}/cover.jpg", "{video_dir}/{video_name}-poster.jpg"),
    ),
    # 只有一列沿用缺省时只固定那一列.
    (
        "mixed",
        ("{video_dir}/cover.jpg", None),
        ("{video_dir}/cover.jpg", "{link_dir}/poster.jpg"),
        ("{video_dir}/cover.jpg", None),
    ),
]


def _templates(conn: Connection) -> dict[str, tuple[str | None, str | None]]:
    rows = conn.execute(text("SELECT name, thumb_template, poster_template FROM libraries")).all()
    return {row.name: (row.thumb_template, row.poster_template) for row in rows}


def test_pin_cover_templates(tmp_path: Path) -> None:
    db_path = tmp_path / "migrate.db"
    cfg = alembic_config(db_path)
    command.upgrade(cfg, _PREVIOUS)

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        for name, (thumb, poster), _, _ in _CASES:
            conn.execute(
                text(_INSERT_LIBRARY), {"name": name, "path": f"/lib/{name}", "thumb": thumb, "poster": poster}
            )

    command.upgrade(cfg, _TARGET)
    with engine.connect() as conn:
        assert _templates(conn) == {name: upgraded for name, _, upgraded, _ in _CASES}

    command.downgrade(cfg, _PREVIOUS)
    with engine.connect() as conn:
        assert _templates(conn) == {name: downgraded for name, _, _, downgraded in _CASES}

    engine.dispose()
