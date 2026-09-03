# Install and open Fika Sync

Quick guide to install and use the application, no programming
knowledge required.

## Only requirement: Python

Fika Sync needs **Python 3.10 or newer** installed on the computer.

- **Not sure if you have it?** No problem — the installer detects it
  automatically and tells you if it's missing.
- **Need to install it?** Download it from
  [python.org/downloads](https://www.python.org/downloads/).
  - **On Windows**: during installation, check the
    *"Add python.exe to PATH"* box before clicking Install — it's the
    step most people skip, and then nothing works afterward.
  - **On Mac**: the installer from python.org works fine, or if you
    use [Homebrew](https://brew.sh), `brew install python3`.

## Step 1: Install (one time only)

| System | What to run |
|---|---|
| **Windows** | Double-click `INSTALL.bat` |
| **Mac / Linux** | Open a terminal in this folder and run `./install.sh` |

A black window with text will open — that's normal, it shows
installation progress. When it finishes it will say *"Installation
complete"*. If something goes wrong, the error message explains
what's missing (it's almost always missing Python, or no internet
connection).

This step **only needs to be done once**. After installing, you don't
need to repeat it unless you delete the project folder.

## Step 2: Open the application (every time you want to use it)

| System | What to run |
|---|---|
| **Windows** | Double-click `Start Fika Sync.bat` |
| **Mac / Linux** | Open a terminal in this folder and run `./start_fika_sync.sh` |

What will happen:
1. A black window opens briefly, which minimizes itself (on Windows)
   or moves to the background (on Mac/Linux) — that's the
   application's "engine" running. No need to look at it or touch it.
2. After a few seconds, your browser opens on its own, showing the
   Fika Sync dashboard.

**Important: don't close that minimized window** while you're using
the app — it's what keeps everything running. If you close it by
accident, the application stops responding; just run Step 2 again to
bring it back up.

## How to fully close the application

Closing the browser tab **does not shut down the server** — it keeps
running in the background (on purpose, so you can reopen the tab
without having to restart anything). To shut it down completely:

| System | What to run |
|---|---|
| **Windows** | Double-click `Stop Fika Sync.bat` |
| **Mac / Linux** | `./stop_fika_sync.sh` |

## The first time you open it

You'll see the dashboard working with **sample data** (marked as
"demo" at the top) — so you can see how everything works without
needing any real account yet. When you want to connect your real
Cal.com, Google or Slack accounts, go to the "Connections" section of
the dashboard — there are guided buttons there for each one.

## Something isn't working

- **"Python not found"**: install it (see above) and run Step 1
  again.
- **The browser didn't open on its own**: open it manually and go to
  `http://127.0.0.1:5000`.
- **"Port in use" or the page doesn't load**: there may already be an
  instance running from a previous session. Run the "Stop" script and
  then "Start" again.
- For anything else, `fika-sync/gui/README.md` has the full technical
  detail.
