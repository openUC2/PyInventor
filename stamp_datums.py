#!/usr/bin/env python3
"""
Stamp and validate openUC2 optical datum markers on an open Inventor assembly.

Datum markers tell optikit where a component's optical surfaces, axis and clear
aperture actually are, instead of letting the GLB importer guess from part
origins. The naming contract is
openUC2-OptiKit/DOCS/inventor-naming-contract.md.

Why markers and not work planes
-------------------------------
Inventor work planes/axes/points DO NOT SURVIVE EXPORT. They are construction
geometry: the STEP translator never writes them, and neither cascadio nor
Inventor's own glTF translator emits a node for them. A datum therefore has to
be real geometry to reach optikit -- a tiny, dedicated marker PART, placed as an
occurrence whose name carries the datum name.

The occurrence rule is not style: body names are lost in GLB conversion (OCCT
collapses a multi-body part to a single node), while occurrence names survive
with their full transform. `--validate` checks for exactly this mistake.

Usage:
  python stamp_datums.py --validate                  # check the active assembly
  python stamp_datums.py --init-lib [DIR]            # generate the marker parts
  python stamp_datums.py --from-work-features        # work features -> markers
  python stamp_datums.py --validate --strict         # exit 1 on any violation

Examples:
  # Model with work planes as usual, then convert them to real markers:
  python stamp_datums.py --init-lib
  python stamp_datums.py --from-work-features
  python stamp_datums.py --validate
"""

import argparse
import math
import re
import sys
from pathlib import Path

try:
    from win32com.client import Dispatch, GetActiveObject
except ImportError:
    sys.exit("pywin32 not found. Install it with: pip install pywin32")

# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

kPartDocumentObject = 12290
kAssemblyDocumentObject = 12291
kJoinOperation = 20481
kPositiveExtentDirection = 20993

#: Inventor's internal API unit is centimetres; the contract speaks millimetres.
MM_PER_CM = 10.0

#: An AXIS marker further than this from any cube axis is a modelling error.
AXIS_TOL_DEG = 20.0
#: Beyond this it is merely flagged for review.
AXIS_WARN_DEG = 1.0

MARKER_PARTS = {
    "PLN": "DATUM-DISC.ipt",
    "AXIS": "DATUM-AXIS.ipt",
    "PT": "DATUM-PT.ipt",
}

_PREFIX_RE = re.compile(r"^(PLN|AXIS|PT)\b")
_PLN_RE = re.compile(r"^PLN\s*-\s*([A-Za-z0-9]+)\s*-\s*(.+)$")
_AXIS_RE = re.compile(r"^AXIS\s*-\s*([A-Za-z0-9]+)\s*$")
_PT_RE = re.compile(r"^PT\s*-\s*(.+)$")

_AXES = {
    "+x": (1.0, 0.0, 0.0), "-x": (-1.0, 0.0, 0.0),
    "+y": (0.0, 1.0, 0.0), "-y": (0.0, -1.0, 0.0),
    "+z": (0.0, 0.0, 1.0), "-z": (0.0, 0.0, -1.0),
}


def marker_kind(name: str) -> str:
    """'PLN' / 'AXIS' / 'PT' for a datum-marker name, else ''."""
    m = _PREFIX_RE.match(name.strip())
    return m.group(1) if m else ""


def check_marker_name(name: str) -> str:
    """'' if the name matches the contract, else why it does not."""
    kind = marker_kind(name)
    if kind == "PLN" and not _PLN_RE.match(name.strip()):
        return "expected 'PLN - <ROLE> - <frame>'"
    if kind == "AXIS" and not _AXIS_RE.match(name.strip()):
        return "expected 'AXIS - <ROLE>'"
    if kind == "PT" and not _PT_RE.match(name.strip()):
        return "expected 'PT - <name>'"
    return ""


def snap_axis(vec: tuple[float, float, float]) -> tuple[str, float]:
    """Nearest cube axis to *vec*, and the angle (deg) discarded by snapping."""
    length = math.sqrt(sum(v * v for v in vec)) or 1.0
    unit = [v / length for v in vec]
    best, best_dot = "+z", -2.0
    for label, axis in _AXES.items():
        dot = sum(u * a for u, a in zip(unit, axis))
        if dot > best_dot:
            best, best_dot = label, dot
    return best, math.degrees(math.acos(min(1.0, max(-1.0, best_dot))))


# ---------------------------------------------------------------------------
# Inventor session
# ---------------------------------------------------------------------------

def connect_inventor() -> object:
    """Return a live Inventor.Application COM object."""
    try:
        return GetActiveObject("Inventor.Application")
    except Exception:
        app = Dispatch("Inventor.Application")
        app.Visible = True
        return app


def active_assembly(app: object) -> object:
    """The active document, insisting it is an assembly."""
    try:
        doc = app.ActiveDocument
    except Exception:
        sys.exit("No active document. Open the assembly you want to stamp.")
    if doc is None:
        sys.exit("No active document. Open the assembly you want to stamp.")
    if doc.DocumentType != kAssemblyDocumentObject:
        sys.exit(
            f"Active document is not an assembly (DocumentType={doc.DocumentType}). "
            "Datum markers are placed occurrences, so open the .iam."
        )
    return doc


# ---------------------------------------------------------------------------
# Marker part library
# ---------------------------------------------------------------------------

def init_marker_library(app: object, folder: Path) -> None:
    """Generate the three marker parts if they are not already there.

    The disc is created at 1 mm diameter; scale it to the real clear aperture
    per placement, because the disc's diameter IS the clear aperture optikit
    reads (see the contract).
    """
    folder.mkdir(parents=True, exist_ok=True)
    tmpl = app.FileManager.GetTemplateFile(kPartDocumentObject)
    tg = app.TransientGeometry

    specs = [
        ("DATUM-DISC.ipt", "circle", 0.05, 0.01),   # r = 0.5 mm, 0.1 mm thick
        ("DATUM-AXIS.ipt", "circle", 0.005, 0.5),   # r = 0.05 mm, 5 mm long rod
        ("DATUM-PT.ipt", "circle", 0.01, 0.02),     # r = 0.1 mm, 0.2 mm tall
    ]
    for filename, _shape, radius_cm, depth_cm in specs:
        path = folder / filename
        if path.exists():
            print(f"  [skip]  {filename} already exists")
            continue
        doc = app.Documents.Add(kPartDocumentObject, tmpl, True)
        try:
            cd = doc.ComponentDefinition
            sk = cd.Sketches.Add(cd.WorkPlanes.Item(3))  # XY
            sk.SketchCircles.AddByCenterRadius(tg.CreatePoint2d(0, 0), radius_cm)
            prof = sk.Profiles.AddForSolid()
            ed = cd.Features.ExtrudeFeatures.CreateExtrudeDefinition(prof, kJoinOperation)
            ed.SetDistanceExtent(depth_cm, kPositiveExtentDirection)
            cd.Features.ExtrudeFeatures.Add(ed)
            doc.SaveAs(str(path), False)
            print(f"  [make]  {filename}")
        finally:
            doc.Close(True)


# ---------------------------------------------------------------------------
# Stamping
# ---------------------------------------------------------------------------

def place_marker(
    app: object, asm: object, part: Path, name: str,
    origin_cm: tuple[float, float, float],
    normal: tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> object:
    """Place *part* as an occurrence named *name*, +z aligned to *normal*."""
    tg = app.TransientGeometry
    m = tg.CreateMatrix()
    # NB: the method is SetToRotateTo / SetToRotation -- there is no SetRotation.
    try:
        m.SetToRotateTo(tg.CreateVector(0.0, 0.0, 1.0), tg.CreateVector(*normal))
    except Exception:
        pass  # already +z aligned
    m.SetTranslation(tg.CreateVector(*origin_cm))
    occ = asm.ComponentDefinition.Occurrences.Add(str(part), m)
    occ.Name = name
    return occ


def markers_from_work_features(app: object, doc: object, lib: Path) -> int:
    """Turn work features named per the contract into real marker occurrences.

    This is the bridge for the natural authoring habit: model with work planes
    and work points, then convert them into geometry that actually exports.
    """
    cd = doc.ComponentDefinition
    made = 0

    for wp in cd.WorkPlanes:
        name = (wp.Name or "").strip()
        if marker_kind(name) != "PLN":
            continue
        try:
            plane = wp.Plane
            root, normal = plane.RootPoint, plane.Normal
        except Exception as exc:
            print(f"  [skip]  {name!r}: cannot read its plane ({exc})")
            continue
        place_marker(
            app, doc, lib / MARKER_PARTS["PLN"], name,
            (root.X, root.Y, root.Z), (normal.X, normal.Y, normal.Z),
        )
        print(f"  [make]  {name!r} from work plane")
        made += 1

    for wpt in cd.WorkPoints:
        name = (wpt.Name or "").strip()
        if marker_kind(name) != "PT":
            continue
        try:
            p = wpt.Point
        except Exception as exc:
            print(f"  [skip]  {name!r}: cannot read its point ({exc})")
            continue
        place_marker(app, doc, lib / MARKER_PARTS["PT"], name, (p.X, p.Y, p.Z))
        print(f"  [make]  {name!r} from work point")
        made += 1

    for wa in cd.WorkAxes:
        name = (wa.Name or "").strip()
        if marker_kind(name) != "AXIS":
            continue
        try:
            line = wa.Line
            root, direction = line.RootPoint, line.Direction
        except Exception as exc:
            print(f"  [skip]  {name!r}: cannot read its axis ({exc})")
            continue
        place_marker(
            app, doc, lib / MARKER_PARTS["AXIS"], name,
            (root.X, root.Y, root.Z), (direction.X, direction.Y, direction.Z),
        )
        print(f"  [make]  {name!r} from work axis")
        made += 1

    return made


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _occurrence_markers(cd: object) -> list[tuple[str, object]]:
    return [
        (occ.Name.strip(), occ)
        for occ in cd.Occurrences
        if marker_kind((occ.Name or "").strip())
    ]


def _body_named_like_a_marker(cd: object) -> list[str]:
    """Marker-looking names on BODIES -- the silent-data-loss mistake.

    Body names reach the STEP file but are dropped in GLB conversion, so such a
    'marker' vanishes with no error anywhere. Worth its own check.
    """
    offenders: list[str] = []
    for occ in cd.Occurrences:
        try:
            sub = occ.Definition.SurfaceBodies
        except Exception:
            continue
        for i in range(1, sub.Count + 1):
            try:
                name = (sub.Item(i).Name or "").strip()
            except Exception:
                continue
            if marker_kind(name):
                offenders.append(f"{occ.Name} / body {name!r}")
    return offenders


def validate(doc: object) -> list[str]:
    """Every way the active assembly departs from the datum contract."""
    cd = doc.ComponentDefinition
    violations: list[str] = []
    markers = _occurrence_markers(cd)

    print(f"\nDatum markers found: {len(markers)}")
    for name, _occ in markers:
        print(f"  {name}")

    # 1. names must parse
    for name, _occ in markers:
        why = check_marker_name(name)
        if why:
            violations.append(f"{name!r}: malformed - {why}")

    # 2. duplicate frame keys
    seen: dict[str, int] = {}
    for name, _occ in markers:
        seen[name] = seen.get(name, 0) + 1
    for name, count in seen.items():
        if count > 1:
            violations.append(f"{name!r}: appears {count} times - names must be unique")

    # 3. the required set
    kinds = [marker_kind(n) for n, _ in markers]
    if "PLN" not in kinds:
        violations.append(
            "no PLN marker - optikit will fall back to the BUY node origin and "
            "flag the record for review; add 'PLN - OPT - optical'"
        )
    if "AXIS" not in kinds:
        violations.append(
            "no AXIS marker - the beam direction will be assumed +z; add 'AXIS - OPT'"
        )

    # 4. axis alignment
    for name, occ in markers:
        if marker_kind(name) != "AXIS":
            continue
        try:
            m = occ.Transformation
            normal = (m.Cell(1, 3), m.Cell(2, 3), m.Cell(3, 3))  # local +z in the parent
        except Exception as exc:
            violations.append(f"{name!r}: cannot read its transform ({exc})")
            continue
        axis, err = snap_axis(normal)
        if err > AXIS_TOL_DEG:
            violations.append(
                f"{name!r}: {err:.1f} deg from {axis} - not aligned to any cube axis; "
                "optikit cannot represent this beam"
            )
        elif err > AXIS_WARN_DEG:
            print(f"  note: {name!r} is {err:.1f} deg off {axis} (snapped; within tolerance)")

    # 5. the body mistake
    for offender in _body_named_like_a_marker(cd):
        violations.append(
            f"{offender}: a marker named on a BODY is lost in GLB export - "
            "it must be a placed part occurrence"
        )

    return violations


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stamp and validate openUC2 optical datum markers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--validate", action="store_true",
                        help="check the active assembly against the contract (default)")
    parser.add_argument("--init-lib", nargs="?", const="", metavar="DIR",
                        help="generate the marker parts into DIR")
    parser.add_argument("--from-work-features", action="store_true",
                        help="convert contract-named work features into marker occurrences")
    parser.add_argument("--marker-lib", type=Path, default=None,
                        help="folder holding DATUM-*.ipt (default: ./datum-markers)")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 if there are any violations")
    args = parser.parse_args()

    lib = args.marker_lib or Path.cwd() / "datum-markers"
    app = connect_inventor()
    print(f"Inventor: {app.SoftwareVersion.DisplayName}")

    if args.init_lib is not None:
        folder = Path(args.init_lib) if args.init_lib else lib
        print(f"\nMarker library -> {folder}")
        init_marker_library(app, folder)
        if not args.from_work_features and not args.validate:
            return 0

    doc = active_assembly(app)
    print(f"Assembly: {doc.DisplayName}")

    if args.from_work_features:
        if not lib.exists():
            sys.exit(f"Marker library not found: {lib}\nRun --init-lib first.")
        print("\nConverting work features to markers ...")
        made = markers_from_work_features(app, doc, lib)
        print(f"{made} marker(s) placed.")

    violations = validate(doc)
    if violations:
        print(f"\n{len(violations)} violation(s):", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1 if args.strict else 0

    print("\nNo violations - the assembly satisfies the datum contract.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
