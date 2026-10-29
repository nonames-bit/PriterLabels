# PriterLabels

Reprint the DataMatrix part labels from a PC, straight to the Honeywell printer
(Fingerprint / Direct Protocol over TCP port 9100), without going through the PLC.

## Use

- **Windows, no Python:** download `ReprintLabels.exe` from the latest
  *Build Windows exe* run in the Actions tab (artifact `ReprintLabels-exe`) and run it.
- **With Python 3:** `python reprint_labels.py` (window) or
  `python reprint_labels.py 85066731 3` (prints 3 labels, no window).

In the window: add part numbers and quantities to the list, press **Print**, and use
**Pause / Resume / Stop** while it prints. Printer IP/port and the X/Y position offset
are editable and saved in `settings.json` next to the program.
