# Expirito

Expirito is a utility tool for cleaning up old files and empty directories based
on their age. It moves files and directories from specified paths to a holding
directory and eventually deletes them after a defined period.

## How entries expire

- Each entry at the top of a monitored directory expires as a unit. A file goes
  when it is past the age limit; a folder goes only when nothing anywhere in its
  tree has been touched within the limit, so a job folder is never picked apart.
- An entry's age runs from its last change: the later of its modification time
  and its inode change time. Data copied in with `cp -a` or `rsync -a` keeps its
  old modification time but is dated by its arrival, and moving an entry into
  the holding directory restarts its clock, so the holding period is honoured.
- Symlinks are dated by the link itself and removed as links; targets are never
  touched. A dangling link is not removed early (its target may just be on an
  unmounted disk).
- The holding directory may live inside a monitored directory (for example
  `/mnt/scratch/.expired`); it is skipped, never moved into itself.
- The holding directory belongs to expirito alone. It must be a real folder
  (not a symlink), owned by the user running expirito and writable by no one
  else, or expirito refuses to start. Its path components must not be symlinks
  or mount points; entries held there that happen to be symlinks are fine.
  Don't work in holding: a quarantined entry is waiting to be deleted.
- Nothing in holding is replaced: a taken name gives `NAME.1`, `NAME.2`, and so
  on. On Linux the move is one atomic no-replace rename (`renameat2`), so this
  holds even if a name is taken at the last moment; elsewhere it is a check
  followed by a rename.
- Moves are plain renames on one filesystem, never copy-then-delete. An entry
  that is or contains a mount point is left alone and logged; on Linux, a mount
  table that cannot be read stops the run.
- Each entry is checked again just before it is moved or deleted, and only one
  run (holding a lock in the holding directory) acts at a time. Even so, a
  process still writing into an entry at that moment can race the final step.
  For the move into holding the holding period is the safety margin; the purge
  of an entry from holding deletes it for good, including anything written into
  it during the purge.
- A run that leaves anything undone exits 1: a failed move or deletion, or an
  entry that could not be fully read (it is kept). Entries kept because they
  contain a mount point are a deliberate skip, logged without failing the run.
  `--dry-run` changes nothing, writes no log, and plans the same destinations
  a real run would choose; it cannot predict errors the real run will meet.

## Installation

- Arch Linux: `paru -S expirito` (AUR), or build the PKGBUILD here.
- Linux or another POSIX system with Python 3.10+:
  `uv tool install git+https://github.com/mmacpherson/expirito`

Then place a `config.yaml` (see below), by default at
`~/.config/expirito/config.yaml`, and either install the systemd timer
([Systemd Timer](#systemd-timer)) or run `expirito -c CONFIG` from your own
scheduler. `expirito --dry-run` shows what would happen without changing anything.

## Configuration

Create a `config.yaml` file with the following structure:

```yaml
holding_directory: /path/to/holding
holding_age_limit: 90
directories:
  - path: /path/to/directory1
    age_limit: 5
  - path: /path/to/directory2
    age_limit: 30
log_file: actions.log
```

- `holding_directory`: The path to the holding directory where files and empty directories will be moved.
- `holding_age_limit`: The number of days after which files and directories in the holding directory will be deleted.
- `directories`: A list of directories to monitor and clean up, each with a specified `path` and `age_limit`.
- `log_file`: The path to the log file where Expirito will log its actions.

Place the `config.yaml` file in the `~/.config/expirito` directory (or another suitable location).

## Systemd Timer

The Arch package installs `expirito.service` and `expirito.timer` as user units;
enable the timer with:

```
systemctl --user enable --now expirito.timer
```

With a uv install, copy both files from `systemd/` to `~/.config/systemd/user/`,
change the service's `ExecStart=` to `%h/.local/bin/expirito` (where `uv tool`
puts commands), run `systemctl --user daemon-reload`, then enable the timer as
above.

The timer runs expirito daily at 2am; `systemctl --user list-timers` shows it. A
run that leaves anything undone exits 1 and shows as a failed unit.

## License

This project is licensed under the MIT License.

## Acknowledgements

- [Your Name]: Project initiator and collaborator.
- ChatGPT with GPT-4 by OpenAI: Collaborator and AI-assisted development.
