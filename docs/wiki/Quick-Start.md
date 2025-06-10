## Quick Start

Get started with PyRC in a few easy steps.

### Prerequisites

- Python 3.8 or higher
- `pip` (Python package installer)
- `windows-curses` (on Windows)
- `pyfiglet` (optional, for `/ascii` command)

**Easy Setup:** Follow these steps to get PyRC up and running quickly.

### Installation

PyRC can be installed directly from PyPI:

```
pip install pyrc
```

Alternatively, you can install the latest development version from GitHub:

```
pip install git+https://github.com/edgeof8/PyRC.git
```

### Configuration

PyRC uses `pyterm_irc_config.ini` in its root directory. To get started, copy the example configuration file:

```
cp pyterm_irc_config.ini.example pyterm_irc_config.ini
```

Then, edit `pyterm_irc_config.ini` to customize your server settings and identity. A basic example:

```ini
[Server.YourServerName]
address = irc.libera.chat
port = 6697
ssl = true
nick = YourNick
channels = #yourchannel,#anotherchannel

[identity]
username = yourusername
realname = Your Real Name
```

For more detailed configuration options, refer to the [Advanced Usage](advanced-usage.md) section.

### Running PyRC

Once installed and configured, run PyRC from your terminal:

```
pyrc
```

#### Command-line Overrides

You can override server settings directly from the command line:

```
pyrc --connect irc.example.com --nick MyNick --channel #mychannel
```

#### Headless Mode

To run PyRC without a UI (e.g., for bots or automated testing), use the `--headless` flag:

```
pyrc --headless --connect irc.libera.chat
```

#### Troubleshooting

If you encounter any issues, please refer to the [Troubleshooting](troubleshooting.md) guide for common problems and solutions, or check the [Debugging and Logging](debugging-and-logging.md) page.
