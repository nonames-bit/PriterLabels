# PriterLabels

Reprint the DataMatrix part labels from a PC, straight to the Honeywell printer
(Fingerprint / Direct Protocol over TCP port 9100), without going through the PLC.

## Use

- **Windows, no Python:** download `ReprintLabels.exe` from the latest
  *Build Windows exe* run in the Actions tab (artifact `ReprintLabels-exe`) and run it.
- **With Python 3:** `python reprint_labels.py` (window) or
  `python reprint_labels.py 85066731 3` (prints 3 labels, no window).

In the window: add part numbers and quantities to the list, press **Print**, and use
**Pause / Resume / Stop** while it prints. If the print sits off-center, use the
arrow buttons under *Label position* (each click moves it a little) and
**Print 1 test label**; **Reset** goes back to the normal position. The *Preview*
shows an approximate drawing of the label as you type and move it. Printer IP/port and the position
are saved in `settings.json` next to the program.
