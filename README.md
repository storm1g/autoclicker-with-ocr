# ⚔ AutoClicker

A macro tool for automating click sequences with OCR-based text detection. Built for prefix/suffix gambling in games — stops automatically when the right item name is detected.

## Installation

Install Python 3.9+ from https://python.org/downloads (check **"Add Python to PATH"** during install), then run:

```
pip install pyautogui pillow easyocr opencv-python keyboard pygetwindow
```

No external system installs required. EasyOCR downloads its own models (~100 MB) on first use and caches them locally.

## Running

```
python autoclicker.py
```

Or just double-click `autoclicker.py` if Python is associated with `.py` files on your system.

> **Run as Administrator** for best compatibility with games (right-click → Run as administrator, or launch your terminal as admin first).

## Hotkeys

| Key | Action |
|-----|--------|
| F6 | Start macro |
| F8 | Stop macro |
| F9 | Capture coordinate or color (inside dialogs) |
| ESC | Cancel region selection overlay |
| Mouse to top-left corner | Emergency stop |

## Setup Guide

### 1. Clicks Tab
Add each click in the sequence — in order. For gambling this is typically: select item → use card.

- **➕ Add Click** — opens a dialog to set coordinates, label, and delay
- **📍 Pick (F9)** — minimize the window, hover over the target, press F9 to capture coordinates automatically
- **📋 Duplicate** — copies the selected click right below it, useful for repeated actions
- **Double click checkbox** — sends two rapid clicks instead of one
- **Delay after (s)** — how long to wait after this click before the next one

### 2. Detection Tab

**OCR Region** — defines the screen area to scan for text (the item name).
- Use **📐 Select Region** to drag-select the area, or type coordinates manually
- Use **👁 Preview OCR** to verify it reads the text correctly before running

**Success Conditions** — three boxes control when the macro stops:

| Box | Logic | Example |
|-----|-------|---------|
| ✅ AND | Every word listed must be present | `of agility` |
| 🔀 OR | At least one word must be present | `sharp`, `keen`, `jagged` |
| ❌ Forbidden | Any match here = keep going | `of strength` |

One word or phrase per line. Leave a box empty to skip that check.

**Pixel Color Check** (optional) — extra confirmation by checking a specific pixel's color. Use **🎨 Pick Color** to capture it from the screen.

### 3. Options Tab
- **Delay between attempts (s)** — how long to wait after the last click before OCR scans. Should be long enough for the game to render the new item name. Start at `1.0` and tune down.
- **Max attempts** — also configurable directly in the bottom bar next to the Start button. Set to `0` for unlimited.

### 4. Start
Set the attempt count in the bottom bar, then press **F6** or click **▶ Start Macro**.

The macro will loop — clicking the sequence, waiting, scanning — until either the target is found or max attempts is reached. Check the **📋 Log tab** to see OCR output per attempt and tune your settings.

## Tips

- OCR fires *after* the loop delay, and the next attempt won't start until OCR finishes — so the cycle time is `click delays + loop delay + OCR scan time`
- EasyOCR typically takes 0.2–0.8s per scan depending on CPU — factor this in when setting delays
- If OCR misreads the item name, try making the region tighter or slightly larger
- Config is auto-saved to `autoclicker_config.json` in the same folder as the script