# Expirito

Expirito is a utility tool for cleaning up old files and empty directories based on their age. It moves files and directories from specified paths to a holding directory and eventually deletes them after a defined period.

This project is a collaboration between [Your Name] and ChatGPT with GPT-4 by OpenAI.

## Installation

1. Install the Expirito package using the provided PKGBUILD file.
2. Place the `config.yaml` file in a suitable location, such as `~/.config/expirito/config.yaml`.
3. Install the systemd timer by following the instructions in the [Systemd Timer](#systemd-timer) section.

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
