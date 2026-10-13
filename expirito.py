#!/usr/bin/env python3

__version__ = "1.2.0"

import argparse
import contextlib
import errno
import fcntl
import logging
import os
import re
import shutil
import stat
import sys
import time
from pathlib import Path
from typing import Any

import yaml

# Configure logging - will be updated with file handler if specified in config
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(asctime)s: %(message)s"))
logger.addHandler(console_handler)


def validate_path(path: Path) -> bool:
    """Reject paths with ".." components (a traversal guard for configured paths).

    Containment below the holding directory is enforced by holding_subdir.
    """
    return ".." not in path.parts


def move_to_holding(file_path: Path, holding_directory: Path, dry_run: bool) -> Path:
    """Move the file to the holding directory, replicating the entire path.

    Args:
        file_path: The file path to be moved.
        holding_directory: The holding directory path.
        dry_run: If True, print the action without actually moving the file.

    Returns:
        The destination path in the holding directory.
    """
    # Security checks
    if not validate_path(file_path):
        raise ValueError(f"Invalid source path: {file_path}")
    if not validate_path(holding_directory):
        raise ValueError(f"Invalid holding directory: {holding_directory}")

    # The entry keeps its full original path below the holding directory.
    source = file_path.absolute()
    destination_directory = holding_subdir(
        holding_directory, source.parent.parts[1:], create=not dry_run
    )
    destination_path = free_name(destination_directory, source.name)

    if not dry_run:
        # rename only: shutil.move would fall back to copy-then-delete when a
        # rename fails (another filesystem, a busy mount point), and that can
        # remove the source tree while the copy is incomplete.
        try:
            os.rename(source, destination_path)
        except OSError:
            # Clean up any partially created directories
            if destination_directory.exists() and not any(
                destination_directory.iterdir()
            ):
                with contextlib.suppress(OSError):
                    destination_directory.rmdir()
            raise

    return destination_path


def free_name(folder: Path, name: str) -> Path:
    """FOLDER/NAME, or NAME.1, NAME.2, ... if taken, so a move never replaces a
    held entry or lands inside a held folder of the same name.

    The check and the later rename are not one atomic step; runs are serialized
    by the lock in main, and nothing else should write into holding.
    """
    candidate, n = folder / name, 0
    while os.path.lexists(candidate):
        n += 1
        candidate = folder / f"{name}.{n}"
    return candidate


def holding_subdir(
    holding_directory: Path, parts: tuple[str, ...], create: bool
) -> Path:
    """The folder HOLDING_DIRECTORY/PARTS..., checked one component at a time.

    Every existing component must be a real folder, never a symlink: a link
    anywhere below the holding directory would send moves, and the holding
    pass's deletions, somewhere else entirely.

    Args:
        holding_directory: The configured holding directory (itself checked by
            read_config).
        parts: Path components below it.
        create: Create missing components; otherwise stop at the first one
            missing and return the path as it would be.

    Raises:
        OSError: A component is a symlink or not a folder.
    """
    current = holding_directory
    for part in parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            if not create:
                return holding_directory.joinpath(*parts)
            current.mkdir()
            continue
        if not stat.S_ISDIR(mode):
            raise OSError(
                errno.ENOTDIR, "symlink or non-folder in the holding path", str(current)
            )
    return current


def last_touched(path: Path) -> float:
    """When an entry last changed: its content, or its arrival where it is now.

    mtime alone misdates two cases: cp -a and rsync -a keep an old mtime on
    data that just arrived, and moving an entry into the holding directory keeps
    its old mtime, which would let the holding pass delete it at once. The
    inode's ctime records both the arrival and the move.
    lstat dates a symlink by the link itself; a dangling target must not raise.
    """
    st = path.lstat()
    return max(st.st_mtime, st.st_ctime)


def is_old_enough(path: Path, age_limit: int, current_time: float) -> bool:
    """Check if a file or directory is older than the specified age limit.

    Args:
        path: The path to the file or directory.
        age_limit: The age limit in days.
        current_time: The current time in seconds since the epoch.

    Returns:
        True if the entry is older than the age limit, False otherwise.
    """
    age_in_seconds = current_time - last_touched(path)
    age_in_days = age_in_seconds / (60 * 60 * 24)
    return age_in_days > age_limit


def is_tree_old_enough(path: Path, age_limit: int, current_time: float) -> bool:
    """Check if all files and subdirectories under a given path are older than
    the specified age limit.

    Args:
        path: The path to the directory.
        age_limit: The age limit in days.
        current_time: The current time in seconds since the epoch.

    Returns:
        True if all entries in the tree are older than the age limit, False otherwise.

    Raises:
        OSError: Some part of the tree could not be inspected, or lies on another
            filesystem. An unread corner might hold recent data, so the tree must
            not be judged old.
    """
    if not is_old_enough(path, age_limit, current_time):
        return False
    device = path.lstat().st_dev

    def stop(error: OSError) -> None:
        raise error

    # os.walk does not follow links to folders; they are dated as links below.
    for dirpath, dirnames, filenames in os.walk(path, onerror=stop):
        for name in dirnames + filenames:
            entry = Path(dirpath) / name
            if entry.lstat().st_dev != device:
                raise OSError(errno.EXDEV, "another filesystem inside", str(entry))
            if not is_old_enough(entry, age_limit, current_time):
                return False
    return True


def mount_points() -> set[str]:
    """Every mount point on this system, from /proc/self/mountinfo.

    The table catches bind mounts too, which share their parent's device number
    and so slip past an st_dev comparison. Empty where /proc is unavailable.
    """
    try:
        lines = Path("/proc/self/mountinfo").read_text().splitlines()
    except OSError:
        return set()
    # The fifth field is the mount point, with spaces and such escaped as \ooo (octal).
    return {
        re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), line.split()[4])
        for line in lines
    }


def contains_mount(entry_path: Path, mounts: set[str]) -> bool:
    """Whether ENTRY_PATH is a mount point or has one anywhere beneath it."""
    entry = os.fspath(entry_path.resolve())
    return any(m == entry or m.startswith(entry + "/") for m in mounts)


def expired(entry_path: Path, age_limit: int, current_time: float) -> bool:
    """Whether a top-level entry has expired: a file or link by its own age, a
    folder only when its whole tree is older than the limit."""
    # A symlink to a folder is still just a link: date and remove the link.
    if entry_path.is_symlink() or not entry_path.is_dir():
        return is_old_enough(entry_path, age_limit, current_time)
    try:
        return is_tree_old_enough(entry_path, age_limit, current_time)
    except OSError as e:
        logger.warning(
            f"Keeping {entry_path}: cannot inspect {e.filename}: {e.strerror}"
        )
        return False


def contains_holding(entry_path: Path, holding_directory: Path | None) -> bool:
    """Whether ENTRY_PATH is the holding directory or a folder containing it.

    The holding directory may live inside a monitored folder (e.g.
    /mnt/scratch/.expired); it must never be moved into itself.
    """
    if holding_directory is None or entry_path.is_symlink():
        return False
    holding = holding_directory.resolve()
    entry = entry_path.resolve()
    return holding == entry or holding.is_relative_to(entry)


def clean_folder(
    folder_path: Path,
    days_old: int,
    holding_directory: Path | None,
    dry_run: bool,
    current_time: float | None = None,
) -> int:
    """Clean up files and empty directories in the folder based on their age.

    Each top-level entry expires as a unit: a folder goes only when nothing in
    its whole tree has been touched within the age limit. Symlinks are dated by
    the link itself and removed as links; their targets are never touched.

    Args:
        folder_path: The folder path to be cleaned.
        days_old: Files and empty directories older than this number of days
                  will be moved or deleted.
        holding_directory: The holding directory path. If not None, files and
                           empty directories are moved here instead of being deleted.
        dry_run: If True, print the actions without actually making changes.
        current_time: Seconds since the epoch to age entries against; now if None.

    Returns:
        The number of entries that could not be moved or deleted.
    """
    # Security check: validate folder_path
    if not validate_path(folder_path):
        logger.error(f"Invalid path: {folder_path}")
        return 1

    if current_time is None:
        current_time = time.time()
    try:
        entries = sorted(folder_path.iterdir())
    except OSError as e:
        logger.error(f"Cannot list {folder_path}: {e}")
        return 1
    mounts = mount_points()
    failures = 0
    for entry_path in entries:
        if contains_holding(entry_path, holding_directory):
            continue
        try:
            if not entry_path.is_symlink() and contains_mount(entry_path, mounts):
                logger.warning(f"Keeping {entry_path}: it is or contains a mount point")
                continue
            if not expired(entry_path, days_old, current_time):
                continue
            if dry_run:
                if holding_directory:
                    planned = move_to_holding(entry_path, holding_directory, True)
                    logger.info(f"Would move {entry_path} to {planned}")
                else:
                    logger.info(f"Would delete {entry_path}")
                continue
            # Something may have written into the entry since the scan; look
            # again right before acting, so that window is as small as it can be.
            if not expired(entry_path, days_old, current_time):
                logger.info(f"Keeping {entry_path}: it changed since the scan")
                continue
            if holding_directory:
                destination = move_to_holding(entry_path, holding_directory, False)
                logger.info(f"Moved {entry_path} to {destination}")
            else:
                delete_entry(entry_path)
                logger.info(f"Deleted {entry_path}")
        except FileNotFoundError:
            continue  # gone since the listing: nothing left to do
        except (OSError, ValueError) as e:
            verb = "move" if holding_directory else "delete"
            logger.error(f"Failed to {verb} {entry_path}: {e}")
            failures += 1
    return failures


def delete_entry(entry_path: Path) -> None:
    """Delete a file or link, or a whole folder tree (links inside are not followed)."""
    if entry_path.is_symlink() or not entry_path.is_dir():
        entry_path.unlink()
    else:
        shutil.rmtree(entry_path)


def setup_file_logging(log_file: str) -> None:
    """Configure file logging if specified in config.

    Args:
        log_file: Path to the log file
    """
    try:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter("%(asctime)s: %(message)s"))
        logger.addHandler(file_handler)
        logger.info(f"Logging to file: {log_file}")
    except Exception as e:
        logger.warning(f"Could not set up file logging: {e}")


def read_config(config_path: Path) -> dict[str, Any]:
    """Read the configuration file.

    Args:
        config_path: The path to the configuration file.

    Returns:
        The configuration as a dictionary.
    """
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Validate required fields
    required_fields = ["holding_directory", "holding_age_limit", "directories"]
    for field in required_fields:
        if field not in config:
            logger.error(f"Missing required field in config: {field}")
            sys.exit(1)

    # Validate and sanitize holding directory
    holding_dir = Path(config["holding_directory"])
    if not validate_path(holding_dir):
        logger.error(f"Invalid holding directory path: {holding_dir}")
        sys.exit(1)

    # A symlinked holding directory could point anywhere, and inside a monitored
    # folder the link itself would eventually expire and be moved.
    if holding_dir.is_symlink():
        logger.error(f"Holding directory [{holding_dir}] must not be a symlink.")
        sys.exit(1)

    if not holding_dir.exists():
        logger.error(f"Holding directory [{holding_dir}] does not exist.")
        sys.exit(1)

    # Validate holding_age_limit
    holding_age = config["holding_age_limit"]
    if (
        not isinstance(holding_age, int) or holding_age <= 0 or holding_age > 36500
    ):  # Max 100 years
        logger.error(
            f"Invalid holding_age_limit [{holding_age}]. Must be 1-36500 days."
        )
        sys.exit(1)

    # Validate monitored directories
    if not isinstance(config["directories"], list):
        logger.error("'directories' must be a list")
        sys.exit(1)

    for i, cd in enumerate(config["directories"]):
        if not isinstance(cd, dict):
            logger.error(f"Directory entry {i} is not a dictionary")
            sys.exit(1)

        if "path" not in cd or "age_limit" not in cd:
            logger.error(f"Directory entry {i} missing required fields")
            sys.exit(1)

        # Validate path
        dir_path = Path(cd["path"])
        if not validate_path(dir_path):
            logger.error(f"Invalid directory path at index {i}: {dir_path}")
            sys.exit(1)

        # Ensure monitored directory is not inside holding directory
        try:
            dir_path.resolve().relative_to(holding_dir.resolve())
            logger.error(
                f"Monitored directory cannot be inside holding directory: {dir_path}"
            )
            sys.exit(1)
        except ValueError:
            # Good - path is not inside holding directory
            pass

        if not dir_path.exists():
            logger.warning(f"Monitored directory [{dir_path}] does not exist.")

        # Validate age_limit
        age_limit = cd["age_limit"]
        if not isinstance(age_limit, int) or age_limit <= 0 or age_limit > 36500:
            logger.error(
                f"Invalid age_limit [{age_limit}] at index {i}. Must be 1-36500 days."
            )
            sys.exit(1)

    return config


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        An argparse.Namespace object containing the command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description="Clean up old files in specified directories.", prog="expirito"
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "-c", "--config-file", type=str, help="Path to the custom configuration file."
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Perform a dry run without actually making changes.",
    )
    return parser.parse_args()


LOCK_NAME = ".expirito.lock"


def main(config_path: Path, dry_run: bool) -> int:
    """Main function to clean up files based on the configuration.

    Args:
        config_path: The path to the configuration file.
        dry_run: If True, print the actions without actually making changes.

    Returns:
        The number of failures; nonzero means something was left undone.
    """
    config = read_config(config_path)

    # Set up file logging if specified
    # A dry run writes nothing, its log included: console only.
    if "log_file" in config and not dry_run:
        setup_file_logging(config["log_file"])

    holding_directory = Path(config["holding_directory"])
    holding_age_limit = config["holding_age_limit"]

    # One run at a time: two runs could pick the same free name in holding or
    # act on each other's half-finished moves. A dry run changes nothing and
    # needs no lock.
    lock = None
    if not dry_run:
        lock = open(holding_directory / LOCK_NAME, "a")  # noqa: SIM115
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            logger.error(f"Another expirito run holds {holding_directory / LOCK_NAME}")
            return 1
    try:
        failures = clean_all(config, holding_directory, holding_age_limit, dry_run)
    finally:
        if lock:
            lock.close()
    if failures:
        logger.error(f"{failures} entr{'y' if failures == 1 else 'ies'} left undone")
    return failures


def clean_all(
    config: dict[str, Any],
    holding_directory: Path,
    holding_age_limit: int,
    dry_run: bool,
) -> int:
    """Expire each monitored directory into holding, then purge its holding.

    Returns:
        The number of failures across all directories.
    """
    failures = 0
    for directory in config["directories"]:
        folder_path = Path(directory["path"])
        days_old = directory["age_limit"]

        # Move to holding pass.
        failures += clean_folder(folder_path, days_old, holding_directory, dry_run)

        # Delete from holding pass.
        try:
            deletion_path = holding_subdir(
                holding_directory, folder_path.absolute().parts[1:], create=False
            )
        except OSError as e:
            logger.error(f"Not purging holding for {folder_path}: {e}")
            failures += 1
            continue
        if deletion_path.is_dir():
            failures += clean_folder(deletion_path, holding_age_limit, None, dry_run)
    return failures


def cli() -> None:
    """Command-line entry point."""
    args = parse_arguments()

    default_config_path = Path.home() / ".config/expirito/config.yaml"
    config_path = Path(args.config_file) if args.config_file else default_config_path
    if not config_path.is_file():
        logger.error(f"Configuration file not found at {config_path}")
        sys.exit(1)

    sys.exit(1 if main(config_path, args.dry_run) else 0)


if __name__ == "__main__":
    cli()
