import sys

import pytest


@pytest.fixture(autouse=True)
def _reset_join_limit():
    # The join rate limit is per process; every test starts with a clean slate.
    server = sys.modules.get("knowledge_clock.server")
    if server is not None:
        server._JOINS.clear()
