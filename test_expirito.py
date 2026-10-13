import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import expirito

DAY = 86400


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
    entry = test_dir / "entry.txt"
    entry.touch()

    # Not yet past the limit: stays.
    expirito.clean_folder(test_dir, 5, holding, False, time.time() + 1 * DAY)
    assert entry.exists()

    # Past it: moved to holding with its path structure preserved.
    expirito.clean_folder(test_dir, 5, holding, False, time.time() + 10 * DAY)
    assert not entry.exists()
    assert (holding / test_dir.relative_to(test_dir.anchor) / "entry.txt").exists()


def test_copied_in_old_file_is_dated_by_its_arrival(tmp_path):
    # cp -a keeps a 200-day-old mtime; the file only arrived now.
    test_dir = tmp_path / "test"
    test_dir.mkdir()
    create_test_file(test_dir / "copied.tgz", 200)

    expirito.clean_folder(test_dir, 60, None, False)

    assert (test_dir / "copied.tgz").exists()


def test_holding_gives_the_full_grace_period(tmp_path):
    # Moving into holding restarts the clock: the next holding pass must not
    # delete an entry whose contents are long expired.
    scratch = tmp_path / "scratch"
    job = scratch / "job"
    job.mkdir(parents=True)
    create_test_file(job / "frames.bin", 200)
    holding = scratch / ".expired"
    holding.mkdir()
    moved_to = holding / scratch.relative_to(scratch.anchor)

    expirito.clean_folder(scratch, 60, holding, False, time.time() + 61 * DAY)
    assert (moved_to / "job" / "frames.bin").exists()

    expirito.clean_folder(moved_to, 14, None, False, time.time() + 1 * DAY)
    assert (moved_to / "job").exists()

    expirito.clean_folder(moved_to, 14, None, False, time.time() + 15 * DAY)
    assert not (moved_to / "job").exists()


def test_holding_inside_the_monitored_folder_is_never_moved(tmp_path):
    scratch = tmp_path / "scratch"
    holding = scratch / ".expired"
    holding.mkdir(parents=True)
    (holding / "waiting.txt").touch()

    expirito.clean_folder(scratch, 60, holding, False, time.time() + 365 * DAY)

    assert (holding / "waiting.txt").exists()
    assert [p.name for p in scratch.iterdir()] == [".expired"]


def test_a_folder_expires_only_when_nothing_in_it_is_recent(tmp_path):
    scratch = tmp_path / "scratch"
    job = scratch / "job"
    job.mkdir(parents=True)
    (job / "input.csv").touch()
    now = time.time() + 61 * DAY
    later = now + DAY
    os.utime(job / "input.csv", (later, later))  # still being written

    expirito.clean_folder(scratch, 60, None, False, now)

    assert (job / "input.csv").exists()


def test_symlinks_are_dated_by_the_link_and_never_followed(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "precious.txt").touch()
    (scratch / "live-link").symlink_to(target)
    (scratch / "dangling-link").symlink_to(tmp_path / "unmounted")

    # A fresh dangling link (its target may just be unmounted) is kept.
    expirito.clean_folder(scratch, 60, None, False)
    assert (scratch / "dangling-link").is_symlink()

    expirito.clean_folder(scratch, 60, None, False, time.time() + 61 * DAY)
    assert not (scratch / "live-link").is_symlink()
    assert not (scratch / "dangling-link").is_symlink()
    assert (target / "precious.txt").exists()


def test_tree_with_dangling_symlink(tmp_path):
    # A broken link nested in a tree (e.g. docs/tutorials -> ../tutorials/)
    # must be dated by the link itself, not crash following it.
    tree = tmp_path / "project"
    (tree / "docs").mkdir(parents=True)
    create_test_file(tree / "docs" / "old.txt", 10)
    (tree / "docs" / "tutorials").symlink_to("../tutorials/")

    assert expirito.is_tree_old_enough(tree, 7, time.time() + 10 * DAY)
