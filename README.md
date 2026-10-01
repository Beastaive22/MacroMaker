# Macro Maker

Turn any key or mouse button into a macro. Bind a button to act as another key, press
a shortcut (like `ctrl+c`), or run a full macro: recorded key presses, mouse clicks,
scrolling, typed text, waits, and opening programs.

A simple Windows app — one window, no installer, no Python, no account needed.

## Download

1. Open the [latest release](../../releases/latest).
2. Download **MacroMaker.exe**.
3. Run it. That's it — nothing to install.

## First launch: Windows will warn you

This app is new and unsigned, so Windows SmartScreen will probably say **"Windows
protected your PC"**. Click **More info → Run anyway**. Some antivirus programs also
flag apps that watch keyboard input as a false positive. The full source code is in
this repo ([`macro_maker.py`](macro_maker.py)) — you can read exactly what it does.

## How to use it

1. Click a key or mouse button in the picture.
2. Choose what that button should do:
   - **Act as another key or mouse button** — e.g. make it work like the letter `E`.
   - **Press a shortcut** — e.g. `ctrl+shift+s`.
   - **Run a macro** — a list of steps: key presses, mouse clicks, scrolling, typed
     text, waits, and opening programs.
3. Click the green **Turn ON** button.

While it's ON, your macros work in your other programs and games, while this window
keeps working normally.

Extra things it can do:

- **Profiles** — keep separate setups and switch between them.
- **Record** — click Record, use another program, click Stop, and your actions become
  macro steps automatically (turn the app OFF first).
- **Save macros** — name a macro and reuse it on any button.
- **Sharing** — export a profile or your saved macros as a file, and import files
  other people send you.

## Questions

**My macros don't work in a game or program.**
Make sure the app is turned ON. If the game or program runs as administrator, run
Macro Maker as administrator too (right-click → *Run as administrator*).

**Where are my settings saved?**
In `%APPDATA%\MacroMaker\macros.json`. Back up that file to keep your setups safe.

## Run from source

```
py -m pip install pynput
py macro_maker.py
```

## Build the exe

```
py -m pip install pyinstaller pynput
py -m PyInstaller --onefile --windowed --name MacroMaker macro_maker.py
```

The finished exe is `dist\MacroMaker.exe`.
