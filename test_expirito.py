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

    # move_to_holding takes (file_path, holding_directory, dry_run)
    result_path = expirito.move_to_holding(old_file, holding, dry_run=False)

    assert not old_file.exists()
    assert result_path.exists()


def test_clean_folder(tmp_path):
    holding = tmp_path / "holding"
    holding.mkdir()
    test_dir = tmp_path / "test"
    test_dir.mkdir()

    old_file = test_dir / "old.txt"
    create_test_file(old_file, 10)
    new_file = test_dir / "new.txt"
    create_test_file(new_file, 1)

    # clean_folder takes (folder_path, days_old, holding_directory, dry_run)
    expirito.clean_folder(
        test_dir, days_old=5, holding_directory=holding, dry_run=False
    )

    assert not old_file.exists()
    assert new_file.exists()  # Should not be moved (only 1 day old)
    # Check that old file was moved to holding with preserved path structure
    moved_file = holding / test_dir.relative_to(test_dir.anchor) / "old.txt"
    assert moved_file.exists()
