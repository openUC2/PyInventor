#!/usr/bin/env python3
"""
Apply an optikit-fx.json changeset to Inventor fx (user) parameters (WP-35 T2).

This closes the optiland → Inventor loop: after optikit's `/v1/optimize` (or a
hand edit) writes a design's dof values, `optikit-core fx <design> -o
optikit-fx.json` emits a small changeset; this script consumes it on the
Inventor machine, sets the user parameters on the master-insert part of the
open assembly, selects T1 positional representations for `state` changes, and
optionally re-runs batch_iam_to_stp_glb.py so the STP/GLB match the optics.

Naming contract (openUC2-OptiKit/DOCS/inventor-naming-contract.md §fx):

- the Inventor USER PARAMETER NAME IS THE DOF NAME (`dz` in the template
  record ⇒ user parameter `dz` on the master-insert part). Units: mm.
- when the changeset carries a `groove` block (T2 groove-lattice templates)
  and the part declares `<name>_midpoint` / `<name>_delta` user parameters,
  those receive the decomposed pair midpoint and continuous δ instead of the
  raw value — the groove choice is physical (which grooves the holder
  clamps), only δ is a dimension.
- a change whose `parameter` is `state` selects the Inventor POSITIONAL
  REPRESENTATION named by `value` (T1 states, e.g. a mirror's XY ⇄ YZ).

ME-guide warning: parts/assemblies are cross-linked between Inventor designs —
ALWAYS work on a copied design, never edit a library master in place.

Usage:
  python apply_fx_params.py optikit-fx.json                 # apply to the open assembly
  python apply_fx_params.py optikit-fx.json --dry-run       # print what would change
  python apply_fx_params.py optikit-fx.json --export        # then re-export STP/GLB
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    from win32com.client import Dispatch, GetActiveObject
except ImportError:
    sys.exit("pywin32 not found. Install it with: pip install pywin32")

kAssemblyDocumentObject = 12291

#: Inventor's internal API unit is centimetres; the changeset speaks mm.
MM_PER_CM = 10.0


def connect_inventor() -> object:
    try:
        return GetActiveObject("Inventor.Application")
    except Exception:
        app = Dispatch("Inventor.Application")
        app.Visible = True
        return app


def active_assembly(app: object) -> object:
    doc = getattr(app, "ActiveDocument", None)
    if doc is None:
        sys.exit("No active document. Open the assembly the changeset targets.")
    if doc.DocumentType != kAssemblyDocumentObject:
        sys.exit("Active document is not an assembly — open the .iam.")
    return doc


def master_insert_occurrence(assembly_doc: object) -> object:
    """The MASINS occurrence — the T2 DOF carrier by the naming contract."""
    for occ in assembly_doc.ComponentDefinition.Occurrences:
        if "MASINS" in str(occ.Name).upper():
            return occ
    sys.exit(
        "No MASINS occurrence in the active assembly — a T2 changeset needs "
        "the master insert (see inventor-naming-contract.md)."
    )


def user_parameters(part_doc: object) -> object:
    return part_doc.ComponentDefinition.Parameters.UserParameters


def set_mm(params: object, name: str, value_mm: float, dry_run: bool) -> bool:
    """Set user parameter `name` to value_mm (stored in cm). False if absent."""
    try:
        param = params.Item(name)
    except Exception:
        return False
    if dry_run:
        print(f"  would set {name} = {value_mm} mm (was {param.Value * MM_PER_CM:.4g} mm)")
        return True
    param.Value = value_mm / MM_PER_CM
    print(f"  set {name} = {value_mm} mm")
    return True


def select_state(assembly_doc: object, state: str, dry_run: bool) -> None:
    """Activate the positional representation named `state` (T1 amendment)."""
    reps = assembly_doc.ComponentDefinition.RepresentationsManager.PositionalRepresentations
    names = [str(reps.Item(i + 1).Name) for i in range(reps.Count)]
    if state not in names:
        sys.exit(f"positional representation {state!r} not found (have: {names})")
    if dry_run:
        print(f"  would activate positional representation {state!r}")
        return
    reps.Item(state).Activate()
    print(f"  activated positional representation {state!r}")


def apply_changeset(changeset: dict, args: argparse.Namespace) -> list[str]:
    app = connect_inventor()
    assembly_doc = active_assembly(app)
    touched: list[str] = []

    for change in changeset.get("changes", []):
        template_id = change.get("template-id")
        parameter = change.get("parameter", "")
        print(f"{change.get('component', '?')} ({template_id or 'unresolved template'}):")
        if template_id is None:
            print("  SKIP: optikit could not resolve the template — check the design")
            continue

        if parameter == "state":
            select_state(assembly_doc, str(change.get("value", "")), args.dry_run)
            touched.append(str(assembly_doc.FullFileName))
            continue

        occ = master_insert_occurrence(assembly_doc)
        part_doc = occ.Definition.Document
        params = user_parameters(part_doc)
        value_mm = float(change.get("value-mm", 0.0))
        groove = change.get("groove")

        applied = False
        if groove is not None:
            # Groove-lattice decomposition: dimensioned δ + informational
            # midpoint, when the master insert declares the split parameters.
            applied = set_mm(params, f"{parameter}_delta", float(groove["delta-mm"]), args.dry_run)
            set_mm(params, f"{parameter}_midpoint", float(groove["midpoint-mm"]), args.dry_run)
            if applied:
                print(f"  groove pair {groove['pair']} (clamp these grooves)")
        if not applied:
            applied = set_mm(params, parameter, value_mm, args.dry_run)
        if not applied:
            print(f"  SKIP: no user parameter {parameter!r} on {part_doc.DisplayName} "
                  "— fx name must equal the dof name")
            continue
        if not args.dry_run:
            part_doc.Update()
            assembly_doc.Update()
            part_doc.Save()
            assembly_doc.Save()
        touched.append(str(assembly_doc.FullFileName))

    return touched


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("changeset", help="optikit-fx.json from `optikit-core fx`")
    parser.add_argument("--dry-run", action="store_true", help="print, change nothing")
    parser.add_argument(
        "--export", action="store_true",
        help="re-run batch_iam_to_stp_glb.py for the touched assemblies",
    )
    args = parser.parse_args()

    data = json.loads(Path(args.changeset).read_text(encoding="utf-8"))
    if data.get("schema") != "optikit-fx/v0":
        sys.exit(f"not an optikit-fx/v0 changeset: {data.get('schema')!r}")

    touched = apply_changeset(data, args)
    print(f"{len(touched)} assembly update(s)")

    if args.export and touched and not args.dry_run:
        # batch_iam_to_stp_glb.py exports a FOLDER of .iam files — re-export
        # each touched assembly's folder with --overwrite so stale STP/GLB
        # can't survive a parameter change.
        batch = Path(__file__).parent / "batch_iam_to_stp_glb.py"
        for folder in sorted({str(Path(iam).parent) for iam in touched}):
            print(f"re-exporting {folder}")
            subprocess.run(
                [sys.executable, str(batch), folder, "--overwrite"], check=True
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
