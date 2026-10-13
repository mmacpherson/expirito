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
- The holding directory belongs to expirito alone, and expirito checks three
  kinds of folder:
  - the holding directory itself must be a real folder owned by the user
    running expirito, with no access for group or others (`chmod 700`);
  - every folder above it must be owned by that user or root and writable by no
    one else, unless it is sticky like `/tmp` (whoever can write a folder can
    rename what is in it), and none may be a symlink;
  - the folders expirito creates inside holding to mirror each entry's original
    path (for example `.expired/mnt/scratch`) must belong to that user, be
    writable by no one else, and be neither symlinks nor mount points. expirito
    creates them `0700`.

  A problem with the first two stops expirito at startup; a problem with the
  third fails the moves and purge that need that folder. Entries held in
  holding are not checked this way, and may themselves be symlinks. Another
  process running as the same user is not stopped by any of this, so don't work
  in holding: a quarantined entry is waiting to be deleted.
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

## Upgrading to 1.2.0

The holding directory must now be private. Before the first run, `chmod 700`
it and fix any folder above it that others can write; expirito refuses to start
and says why otherwise. Folders an earlier version created inside holding to
mirror original paths (such as `.expired/home` and `.expired/home/user`) must
not be writable by group or others either; `chmod go-w` those mirror folders
only, not the held entries inside them.

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
    ignore:          # optional, gitignore syntax, relative to this directory
      - AGENTS.md
      - "*.ckpt"
log_file: actions.log
```

- `holding_directory`: The path to the holding directory where files and empty directories will be moved.
- `holding_age_limit`: The number of days after which files and directories in the holding directory will be deleted.
- `directories`: A list of directories to monitor and clean up, each with a specified `path` and `age_limit`.
- `ignore` (optional, per directory): gitignore-style patterns for entries
  expirito must never move or delete, matched relative to that directory. A
  folder holding a match is kept whole, since moving it would move the match.
- `log_file`: The path to the log file where Expirito will log its actions.

Without `-c`, expirito reads `$XDG_CONFIG_HOME/expirito/config.yaml`
(`~/.config/expirito/config.yaml` when `XDG_CONFIG_HOME` is unset).

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
