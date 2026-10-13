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

1. Copy the `expirito.service` and `expirito.timer` files to the `~/.config/systemd/user/` directory.
2. Reload the systemd user daemon by running:
   ```
   systemctl --user daemon-reload
   ```
3. Enable and start the timer by running:
   ```
   systemctl --user enable --now expirito.timer
   ```
4. To check the timer's status, run:
   ```
   systemctl --user list-timers
   ```

Expirito will now run automatically at 2am every day.

## License

This project is licensed under the MIT License.

## Acknowledgements

- [Your Name]: Project initiator and collaborator.
- ChatGPT with GPT-4 by OpenAI: Collaborator and AI-assisted development.
