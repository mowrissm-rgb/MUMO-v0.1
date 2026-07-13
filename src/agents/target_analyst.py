"""
MUMO Agent — Target Analyst
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

WHAT THIS AGENT DOES (plain English)
------------------------------------
This is the BRIDGE between "I know the gene" and "I can dock."
You give it a gene (e.g. 'CFTR'). It:
    1. Finds the protein's UniProt ID            (CFTR -> P13569)
    2. Downloads its 3D structure from AlphaFold  (a real .pdb file)
    3. Reads UniProt's annotated active/binding site residues
    4. Places a docking GRID BOX over that active site
       (if the protein has no annotated site, it falls back to a box over the
        whole protein — "blind docking")

Output = everything the Docking Engine needs: a .pdb file + a grid box.
No API key. No install. Pure Python + free public databases.
"""

import os
import requests

UNIPROT_SEARCH = "https://rest.uniprot.org/uniprotkb/search"
UNIPROT_ENTRY  = "https://rest.uniprot.org/uniprotkb/{acc}.json"
ALPHAFOLD_API  = "https://alphafold.ebi.ac.uk/api/prediction/{acc}"


def gene_to_uniprot(gene, organism_id=9606):
    """Step 1: gene symbol -> reviewed (Swiss-Prot) UniProt accession for human."""
    params = {
        "query": f"gene_exact:{gene} AND organism_id:{organism_id} AND reviewed:true",
        "fields": "accession,id,protein_name",
        "format": "json",
        "size": 1,
    }
    r = requests.get(UNIPROT_SEARCH, params=params, timeout=30)
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results:
        raise ValueError(f"No reviewed human UniProt entry found for gene '{gene}'.")
    return results[0]["primaryAccession"]


def download_alphafold(acc, out_dir):
    """
    Step 2: download the AlphaFold 3D model (.pdb) for this accession.
    We ask AlphaFold's API for the current file URL, so this never breaks when
    they bump the model version (v4 -> v6 -> ...).
    """
    os.makedirs(out_dir, exist_ok=True)
    info = requests.get(ALPHAFOLD_API.format(acc=acc), timeout=30)
    if info.status_code != 200 or not info.json():
        raise FileNotFoundError(f"No AlphaFold model available for {acc}.")
    pdb_url = info.json()[0]["pdbUrl"]

    pdb_path = os.path.join(out_dir, f"AF_{acc}.pdb")
    r = requests.get(pdb_url, timeout=60)
    r.raise_for_status()
    with open(pdb_path, "wb") as f:
        f.write(r.content)
    return pdb_path


def get_active_site_residues(acc):
    """
    Step 3: ask UniProt which residue numbers are the active/binding site.
    Returns a list of residue position integers (may be empty).
    """
    r = requests.get(UNIPROT_ENTRY.format(acc=acc), timeout=30)
    r.raise_for_status()
    features = r.json().get("features", [])
    wanted = {"Active site", "Binding site"}
    positions = []
    for ft in features:
        if ft.get("type") in wanted:
            loc = ft.get("location", {})
            start = loc.get("start", {}).get("value")
            end = loc.get("end", {}).get("value", start)
            if start is not None:
                positions.extend(range(int(start), int(end) + 1))
    return sorted(set(positions))


def _read_ca_coords(pdb_path):
    """Read alpha-carbon (CA) coordinates per residue number from a PDB file."""
    coords = {}   # residue_number -> (x, y, z)
    all_atoms = []
    with open(pdb_path) as f:
        for line in f:
            if line.startswith("ATOM"):
                x = float(line[30:38]); y = float(line[38:46]); z = float(line[46:54])
                all_atoms.append((x, y, z))
                if line[12:16].strip() == "CA":
                    resnum = int(line[22:26])
                    coords[resnum] = (x, y, z)
    return coords, all_atoms


def _box_from_points(points, padding=5.0, min_size=16.0, max_size=22.0):
    """Given some 3D points, return (center, size) of a cube that wraps them.
    Kept TIGHT (focused docking) — a smaller search box is dramatically faster in
    Vina (time scales with box volume) and, for a well-centred pocket, just as
    accurate. Widen only for blind docking."""
    xs = [p[0] for p in points]; ys = [p[1] for p in points]; zs = [p[2] for p in points]
    center = (
        round(sum(xs) / len(xs), 3),
        round(sum(ys) / len(ys), 3),
        round(sum(zs) / len(zs), 3),
    )
    span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    size = max(min_size, min(max_size, span + padding))
    return center, (round(size, 1), round(size, 1), round(size, 1))


def detect_pocket(all_atoms, spacing=1.8, burial_R=10.0, burial_min=0.66,
                  link=3.2, min_pts=12, pad=5.0, min_size=16.0, max_size=22.0):
    """
    Geometric binding-pocket detection (LIGSITE / burial style — pure numpy + scipy,
    permissive licences). Replaces weak "blind docking over the whole protein" when
    there is no co-crystal ligand and no annotated site.

    How: lay a grid over the protein; keep grid points that are EMPTY (not inside an
    atom) yet ENCLOSED by protein on most sides — a real cavity, not open surface
    (measured by how evenly the surrounding atoms wrap the point). Cluster those
    points; box the largest pocket. Returns (center, size) or None (→ caller falls
    back) when nothing convincing is found. Validated on 6LU7: centre lands ~3.7 Å
    from the true inhibitor site.
    """
    try:
        import numpy as np
        from scipy.spatial import cKDTree
    except Exception:
        return None
    pts = np.asarray(all_atoms, dtype=float)
    if len(pts) < 100:
        return None
    tree = cKDTree(pts)
    lo, hi = pts.min(0) - 3, pts.max(0) + 3
    grid = np.stack(np.meshgrid(
        np.arange(lo[0], hi[0], spacing), np.arange(lo[1], hi[1], spacing),
        np.arange(lo[2], hi[2], spacing), indexing="ij"), -1).reshape(-1, 3)
    dn, _ = tree.query(grid, k=1)
    empty = grid[(dn > 2.6) & (dn < 4.5)]                 # empty but near the surface
    if len(empty) < min_pts:
        return None
    nb = tree.query_ball_point(empty, burial_R)
    bur = np.zeros(len(empty))
    for i, idx in enumerate(nb):
        if len(idx) < 8:
            continue
        v = pts[idx] - empty[i]
        v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
        bur[i] = 1 - np.linalg.norm(v.mean(0))            # ~1 enclosed, ~0 open surface
    pk = empty[bur >= burial_min]
    if len(pk) < min_pts:
        return None
    bt = cKDTree(pk)
    nn = bt.query_ball_tree(bt, link)
    seen = [False] * len(pk)
    best = []
    for i in range(len(pk)):
        if seen[i]:
            continue
        stack, comp = [i], []
        while stack:
            j = stack.pop()
            if seen[j]:
                continue
            seen[j] = True
            comp.append(j)
            stack.extend(nn[j])
        if len(comp) > len(best):
            best = comp
    if len(best) < min_pts:
        return None
    cl = pk[best]
    center = tuple(round(float(c), 3) for c in cl.mean(0))
    span = float((cl.max(0) - cl.min(0)).max())
    size = max(min_size, min(max_size, span + pad))
    return center, (round(size, 1), round(size, 1), round(size, 1))


# Things in a PDB that are NOT the drug: water, ions, common crystallisation junk.
_NOT_LIGAND = {
    "HOH", "WAT", "SOL", "DOD", "TIP", "CL", "NA", "K", "MG", "CA", "ZN", "MN",
    "SO4", "PO4", "ACT", "GOL", "EDO", "PEG", "DMS", "IOD", "BR", "FMT", "NO3",
}


def auto_grid_from_pdb(pdb_path, padding=5.0, min_size=16.0, max_size=22.0):
    """
    Automatic grid box for ANY PDB file (uploaded or fetched by ID).
    Strategy:
      1. If the structure has a co-crystallised ligand (a HETATM group that is not
         water/ion/buffer), centre the box on that ligand — the real binding site.
      2. Otherwise fall back to a box over the whole protein ('blind docking').
    Returns (center, size, source_description).
    """
    all_atoms = []
    het_groups = {}    # (resname, chain, resnum) -> list of (x,y,z)
    with open(pdb_path) as f:
        for line in f:
            if line.startswith(("ATOM", "HETATM")):
                try:
                    xyz = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
                except ValueError:
                    continue
                all_atoms.append(xyz)
                if line.startswith("HETATM"):
                    resn = line[17:20].strip()
                    if resn not in _NOT_LIGAND:
                        key = (resn, line[21], line[22:26].strip())
                        het_groups.setdefault(key, []).append(xyz)

    if het_groups:
        # biggest hetero group = the bound ligand (most reliable box)
        (resn, _, _), atoms = max(het_groups.items(), key=lambda kv: len(kv[1]))
        center, size = _box_from_points(atoms, padding, min_size, max_size)
        return center, size, f"co-crystal ligand '{resn}' ({len(atoms)} atoms)"

    pocket = detect_pocket(all_atoms)                     # geometric pocket detection
    if pocket:
        center, size = pocket
        return center, size, "geometric pocket detection"

    center, size = _box_from_points(all_atoms, padding=0, min_size=22, max_size=max_size)
    return center, size, "blind docking (no bound ligand / pocket found)"


def analyze_target(gene, out_dir):
    """
    Full bridge: gene -> {pdb_path, center, size, accession, pocket_source}.
    'pocket_source' tells you whether we used the real active site or fell back.
    """
    acc = gene_to_uniprot(gene)
    pdb_path = download_alphafold(acc, out_dir)
    ca_coords, all_atoms = _read_ca_coords(pdb_path)

    site_residues = get_active_site_residues(acc)
    site_points = [ca_coords[r] for r in site_residues if r in ca_coords]

    if site_points:
        center, size = _box_from_points(site_points)
        pocket_source = f"UniProt active/binding site ({len(site_points)} residues)"
    else:
        pocket = detect_pocket(all_atoms)                 # geometric pocket detection
        if pocket:
            center, size = pocket
            pocket_source = "geometric pocket detection"
        else:
            # last resort: blind docking — box over the whole protein.
            center, size = _box_from_points(all_atoms, padding=0, min_size=22, max_size=30)
            pocket_source = "blind docking (no annotated site / pocket)"

    return {
        "accession": acc,
        "pdb_path": pdb_path,
        "center": center,
        "size": size,
        "pocket_source": pocket_source,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DEMO — run live for CFTR (Project 2) and CHRM3 (Project 1 bronchitis target)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    for gene in ["CFTR", "CHRM3"]:
        print("=" * 64)
        print(f"MUMO TARGET ANALYST — gene: {gene}")
        print("=" * 64)
        try:
            info = analyze_target(gene, out)
            print(f"UniProt accession : {info['accession']}")
            print(f"Structure (PDB)   : {os.path.basename(info['pdb_path'])}")
            print(f"Pocket source     : {info['pocket_source']}")
            print(f"Grid box center   : {info['center']}")
            print(f"Grid box size (A) : {info['size']}")
        except Exception as e:
            print(f"[Error] {e}")
        print()
