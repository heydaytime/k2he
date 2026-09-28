# QMK Layout – Keychron K2 HE (ANSI RGB)

This repo contains my custom QMK keymap (`mylayout`) for the **Keychron K2 HE** with Hall Effect switches and an ANSI RGB layout.  
Built on Keychron’s `2025q3` branch of QMK firmware (the older `hall_effect_playground` branch is deprecated).

---

## 📷 Layout Preview

Mac Base Layout QWERTY
![Current Layout](main-keyboard-layout.png)

Win Base Layout COLEMAK
![Current Layout](alt-keyboard-layout.png)



## 🛠️ Setup Instructions (macOS)

### 1. Install QMK CLI
```bash
brew install qmk/qmk/qmk
```

### 2. Clone the Correct Firmware Branch
```bash
git clone -b 2025q3 https://github.com/Keychron/qmk_firmware.git ~/qmk_firmware
git submodule update --init --recursive
qmk setup -H ~/qmk_firmware
```
This sets `~/qmk_firmware` as your QMK home directory.

### 3. (Optional but Recommended) Install QMK Toolbox
For easier firmware flashing:
```bash
brew install --cask qmk-toolbox
```

---

## 💻 Compiling the Firmware

Make sure you're in the QMK firmware root:
```bash
cd ~/qmk_firmware
```

(Optional) Update submodules:
```bash
qmk pull
# or
git submodule update --init
```

Then compile the firmware using your custom keymap:
```bash
qmk compile -kb keychron/k2_he/ansi -km mylayout
```

---

## 🧠 Notes

- This layout is in `keyboards/keychron/k2_he/ansi/keymaps/mylayout/`.
- You can flash the compiled `.bin` using QMK Toolbox.

---

## 🚦 Key Signals

Programs on the computer can color any key green (good), yellow (warn) or red
(needs attention) over raw HID. Signals are held in RAM, can expire on their
own, and show only while the RGB backlight is on. Implementation and full
details: `features/key_signals.h`. On the Mac, the `keysignal` service in
[`host/`](host/README.md) wraps this in a local HTTP API and command line.

Send a 32-byte report to the keyboard's raw HID interface (vendor ID `0x3434`,
usage page `0xFF60`, usage `0x61`). The keyboard echoes it back with the status
byte filled in.

| Byte | Meaning |
|---|---|
| 0 | `0x07` (VIA custom set value) |
| 1 | `0x00` (VIA custom channel) |
| 2 | command: `0x01` set, `0x02` clear all, `0x03` info |
| 3 | status in reply: `0` ok, `1` bad command, `2` bad key, `3` bad level/pattern |
| 4, 5 | set: key row, column (matrix position) |
| 6 | set: level `0` off, `1` good, `2` warn, `3` alert, `4` custom |
| 7 | set: pattern `0` solid, `1` blink, `2` pulse |
| 8, 9 | set: expiry in seconds, big endian, `0` = until cleared |
| 10–12 | set: r, g, b for the custom level |

Info replies with the protocol version, rows and columns in bytes 4–6.

---

## 📦 Repo Purpose

This repo only includes the keymap folder (`mylayout`) — not the full QMK firmware.  
You’ll still need to clone the full firmware from Keychron to compile it.
