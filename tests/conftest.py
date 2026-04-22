import os
from pathlib import Path

import pytest


@pytest.fixture
def chdir():
    """Change working directory for the duration of a test."""
    original = Path.cwd()

    def _chdir(path: Path) -> None:
        os.chdir(path)

    yield _chdir
    os.chdir(original)
