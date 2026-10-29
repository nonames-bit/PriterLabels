# PriterLabels

Created by Jaime.

Reprint the DataMatrix part labels from a PC, straight to the Honeywell printer
(Fingerprint / Direct Protocol over TCP port 9100), without going through the PLC.

## Use

- **Windows, no Python:** download `ReprintLabels.exe` from the latest
  *Build Windows exe* run in the Actions tab (artifact `ReprintLabels-exe`) and run it.
- **With Python 3:** `python reprint_labels.py` (window) or
  `python reprint_labels.py 85066731 3` (prints 3 labels, no window).

In the window:

1. Pick the **Label type**: A (part + date), B (GM part) or C (Y code, date on top);
   type the part number (and the Y code for type C) and the quantity, then **Add to list**.
2. Press **Print**; use **Pause / Resume / Stop** while it prints.
3. If the print sits off-center, use the arrow buttons under *Label position* to move
   everything, or drag one item (date, part number, DataMatrix...) in the **Preview**.
   **Print 1 test label** to check; **Reset** goes back to the normal position.

Printer IP/port and the positions (per label type) are saved in `settings.json` next to
the program. Label types live in `TEMPLATES` in `reprint_labels.py`, copied from the PLC
programs.

**Theme**: next to the printer IP you can pick *Normal*, *Green terminal* or *Amber terminal*
(retro look); the choice is saved in `settings.json`.
