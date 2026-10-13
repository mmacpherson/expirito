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
  `/mnt/scratch/.expired`); it is skipped, never moved into itself. It must be a
  real folder, not a symlink, and expirito refuses any symlink inside it.
- Nothing is overwritten in holding: if a name is taken there, the newcomer
  becomes `NAME.1`, `NAME.2`, and so on.
- Moves are plain renames on one filesystem, never copy-then-delete. An entry
  that is or contains a mount point, or that cannot be fully read, is left
  alone and logged.
- Each entry is checked again just before it is moved or deleted, and only one
  run (holding a lock in the holding directory) acts at a time. A job that is
  still writing into a folder it has not touched for the whole age limit can
  race that last step; the holding period is the safety margin for that.
- A run that leaves anything undone exits 1; `--dry-run` changes nothing and
  writes no log.

## Installation

- Arch Linux: `paru -S expirito` (AUR), or build the PKGBUILD here.
- Anywhere with Python 3.10+: `uv tool install git+https://github.com/mmacpherson/expirito`

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
