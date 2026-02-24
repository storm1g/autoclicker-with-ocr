# Gambling Macro — Setup

## Install Python dependencies (that's all you need!)
```
pip install pyautogui pillow easyocr opencv-python keyboard pygetwindow
```

No external system installs required. EasyOCR is pure Python and handles
its own models — it will download ~100 MB of model files on first use,
then cache them locally for all future runs.

## Run
```
python gambling_macro.py
```

## Hotkeys (work globally while macro runs in background)
- F6 — Start macro
- F8 — Stop macro
- F9 — Capture coordinate / color (used inside dialogs)
- ESC — Cancel region selection overlay
- Move mouse to TOP-LEFT CORNER of screen — Emergency stop (pyautogui failsafe)

## How to set up

### 1. Clicks Tab
Add each click you need in sequence:
- Click the item to select it
- Click the gambling card(s)
Add them in order. Set a small delay_after (e.g. 0.15–0.5s) for each click.
Use the "Pick (F9)" button to capture exact screen coordinates.

### 2. Detection Tab
- Draw a region around the item name text on screen (use "Select Region")
- Click "Preview OCR" to confirm the text is being read correctly
  (first preview will be slow while EasyOCR loads its model)
- In "Must contain": type the prefix/suffix words you want (one per line)
  ALL words listed must be found for success
- In "Must NOT contain": type words that indicate failure (one per line)
- Optionally add a pixel color check for extra confirmation

### 3. Options Tab
- Loop delay: time between each gambling attempt (in seconds)
- Max attempts: macro will stop after this many tries

### 4. Start
Press F6 or click Start. Watch the Log tab for OCR output per attempt.
The macro stops automatically when the target prefix/suffix is found.

## Tips for better OCR accuracy
- Make the OCR region tight around just the item name text
- Use "Preview OCR" to verify what the macro sees before running
- EasyOCR handles coloured/stylised game fonts much better than Tesseract
- If OCR is inconsistent, try a slightly larger region with more context
