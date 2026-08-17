"""
MUMO — pose-stability worker, run inside the ISOLATED MD environment.

WHY THIS FILE EXISTS
--------------------
openmm and openff cannot go into MUMO's main conda environment. Adding them
there once already caused a numpy/MKL/libstdc++ ABI conflict that segfaulted
ProLIF (exit 139) and took the whole Space down. The lesson recorded at the
time was: isolate MD in its own environment and invoke it as a subprocess.

So this script is executed by a DIFFERENT python — the one in /opt/mdenv — and
talks to the app over JSON on disk. Nothing from openmm is ever imported into
the Streamlit process, which is what makes a crash here survivable: the child
dies, the parent reads an error, and the rest of MUMO keeps serving.

Usage (not for humans):
    /opt/mdenv/bin/python md_runner.py spec.json
where spec.json is {"receptor_pdb": path, "ligand_sdf": path, "out_dir": path,
                    "relax_ps": float}
and the result is written next to it as result.json.
"""

import json
import os
import sys
import traceback


def main(spec_path):
    with open(spec_path, "r", encoding="utf-8") as fh:
        spec = json.load(fh)

    out_dir = spec.get("out_dir") or os.path.dirname(os.path.abspath(spec_path))
    result_path = os.path.join(out_dir, "result.json")

    def write(obj):
        tmp = result_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)
        os.replace(tmp, result_path)          # atomic: the reader never sees half a file

    try:
        # imported here, not at module scope, so a broken MD environment still
        # produces a JSON error rather than an unparseable traceback on stderr
        from rdkit import Chem
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
        from agents.md_analyst import run_stability_md

        lig = Chem.MolFromMolFile(spec["ligand_sdf"], removeHs=False)
        if lig is None:
            write({"_error": "Could not read the ligand SDF for simulation."})
            return 1

        res = run_stability_md(
            spec["receptor_pdb"], lig, out_dir,
            relax_ps=float(spec.get("relax_ps", 2.0)),
            status=lambda m: print(f"[md] {m}", flush=True),
        )
        write(res)
        return 0 if not res.get("_error") else 1
    except Exception as e:
        write({"_error": f"{type(e).__name__}: {e}",
               "traceback": traceback.format_exc()[-1500:]})
        return 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: md_runner.py <spec.json>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
