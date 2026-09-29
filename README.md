<p align="center">
  <img src="data/powerful-tools.svg" width="96" alt="Powerful Tools icon">
</p>

<h1 align="center">Powerful Tools</h1>

<p align="center">
  A free desktop app for Linux that puts 16 everyday productivity utilities in one place.
</p>

<p align="center">
  <a href="https://github.com/maggimagesh/powerful-tools/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/maggimagesh/powerful-tools?label=download"></a>
  <a href="https://github.com/maggimagesh/powerful-tools/actions/workflows/ci.yml"><img alt="Tests" src="https://github.com/maggimagesh/powerful-tools/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <img alt="Ubuntu 18.04 and newer" src="https://img.shields.io/badge/Ubuntu-18.04%2B-E95420">
</p>

![Powerful Tools dashboard](docs/screenshots/dashboard.png)

## What is Powerful Tools?

Powerful Tools is an app you install on your Linux computer. It gives you small, practical tools that
Linux doesn't offer out of the box. Pick a color from anywhere on the screen, copy text out of an image,
rename hundreds of files at once, keep your computer from sleeping during a long download, pin a
window on top of all the others, and more.

Everything is in a single window with a simple sidebar. Everything runs on your own computer: there's
no account, no internet connection needed and no data collection.

It's distributed as a single installer file (`.deb`), the standard package format for Ubuntu and
similar Linux systems.

## Features

| Tool | What it does |
|---|---|
| **Awake** | Stops your computer from sleeping: until you turn it off, for a set time, or until a chosen time. Your power settings are not changed. |
| **Color Picker** | Click anywhere on the screen to capture a color, with a magnifier for precision. Copy it as HEX, RGB, HSL, HSV or CMYK. Recent colors are saved. |
| **Text Extractor** | Draw a box around text on the screen, even inside a picture or video, and it's copied as editable text (OCR). |
| **Quick Launcher** | One search box to open apps and files, do quick math, run commands, search the web, or lock and suspend the computer. |
| **Bulk Rename** | Rename many files and folders at once using find-and-replace, text case changes and automatic numbering. Shows a preview first and can be undone. |
| **Image Resizer** | Resize many images at once to preset or custom sizes, and save as PNG or JPEG. |
| **File Unlocker** | Shows which programs are using a file or folder (the cause of "file is in use" errors) and lets you close them. |
| **Peek** | Instantly preview images, text files and folder contents without opening another app. |
| **Screen Ruler** | Measure anything on the screen in pixels. Edges are detected automatically. |
| **Always On Top** | Keeps a chosen window floating above all others, even while you work in other apps. |
| **Advanced Paste** | Converts copied text: plain text, formatted JSON, Markdown tables, upper or lower case, Base64 and more. |
| **Keyboard Manager** | Assign keyboard shortcuts to every tool, remap keys (for example, Caps Lock as Esc) and create your own shortcuts. |
| **Shortcut Guide** | A searchable list of all keyboard shortcuts on your desktop. |
| **Hosts File Editor** | Manage `/etc/hosts` entries (which website names point to which addresses) in an easy table. |
| **Environment Variables** | View and edit your personal environment variables without using a terminal. |
| **File Templates** | Create new files from your own templates. They also appear in the file manager's right-click menu. |

The window adjusts to any screen, from a small laptop to a 4K monitor. There's a light or dark theme,
and optional right-click menu entries for the Files, Nemo and Caja file managers.

<p align="center">
  <img src="docs/screenshots/quick-launcher.png" width="520" alt="Quick Launcher">
</p>
<p align="center">
  <img src="docs/screenshots/bulk-rename.png" width="620" alt="Bulk Rename with live preview">
  <img src="docs/screenshots/small-screen.png" width="190" alt="Layout on a small screen">
</p>

## Requirements

- **Ubuntu 18.04 or newer**, or an Ubuntu-based system such as Linux Mint, Pop!_OS, Zorin OS or
  elementary OS. Debian 10 or newer should also work, but isn't covered by the automated tests.
- **Any processor**: Intel, AMD or ARM.
- About **1 MB** of disk space for the app. Supporting components it needs are downloaded
  automatically during installation.

## Installation

### Using the terminal (recommended)

Open a terminal (<kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>T</kbd>), then paste these three lines:

```bash
cd /tmp
wget https://github.com/maggimagesh/powerful-tools/releases/latest/download/powerful_tools_1.0.0.deb
sudo apt install ./powerful_tools_1.0.0.deb
```

Enter your password when asked. That's all.

### Using the mouse

1. Open the [latest release](https://github.com/maggimagesh/powerful-tools/releases/latest) and, under
   **Assets**, download **`powerful_tools_1.0.0.deb`**.
2. Open your **Downloads** folder and double-click the file. Your software installer opens.
   Click **Install**.
3. If the installer doesn't open or shows an error (this varies between Ubuntu versions), use the
   terminal method above.

### Start the app

Open **Powerful Tools** from your applications menu, or type `powerful-tools` in a terminal.

> **Why is a password needed?** Linux asks for the administrator password whenever any app is
> installed. After installation, Powerful Tools runs with normal user rights. It asks again only for
> the two actions that Linux itself protects: saving `/etc/hosts`, and closing programs that belong
> to another user.

### Update

Download and install the newer `.deb` the same way. Your settings are kept.

### Uninstall

```bash
sudo apt remove powerful-tools
```

To also remove your personal settings, delete the folder `~/.config/powerful-tools`.

## Getting started

- **Keyboard shortcuts.** Open **Keyboard Manager** and click **Enable** next to a tool. Suggested
  shortcuts include <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Space</kbd> for Quick Launcher and
  <kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>C</kbd> for Color Picker. On GNOME-based desktops (Ubuntu,
  Pop!_OS, Zorin) shortcuts are set up automatically. On other desktops the app shows the commands to
  add in your system settings.
- **Right-click menu.** In **General → File manager integration**, click **Install**. You can then
  right-click files and choose **Scripts → Powerful Tools …** to resize, rename, preview or unlock them.
- **Quick Launcher tips.** Type an app name to launch it, `= 12*4` to calculate, `~/Documents` to browse
  files, `> command` to run a terminal command, or `?? question` to search the web.

## How it works

For readers who want a look under the hood:

- **Built with Python 3 and GTK 3**, the same toolkit used by many standard Ubuntu apps. These are
  already present on Ubuntu desktops, which keeps the package small (about 50 KB) and lets one file
  work on every processor type.
- **What gets installed:**

  | Location | Contents |
  |---|---|
  | `/usr/bin/powerful-tools` | the command that starts the app |
  | `/usr/lib/powerful-tools/` | the application code |
  | `/usr/share/applications/` | the entry in your applications menu |
  | `~/.config/powerful-tools/` | your settings (created when you first use the app) |

- **Supporting components**, installed automatically by `apt` from the official Ubuntu repositories:
  **Tesseract** (text recognition for Text Extractor), **wmctrl** and **xprop** (window control for
  Always On Top), and **pkexec** (the standard password prompt for protected actions).
- **Screen tools** (Color Picker, Text Extractor, Screen Ruler) take a single screenshot, show it
  full-screen and let you point at it. On newer Ubuntu versions (Wayland), your desktop may ask once
  for permission to take screenshots.
- **Privacy.** The app has no network features except the optional web search in Quick Launcher,
  which opens your normal web browser.

## Command line

```text
powerful-tools                    open the app
powerful-tools --run              open Quick Launcher
powerful-tools --pick-color       pick a color from the screen
powerful-tools --text-extract     copy text from the screen
powerful-tools --ruler            measure on screen
powerful-tools --always-on-top    pin or unpin the focused window
powerful-tools --toggle-awake     keep the computer awake, or stop
powerful-tools --page NAME        open a tool, e.g. hosts, envvars, peek
powerful-tools --rename FILES     bulk-rename files (also --resize, --unlocker, --peek)
powerful-tools --help             list all options
```

## Troubleshooting

| Problem | Solution |
|---|---|
| Text Extractor says the text recognition engine is missing | `sudo apt install tesseract-ocr tesseract-ocr-eng` |
| Text in another language isn't recognized | Install its language pack, e.g. `sudo apt install tesseract-ocr-deu` for German |
| Always On Top shows instructions instead of a window list | Your session uses Wayland, which doesn't let apps control other windows. Use the built-in option shown on the page, or choose **"Ubuntu on Xorg"** at the login screen. |
| A keyboard shortcut doesn't respond | Another app may use the same keys. Pick a different shortcut in Keyboard Manager. |
| New environment variables don't show up | They apply after you log out and log back in. |
| apt shows *"Download is performed unsandboxed as root"* | Harmless. It appears when the file is in a private folder such as Downloads. |

Still stuck? [Open an issue](https://github.com/maggimagesh/powerful-tools/issues) with your Ubuntu
version and the steps you took.

## For developers

```bash
git clone https://github.com/maggimagesh/powerful-tools.git
cd powerful-tools
bin/powerful-tools             # run from source (needs python3-gi, python3-gi-cairo, gir1.2-gtk-3.0)
python3 tests/test_logic.py    # quick unit tests
./build.sh                     # build dist/powerful_tools_<version>.deb
tests/docker_test.sh 22.04     # install and test the .deb in a clean Ubuntu container
```

Every push to `main` is tested automatically on Ubuntu 18.04, 20.04, 22.04 and 24.04. When all tests
pass, the tested `.deb` is published to the [Releases](https://github.com/maggimagesh/powerful-tools/releases)
page. See [CONTRIBUTING.md](CONTRIBUTING.md) for the project layout and guidelines.

## License

Powerful Tools is free and open-source software under the [MIT License](LICENSE). You may use, copy,
modify and share it.

It is an independent project with its own original code, name and icon, and it doesn't include
third-party code. The components it relies on are installed separately by your system under their own
open-source licenses: Python (PSF), GTK and PyGObject (LGPL), Tesseract (Apache 2.0), wmctrl (GPL),
xprop (MIT) and polkit (LGPL).

---

<p align="center">Made by <b>Magesh Kumar A T</b>. Thank you for downloading! ❤</p>
