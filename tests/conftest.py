import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Тесты не должны трогать настоящие данные программы и настройки пользователя
os.environ.setdefault("MICROPHOTO_DATA_DIR", tempfile.mkdtemp(prefix="microphoto_test_"))
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp(prefix="microphoto_cfg_"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
