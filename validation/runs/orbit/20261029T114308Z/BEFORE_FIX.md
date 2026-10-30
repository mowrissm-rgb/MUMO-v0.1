# Baseline before the fix

Every item failed because MUMO could not read xTB's output on Windows. xTB prints characters that the Windows default codec (cp1252) cannot decode, so `subprocess.run(..., text=True)` dropped the output and MUMO reported "output could not be parsed for HOMO/LUMO". This is a MUMO defect, not a protocol problem. The fix (`encoding='utf-8', errors='replace'` in `agents/qm_analyst.py`) is the next commit, and the post-fix run is the reference record. The reference xTB call inside the check had the same flaw and was fixed in the same commit.
