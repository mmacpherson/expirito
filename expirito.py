#!/usr/bin/env python3

__version__ = "1.2.0"

import argparse
import contextlib
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, cast

import yaml

# Configure logging - will be updated with file handler if specified in config
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(asctime)s: %(message)s"))
logger.addHandler(console_handler)


def validate_path(path: Path, base_path: Path | None = None) -> bool:
    """Validate that a path is safe from traversal attacks.

    Args:
        path: The path to validate
        base_path: Optional base path that the path must be within

    Returns:
        True if the path is safe, False otherwise
    """
    try:
        # Resolve to absolute path, following symlinks
        resolved = path.resolve(strict=False)

        # Check for path traversal attempts
        if ".." in path.parts:
            return False

        # If base_path provided, ensure path is within it
        if base_path:
            base_resolved = base_path.resolve(strict=False)
            try:
                resolved.relative_to(base_resolved)
            except ValueError:
                # Path is outside base_path
                return False

        return True
    except (OSError, ValueError):
        return False


def check_permissions(path: Path, mode: str) -> bool:
    """Check if we have the required permissions for a path.

    Args:
        path: The path to check
        mode: 'r' for read, 'w' for write, 'x' for execute

    Returns:
        True if we have the required permissions
    """
    try:
        if mode == "r":
            return os.access(path, os.R_OK)
        elif mode == "w":
            # For write, check parent directory if path doesn't exist
            check_path = path if path.exists() else path.parent
            return os.access(check_path, os.W_OK)
        elif mode == "x":
            return os.access(path, os.X_OK)
        else:
            return False
    except OSError:
        return False


def copy2_nofollow(*args):
    """Modified version of copy2 to pass to shutil.move"""
    return shutil.copy2(*args, follow_symlinks=False)


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

    # Check permissions
    if not dry_run:
        if not check_permissions(file_path, "r"):
            raise PermissionError(f"No read permission for: {file_path}")
        if not check_permissions(holding_directory, "w"):
            raise PermissionError(f"No write permission for: {holding_directory}")

    # Create a relative path for the file by removing the root
    relative_path = file_path.relative_to(file_path.anchor)

    # Create the destination path in the holding directory
    destination_path = holding_directory / relative_path

    # Create the destination directory if it doesn't exist
    destination_directory = destination_path.parent
    if not destination_directory.exists() and not dry_run:
        destination_directory.mkdir(parents=True)

    if not dry_run:
        try:
            shutil.move(
                str(file_path), str(destination_path), copy_function=copy2_nofollow
            )
        except (OSError, PermissionError):
            # Clean up any partially created directories
            if destination_directory.exists() and not any(
                destination_directory.iterdir()
            ):
                with contextlib.suppress(OSError):
                    destination_directory.rmdir()
            raise

    return destination_path


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
    """
    return is_old_enough(path, age_limit, current_time) and all(
        is_old_enough(p, age_limit, current_time) for p in path.glob("**/*")
    )


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
) -> None:
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
    """
    # Security check: validate folder_path
    if not validate_path(folder_path):
        logger.error(f"Invalid path: {folder_path}")
        return

    # Check read permissions
    if not check_permissions(folder_path, "r"):
        logger.error(f"No read permission for: {folder_path}")
        return

    if current_time is None:
        current_time = time.time()
    for entry_path in folder_path.iterdir():
        action = None
        if contains_holding(entry_path, holding_directory):
            continue
        # A symlink to a folder is still just a link: date and remove the link.
        if entry_path.is_symlink() or not entry_path.is_dir():
            expired = is_old_enough(entry_path, days_old, current_time)
        else:
            expired = is_tree_old_enough(entry_path, days_old, current_time)
        if expired:
            action = "move" if holding_directory else "delete"

        if action is None:
            continue
        elif action == "move":
            try:
                destination_path = move_to_holding(
                    entry_path, cast(Path, holding_directory), dry_run
                )
                action_log = f"Moved {entry_path} to {destination_path}"
            except (OSError, PermissionError, ValueError) as e:
                logger.error(f"Failed to move {entry_path}: {e}")
                continue
        elif action == "delete":
            if not dry_run:
                try:
                    # Check permissions right before deletion
                    if not check_permissions(entry_path, "w"):
                        logger.error(f"No write permission for: {entry_path}")
                        continue

                    if entry_path.is_file() or entry_path.is_symlink():
                        entry_path.unlink()
                    else:
                        shutil.rmtree(entry_path)
                except (OSError, PermissionError) as e:
                    logger.error(f"Failed to delete {entry_path}: {e}")
                    continue
            action_log = f"Deleted {entry_path}"
        else:
            raise NotImplementedError(f"Unexpected action state [{action}].")

        logger.info(action_log)


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


def main(config_path: Path, dry_run: bool) -> None:
    """Main function to clean up files based on the configuration.

    Args:
        config_path: The path to the configuration file.
        dry_run: If True, print the actions without actually making changes.
    """
    config = read_config(config_path)

    # Set up file logging if specified
    if "log_file" in config:
        setup_file_logging(config["log_file"])

    holding_directory = Path(config["holding_directory"])
    holding_age_limit = config["holding_age_limit"]

    for directory in config["directories"]:
        folder_path = Path(directory["path"])
        days_old = directory["age_limit"]

        # Move to holding pass.
        clean_folder(folder_path, days_old, holding_directory, dry_run)

        # Delete from holding pass.
        deletion_path = holding_directory / str(folder_path).lstrip("/")
        if deletion_path.exists():
            clean_folder(deletion_path, holding_age_limit, None, dry_run)


def cli() -> None:
    """Command-line entry point."""
    args = parse_arguments()

    default_config_path = Path.home() / ".config/expirito/config.yaml"
    config_path = Path(args.config_file) if args.config_file else default_config_path
    if not config_path.is_file():
        logger.error(f"Configuration file not found at {config_path}")
        sys.exit(1)

    main(config_path, args.dry_run)


if __name__ == "__main__":
    cli()
