import os
from datetime import datetime, timedelta
from pathlib import Path

import expirito


def create_test_file(path: Path, age_days: int):
    path.touch()
    mtime = (datetime.now() - timedelta(days=age_days)).timestamp()
    os.utime(path, (mtime, mtime))


def test_move_to_holding(tmp_path):
    holding = tmp_path / "holding"
    holding.mkdir()
    test_dir = tmp_path / "test"
    test_dir.mkdir()

    old_file = test_dir / "old.txt"
    create_test_file(old_file, 10)
    expirito.move_to_holding(test_dir, holding, 5)

    assert not old_file.exists()
    assert (holding / str(test_dir) / "old.txt").exists()


def test_clean_folder(tmp_path):
    holding = tmp_path / "holding"
    holding.mkdir()
    test_dir = tmp_path / "test"
    test_dir.mkdir()

    old_file = test_dir / "old.txt"
    create_test_file(old_file, 10)

    config = {
        "holding_directory": str(holding),
        "holding_age_limit": 90,
        "directories": [{"path": str(test_dir), "age_limit": 5}],
        "log_file": "actions.log",
    }

    expirito.clean_folder(test_dir, config)

    assert not old_file.exists()
    assert (holding / str(test_dir) / "old.txt").exists()
