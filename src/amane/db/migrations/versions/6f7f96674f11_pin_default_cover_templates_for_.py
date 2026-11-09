"""pin default cover templates for existing libraries

Revision ID: 6f7f96674f11
Revises: fb4fd486708c
Create Date: 2026-11-09 12:17:43.789032

封面 / 海报的缺省模板改为按视频文件名区分后, 把存量库里沿用缺省 (NULL 或空串) 的两列写成旧缺省,
已整理的目录布局不随升级改变. 旧值写成字面量, 不引用会随版本变化的常量.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "6f7f96674f11"
down_revision: str | None = "fb4fd486708c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PINNED = (
    ("thumb_template", "{link_dir}/thumb.jpg"),
    ("poster_template", "{link_dir}/poster.jpg"),
)


def upgrade() -> None:
    conn = op.get_bind()
    for column, value in _PINNED:
        conn.execute(
            text(f"UPDATE libraries SET {column} = :value WHERE {column} IS NULL OR {column} = ''"),
            {"value": value},
        )


def downgrade() -> None:
    # 旧版本里 NULL 就是这个值, 还原后行为不变; 无法区分用户手填的同值, 一并还原.
    conn = op.get_bind()
    for column, value in _PINNED:
        conn.execute(text(f"UPDATE libraries SET {column} = NULL WHERE {column} = :value"), {"value": value})
