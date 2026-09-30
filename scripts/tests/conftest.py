import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def recent_titles() -> list[str]:
    """本番の重複判定と同程度の規模(2026-09-14〜27 の既存記事タイトル178件、ドコモ関連を除く)。

    タイトル類似度は corpus 全体の出現頻度で重み付けするため、数件の corpus では本番と挙動が変わる。
    """
    return (FIXTURES / "recent_titles.txt").read_text(encoding="utf-8").splitlines()
