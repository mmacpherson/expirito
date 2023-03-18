#!/usr/bin/env python3

import argparse
import logging
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s: %(message)s")


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
        shutil.move(str(file_path), str(destination_path))

    return destination_path


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
    for entry_path in folder_path.glob("**/*"):
        entry_age_in_seconds = current_time - entry_path.stat().st_atime
        entry_age_in_days = entry_age_in_seconds / (60 * 60 * 24)

        if entry_age_in_days > days_old:
            if entry_path.is_file() or (
                entry_path.is_dir() and not any(entry_path.iterdir())
            ):
                if holding_directory:
                    destination_path = move_to_holding(
                        entry_path, holding_directory, dry_run
                    )
                    action = f"Moved {entry_path} to {destination_path}"
                else:
                    if not dry_run:
                        if entry_path.is_file():
                            entry_path.unlink()
                        else:
                            entry_path.rmdir()
                    action = f"Deleted {entry_path}"

                logging.info(action)


def read_config(config_path: Path) -> Dict[str, Any]:
    """Read the configuration file.

    Args:
        config_path: The path to the configuration file.

    Returns:
        The configuration as a dictionary.
    """
    with open(config_path, "rt") as f:
        config = yaml.safe_load(f)
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
        clean_folder(folder_path, days_old, holding_directory, dry_run)

    clean_folder(holding_directory, holding_age_limit, None, dry_run)


if __name__ == "__main__":
    args = parse_arguments()

    default_config_path = Path.home() / ".config/expirito/config.yaml"
    config_path = Path(args.config_file) if args.config_file else default_config_path
    if not config_path.is_file():
        logging.error(f"Configuration file not found at {config_path}")
        sys.exit(1)

    main(config_path, args.dry_run)
