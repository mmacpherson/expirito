#!/usr/bin/env python3

import argparse
import logging
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, cast

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s: %(message)s")


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
    # Create a relative path for the file by removing the root
    relative_path = file_path.relative_to(file_path.anchor)

    # Create the destination path in the holding directory
    destination_path = holding_directory / relative_path

    # Create the destination directory if it doesn't exist
    destination_directory = destination_path.parent
    if not destination_directory.exists():
        if not dry_run:
            destination_directory.mkdir(parents=True)

    if not dry_run:
        shutil.move(str(file_path), str(destination_path), copy_function=copy2_nofollow)

    return destination_path


def is_old_enough(path: Path, age_limit: int, current_time: float) -> bool:
    """Check if a file or directory is older than the specified age limit.

    Args:
        path: The path to the file or directory.
        age_limit: The age limit in days.
        current_time: The current time in seconds since the epoch.

    Returns:
        True if the entry is older than the age limit, False otherwise.
    """
    age_in_seconds = current_time - path.stat().st_mtime
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


def clean_folder(
    folder_path: Path,
    days_old: int,
    holding_directory: Optional[Path],
    dry_run: bool,
) -> None:
    """Clean up files and empty directories in the folder based on their age.

    Args:
        folder_path: The folder path to be cleaned.
        days_old: Files and empty directories older than this number of days
                  will be moved or deleted.
        holding_directory: The holding directory path. If not None, files and
                           empty directories are moved here instead of being deleted.
        dry_run: If True, print the actions without actually making changes.
    """
    current_time = time.time()
    for entry_path in folder_path.iterdir():
        action = None
        if entry_path.is_symlink():
            target = entry_path.resolve(strict=False)
            if not target.exists():
                if holding_directory:
                    action = "move"
                else:
                    action = "delete"
        else:
            if (
                entry_path.is_file()
                and is_old_enough(entry_path, days_old, current_time)
            ) or (
                entry_path.is_dir()
                and is_tree_old_enough(entry_path, days_old, current_time)
            ):
                if holding_directory:
                    action = "move"
                else:
                    action = "delete"

        if action is None:
            continue
        elif action == "move":
            destination_path = move_to_holding(
                entry_path, cast(Path, holding_directory), dry_run
            )
            action_log = f"Moved {entry_path} to {destination_path}"
        elif action == "delete":
            if not dry_run:
                if entry_path.is_file() or entry_path.is_symlink():
                    entry_path.unlink()
                else:
                    entry_path.rmdir()
            action_log = f"Deleted {entry_path}"
        else:
            raise NotImplementedError(f"Unexpected action state [{action}].")

        logging.info(action_log)


def read_config(config_path: Path) -> Dict[str, Any]:
    """Read the configuration file.

    Args:
        config_path: The path to the configuration file.

    Returns:
        The configuration as a dictionary.
    """
    with open(config_path, "rt") as f:
        config = yaml.safe_load(f)

    # Light validation of config file.
    all_config_dirs = [config["holding_directory"]] + [
        d["path"] for d in config["directories"]
    ]
    for config_dir in all_config_dirs:
        config_path = Path(config_dir)
        if not config_path.exists():
            logging.error(f"Configuration path [{config_path}] does not exist.")
            sys.exit(1)
        if not config_path.is_absolute():
            logging.error(
                f"Configuration path [{config_path}] is not an absolute path."
            )
            sys.exit(1)
    for d in config["directories"]:
        age_limit = d["age_limit"]
        if not (isinstance(age_limit, int) and (age_limit > 0)):
            logging.error(f"Invalid age_limit [{age_limit}] provided.")
            sys.exit(1)

    return config


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        An argparse.Namespace object containing the command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description="Clean up old files in specified directories."
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


if __name__ == "__main__":
    args = parse_arguments()

    default_config_path = Path.home() / ".config/expirito/config.yaml"
    config_path = Path(args.config_file) if args.config_file else default_config_path
    if not config_path.is_file():
        logging.error(f"Configuration file not found at {config_path}")
        sys.exit(1)

    main(config_path, args.dry_run)
