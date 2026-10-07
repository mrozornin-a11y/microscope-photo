import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def pytest_configure(config):
    import tempfile

    os.environ.setdefault("MICROPHOTO_DATA_DIR", tempfile.mkdtemp(prefix="microphoto_test_"))
