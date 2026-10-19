"""pytest 共享夹具：隔离数据目录，避免测试污染真实 backend/data。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 必须在导入 app.main 之前生效：app.main 在模块顶层构造全局 Store
_TMP_DATA = tempfile.mkdtemp(prefix="mas-test-")
os.environ["MAS_DATA_DIR"] = _TMP_DATA


@pytest.fixture()
def tmp_data(tmp_path, monkeypatch):
    """把 store 的数据目录整体指向临时目录，测试结束后自动清理。"""
    from app import store as store_mod

    data = tmp_path / "data"
    runs = data / "runs"
    data.mkdir(parents=True)
    runs.mkdir(parents=True)
    monkeypatch.setattr(store_mod, "DATA_DIR", data)
    monkeypatch.setattr(store_mod, "RUNS_DIR", runs)
    return data


@pytest.fixture()
def store(tmp_data):
    from app.store import Store

    return Store()
