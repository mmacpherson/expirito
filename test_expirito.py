import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

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
    long_ago = time.time() - 200 * DAY
    os.utime(job, (long_ago, long_ago))  # only the move itself can restart the clock
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


# --- Review findings (2026-10): each test pins a defect until its fix lands. ---


class Clock:
    """Stands in for the time module so a whole run can be aged forward."""

    def __init__(self, offset_days: float = 0):
        self.offset = offset_days * DAY

    def time(self) -> float:
        return time.time() + self.offset


def write_config(
    path: Path, holding: Path, watched: Path, age=60, hold=14, log=None
) -> Path:
    import yaml

    config = {
        "holding_directory": str(holding),
        "holding_age_limit": hold,
        "directories": [{"path": str(watched), "age_limit": age}],
    }
    if log:
        config["log_file"] = str(log)
    path.write_text(yaml.safe_dump(config))
    return path


def scratch_with_holding(tmp_path: Path) -> tuple[Path, Path, Path]:
    scratch = tmp_path / "scratch"
    holding = scratch / ".expired"
    holding.mkdir(parents=True)
    return scratch, holding, holding / scratch.relative_to(scratch.anchor)


def test_1_symlink_in_the_holding_path_never_redirects_deletion(tmp_path, monkeypatch):
    scratch, holding, held = scratch_with_holding(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("not holding")
    held.parent.mkdir(parents=True)
    held.symlink_to(outside)  # holding/.../scratch -> outside
    config = write_config(tmp_path / "c.yaml", holding, scratch)
    monkeypatch.setattr(expirito, "time", Clock(30))

    expirito.main(config, False)

    assert (outside / "precious.txt").exists()


def test_2_a_held_file_is_never_overwritten(tmp_path):
    scratch, holding, held = scratch_with_holding(tmp_path)
    held.mkdir(parents=True)
    (held / "report").write_text("held earlier")
    (scratch / "report").write_text("expiring now")

    expirito.clean_folder(scratch, 60, holding, False, time.time() + 61 * DAY)

    contents = sorted(p.read_text() for p in held.iterdir())
    assert contents == ["expiring now", "held earlier"]


def test_2_a_held_folder_is_never_nested_into(tmp_path):
    scratch, holding, held = scratch_with_holding(tmp_path)
    (held / "job").mkdir(parents=True)
    (held / "job" / "a").write_text("held earlier")
    (scratch / "job").mkdir()
    (scratch / "job" / "b").write_text("expiring now")

    expirito.clean_folder(scratch, 60, holding, False, time.time() + 61 * DAY)

    assert not (held / "job" / "job").exists()
    assert (held / "job" / "a").read_text() == "held earlier"
    assert sorted(p.name for p in held.iterdir()) != ["job"]  # new one sits beside it


def test_3_a_failed_rename_never_falls_back_to_copy_and_delete(tmp_path, monkeypatch):
    import errno

    scratch, holding, held = scratch_with_holding(tmp_path)
    (scratch / "job").mkdir()
    (scratch / "job" / "data").write_text("keep me")

    def busy(*args, **kwargs):
        raise OSError(errno.EBUSY, "Device or resource busy")

    monkeypatch.setattr(expirito.os, "rename", busy)
    expirito.clean_folder(scratch, 60, holding, False, time.time() + 61 * DAY)

    assert (scratch / "job" / "data").read_text() == "keep me"


def test_3_an_entry_containing_a_mount_point_is_left_alone(tmp_path, monkeypatch):
    scratch, holding, held = scratch_with_holding(tmp_path)
    (scratch / "job" / "mnt").mkdir(parents=True)
    (scratch / "job" / "mnt" / "data").write_text("on another filesystem")
    monkeypatch.setattr(
        expirito, "mount_points", lambda: {str(scratch / "job" / "mnt")}, raising=False
    )

    expirito.clean_folder(scratch, 60, holding, False, time.time() + 61 * DAY)

    assert (scratch / "job" / "mnt" / "data").exists()


def test_4_a_file_written_after_the_scan_is_not_deleted(tmp_path, monkeypatch):
    held = tmp_path / "held"
    (held / "job").mkdir(parents=True)
    (held / "job" / "old").write_text("old")
    scanned = expirito.is_tree_old_enough
    now = time.time() + 15 * DAY  # the run's clock

    def scan_then_write(path, *args):
        result = scanned(path, *args)
        fresh = path / "fresh"
        if not fresh.exists():  # a writer lands between the scan and the action
            fresh.write_text("written after the scan")
            os.utime(fresh, (now, now))
        return result

    monkeypatch.setattr(expirito, "is_tree_old_enough", scan_then_write)
    expirito.clean_folder(held, 14, None, False, now)

    assert (held / "job" / "fresh").exists()


def test_4_concurrent_runs_are_refused(tmp_path, monkeypatch):
    import fcntl

    scratch, holding, held = scratch_with_holding(tmp_path)
    (scratch / "old.txt").write_text("expiring")
    config = write_config(tmp_path / "c.yaml", holding, scratch)
    monkeypatch.setattr(expirito, "time", Clock(61))
    with open(holding / ".expirito.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # another run holds it
        failures = expirito.main(config, False)

    assert (scratch / "old.txt").exists()
    assert failures


def test_5_an_unreadable_subfolder_keeps_the_whole_entry(tmp_path):
    scratch, holding, held = scratch_with_holding(tmp_path)
    hidden = scratch / "job" / "private"
    hidden.mkdir(parents=True)
    (hidden / "maybe-recent").write_text("cannot be dated")
    hidden.chmod(0)
    try:
        expirito.clean_folder(scratch, 60, holding, False, time.time() + 61 * DAY)
        assert (scratch / "job").exists()
    finally:
        for p in (hidden, held / "job" / "private"):
            if p.exists():
                p.chmod(0o755)


def test_6_a_symlinked_holding_directory_is_rejected(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    real = tmp_path / "real-holding"
    real.mkdir()
    (scratch / ".expired").symlink_to(real)
    config = write_config(tmp_path / "c.yaml", scratch / ".expired", scratch)

    with pytest.raises(SystemExit):
        expirito.read_config(config)


def test_7_an_expired_dangling_link_is_moved(tmp_path):
    scratch, holding, held = scratch_with_holding(tmp_path)
    (scratch / "dangling").symlink_to(tmp_path / "unmounted")

    expirito.clean_folder(scratch, 60, holding, False, time.time() + 61 * DAY)

    assert (held / "dangling").is_symlink()


def test_7_a_read_only_held_file_is_still_deleted(tmp_path):
    held = tmp_path / "held"
    held.mkdir()
    (held / "readonly").write_text("x")
    (held / "readonly").chmod(0o444)

    expirito.clean_folder(held, 14, None, False, time.time() + 15 * DAY)

    assert not (held / "readonly").exists()


def test_8_failures_make_the_run_exit_nonzero(tmp_path, monkeypatch):
    scratch, holding, held = scratch_with_holding(tmp_path)
    locked = scratch / "locked"
    locked.mkdir()
    (locked / "child").write_text("x")
    config = write_config(tmp_path / "c.yaml", holding, scratch)
    monkeypatch.setattr(expirito, "time", Clock(61))
    monkeypatch.setattr(sys, "argv", ["expirito", "-c", str(config)])
    scratch.chmod(0o555)  # nothing can be moved out of it
    try:
        with pytest.raises(SystemExit) as exited:
            expirito.cli()
    finally:
        scratch.chmod(0o755)

    assert exited.value.code not in (0, None)


def test_9_dry_run_writes_nothing(tmp_path, monkeypatch):
    scratch, holding, held = scratch_with_holding(tmp_path)
    (scratch / "old.txt").write_text("expiring")
    log = tmp_path / "actions.log"
    config = write_config(tmp_path / "c.yaml", holding, scratch, log=log)
    monkeypatch.setattr(expirito, "time", Clock(61))

    expirito.main(config, True)

    assert not log.exists()
    assert (scratch / "old.txt").exists()


def test_10_the_systemd_unit_runs_the_installed_command():
    unit = (Path(__file__).parent / "systemd" / "expirito.service").read_text()
    assert "ExecStart=/usr/bin/expirito" in unit.splitlines()


@pytest.mark.xfail(strict=True, reason="review finding 11: .SRCINFO is stale")
def test_11_srcinfo_matches_the_pkgbuild():
    import shutil as sh
    import subprocess

    here = Path(__file__).parent
    if not sh.which("makepkg"):
        pytest.skip("makepkg not available")
    generated = subprocess.run(
        ["makepkg", "--printsrcinfo"],
        cwd=here,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert (here / ".SRCINFO").read_text() == generated
