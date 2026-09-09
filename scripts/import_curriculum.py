"""课程包导入脚本：把 curriculum/quadratic 导入 SQLite（幂等 upsert）。

用法：
    cd backend
    uv run python ../../scripts/import_curriculum.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.infrastructure.curriculum_import import import_curriculum  # noqa: E402
from app.infrastructure.database import get_session_factory  # noqa: E402


def main() -> None:
    session = get_session_factory()()
    try:
        concept_count, question_count = import_curriculum(session)
        session.commit()
        print(f"导入完成：{concept_count} 个知识点，{question_count} 道题（全部通过答案自检）。")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
