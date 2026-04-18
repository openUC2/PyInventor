#!/usr/bin/env python3
"""
Batch export all Inventor assembly (.iam) files in a folder to STEP (.stp),
then convert each STEP file to GLB using cascadio.

Requirements:
  - Autodesk Inventor must be installed and licensed
  - pip install cascadio

Usage:
  python batch_iam_to_stp_glb.py <iam_folder> [stp_output_folder] [glb_output_folder]
                                  [--tol-linear 0.1] [--tol-angular 0.5] [--overwrite]

Examples:
  python batch_iam_to_stp_glb.py C:\\CAD\\Assemblies
  python batch_iam_to_stp_glb.py C:\\CAD\\Assemblies C:\\Export\\STP C:\\Export\\GLB --overwrite

  python batch_iam_to_stp_glb.py   C:\\Users\\benir\\Documents\\openUC2-CAD-new\\workspace\\ASS C:\\Users\\benir\\Documents\\openUC2-CAD-EXPORT\\STP\\ASS C:\\Users\\benir\\Documents\\openUC2-CAD-EXPORT\\GLB --overwrite


"""

import argparse
import sys
from pathlib import Path

try:
    import cascadio
except ImportError:
    sys.exit("cascadio not found. Install it with: pip install cascadio")

try:
    from win32com.client import Dispatch, GetActiveObject
except ImportError:
    sys.exit("pywin32 not found. Install it with: pip install pywin32")


def _connect_inventor() -> object:
    """Return a live Inventor.Application COM object."""
    try:
        return GetActiveObject("Inventor.Application")
    except Exception:
        app = Dispatch("Inventor.Application")
        app.Visible = True
        return app


# ---------------------------------------------------------------------------
# STEP export
# ---------------------------------------------------------------------------

def export_iam_to_stp(
    iam_folder: Path,
    stp_folder: Path,
    overwrite: bool = False,
) -> list[Path]:
    """Open every .iam in *iam_folder* with Inventor and save a copy as .stp.

    Uses direct Inventor COM calls (no PyInventor wrapper) so a single
    bad file cannot corrupt the COM connection for subsequent files.

    Returns a list of paths to the successfully exported STP files.
    """
    iam_files = sorted(iam_folder.glob("*.iam"))
    if not iam_files:
        print(f"No .iam files found in: {iam_folder}")
        return []

    stp_folder.mkdir(parents=True, exist_ok=True)

    print("Connecting to Autodesk Inventor ...", flush=True)
    inv_app = _connect_inventor()
    try:
        inv_app.SilentOperation = True
    except Exception:
        pass

    exported: list[Path] = []
    success, skipped, failed = 0, 0, 0

    for iam_file in iam_files:
        stp_file = stp_folder / (iam_file.stem + ".stp")

        if stp_file.exists() and not overwrite:
            print(f"  [skip]    {iam_file.name}  →  STP already exists")
            skipped += 1
            exported.append(stp_file)
            continue

        print(f"  [export]  {iam_file.name}  →  {stp_file.name} ...", end=" ", flush=True)
        doc = None
        try:
            doc = inv_app.Documents.Open(str(iam_file))
            # SaveAs(Filename, SaveCopyAs=True) — file type is inferred from extension
            doc.SaveAs(str(stp_file), True)
            print("ok")
            success += 1
            exported.append(stp_file)
        except Exception as exc:
            print(f"FAILED  ({exc})")
            failed += 1
        finally:
            if doc is not None:
                try:
                    doc.Close(True)  # SkipSave=True
                except Exception:
                    pass

    try:
        inv_app.SilentOperation = False
    except Exception:
        pass

    print(f"\nSTP export: {success} exported, {skipped} skipped, {failed} failed.\n")
    return exported


# ---------------------------------------------------------------------------
# GLB conversion
# ---------------------------------------------------------------------------

def convert_stp_to_glb(
    stp_files: list[Path],
    glb_folder: Path,
    tol_linear: float = 0.1,
    tol_angular: float = 0.5,
    overwrite: bool = False,
) -> None:
    """Convert a list of STP files to GLB using cascadio."""
    if not stp_files:
        print("No STP files to convert.")
        return

    glb_folder.mkdir(parents=True, exist_ok=True)

    success, skipped, failed = 0, 0, 0

    for stp_file in stp_files:
        glb_file = glb_folder / (stp_file.stem.replace(" ", "_") + ".glb")

        if glb_file.exists() and not overwrite:
            print(f"  [skip]    {stp_file.name}  →  GLB already exists")
            skipped += 1
            continue

        print(f"  [convert] {stp_file.name}  →  {glb_file.name} ...", end=" ", flush=True)
        try:
            cascadio.step_to_glb(str(stp_file), str(glb_file), tol_linear, tol_angular)
            print("ok")
            success += 1
        except Exception as exc:
            print(f"FAILED  ({exc})")
            failed += 1

    print(f"\nGLB conversion: {success} converted, {skipped} skipped, {failed} failed.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Batch export Inventor assemblies (.iam) to STEP, "
            "then convert STEP to GLB using cascadio."
        )
    )
    parser.add_argument(
        "iam_folder",
        type=Path,
        help="Folder containing .iam assembly files.",
    )
    parser.add_argument(
        "stp_folder",
        nargs="?",
        type=Path,
        default=None,
        help="Output folder for .stp files (default: <iam_folder>/STP).",
    )
    parser.add_argument(
        "glb_folder",
        nargs="?",
        type=Path,
        default=None,
        help="Output folder for .glb files (default: <iam_folder>/GLB).",
    )
    parser.add_argument(
        "--tol-linear",
        type=float,
        default=0.1,
        metavar="F",
        help="Linear tessellation tolerance for GLB (default: 0.1). Lower = finer mesh.",
    )
    parser.add_argument(
        "--tol-angular",
        type=float,
        default=0.5,
        metavar="F",
        help="Angular tessellation tolerance in radians for GLB (default: 0.5).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-export / re-convert files even if outputs already exist.",
    )
    parser.add_argument(
        "--stp-only",
        action="store_true",
        help="Only export to STP; skip GLB conversion.",
    )

    args = parser.parse_args()

    iam_folder = args.iam_folder.resolve()
    if not iam_folder.is_dir():
        sys.exit(f"Input path is not a directory: {iam_folder}")

    stp_folder = (args.stp_folder or iam_folder / "STP").resolve()
    glb_folder = (args.glb_folder or iam_folder / "GLB").resolve()

    print(f"IAM source : {iam_folder}")
    print(f"STP output : {stp_folder}")
    if not args.stp_only:
        print(f"GLB output : {glb_folder}")
        print(f"Tolerances — linear: {args.tol_linear}, angular: {args.tol_angular}")
    print()

    # Step 1: export IAM → STP
    stp_files = export_iam_to_stp(iam_folder, stp_folder, args.overwrite)

    # Step 2: convert STP → GLB
    if not args.stp_only:
        convert_stp_to_glb(stp_files, glb_folder, args.tol_linear, args.tol_angular, args.overwrite)


if __name__ == "__main__":
    main()
