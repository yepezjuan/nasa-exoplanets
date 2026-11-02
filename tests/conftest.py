import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "pscomppars_sample.json"


@pytest.fixture
def raw_rows() -> list[dict[str, Any]]:
    """Real rows from `pscomppars`, including ones with null measurements."""
    return json.loads(FIXTURE.read_text())
