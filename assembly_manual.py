#!/usr/bin/env python3
"""Assembly instructions as PDF, straight from an Inventor assembly.

    python assembly_manual.py "ASS - 2067 - CUBLENASP20- V04.iam" --out MANUALS
    python assembly_manual.py <folder> --pattern "ASS - 20*.iam" --out MANUALS
    python assembly_manual.py --kit "KIT - CORE - COR-25-02.iam" --out MANUALS
    python assembly_manual.py --kit "C:\\Users\\benir\\Documents\\openUC2-CAD-new\\workspace\\KIT\\HOLO\\KIT - HOLO - HOL-26-02" --out MANUALS
For every module it writes ``<stem>.pdf`` (and ``<stem>.manual.json``):

  * page 1 - the exploded view with balloons and the parts list (BAUTEILLISTE)
    on the openUC2 A3 sheet, like the hand-made presentation drawings (a list
    too long for that page gets its own page with the finished module);
  * then one page per assembly step, IKEA style: big step number, the parts
    that go in (with quantity and parts-list item), and a picture where what
    is already assembled sits in place and the new parts hover along the
    direction they go in, with arrows.

How the explosion is found (no presentation file is needed): every part is
meshed, ``explode_plan`` works out which part blocks which along +-X/Y/Z and
takes the module apart around its grounded part, one round at a time;
reversed, that is the assembly order. ``SUB - ...`` / ``ASS - ...``
sub-assemblies (the "virt ass" pre-assemblies) become their own steps first;
bought assemblies (BUY, ELE, purchased) stay in one piece.

Nothing in the workspace is changed. The pictures are small throw-away
assemblies of the same parts (placed by definition, so model states and
appearance overrides carry over) saved in a work folder, which is deleted
afterwards unless ``--keep-drawing`` is given; then the folder keeps the .idw
and its scene assemblies for touch-ups by hand.

Requirements: a running, licensed Autodesk Inventor (2025 tested) with the
project of the modules active; pywin32, numpy, scipy.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

try:
    import pythoncom
    import win32com.client
except ImportError:
    sys.exit("pywin32 not found. Install it with: pip install pywin32")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import explode_plan as ep  # noqa: E402
from export_assembly_components import (  # noqa: E402
    _console_safe, _nvm_put, collect_components, connect, find_open_document, safe, split_model_state,
)

# ---------------------------------------------------------------------------
# Inventor constants (RxInventor.tlb)
# ---------------------------------------------------------------------------

kAssemblyDocumentObject = 12291
kDrawingDocumentObject = 12292
kArbitraryViewOrientation = 10763
kStructured = 46593
kA3DrawingSheetSize = 9996
kLandscapePageOrientation = 10242
kPrintAllSheets = 14082
kFileBrowseIOMechanism = 13059
kContinuousLineType = 37633
kDashedLineType = 37634
kOverrideAppearance = 100609
kComponentOccurrenceAppearance = 100615
PDF_TRANSLATOR_ID = "{0AC6FD96-2F4D-42CE-8BE0-8AEA580399E4}"

VIEW_STYLES = {
    "shaded": 32259,         # kShadedDrawingViewStyle (like the hand-made drawings)
    "lines": 32258,          # kHiddenLineRemovedDrawingViewStyle (IKEA look)
    "shaded-lines": 32261,   # kShadedHiddenLineDrawingViewStyle
}
BOM_NAMES = {51969: "default", 51970: "normal", 51971: "phantom", 51972: "reference",
             51973: "purchased", 51974: "inseparable", 51975: "varies"}

#: Seen from front-left-top, Z up: the camera of the existing presentation drawings.
VIEW_FROM = np.array([-1.0, -1.0, 1.0])
#: Step pages may turn the module so that parts moving sideways come towards the reader.
VIEW_CANDIDATES = (VIEW_FROM, np.array([1.0, -1.0, 1.0]), np.array([-1.0, 1.0, 1.0]), np.array([1.0, 1.0, 1.0]))

# ---------------------------------------------------------------------------
# openUC2 naming rules
# ---------------------------------------------------------------------------

#: Sub-assemblies built in their own steps (the "virt ass" pre-assemblies, modules in modules).
GROUP_PREFIXES = ("SUB -", "ASS -", "MAS -")
#: Screws, pins, washers, nuts: their thread is modelled into the hole they sit in.
FASTENER_RE = re.compile(r"^(ISO|DIN|EN|STD)\b|screw|schraube|washer|scheibe|\bpin\b|stift|\bnut\b|mutter|"
                         r"threaded|gewinde|o-ring|bushing|buchse", re.I)
#: Stickers go on last, all on one page.
DECAL_RE = re.compile(r"sticker|aufkleber|\bSTK", re.I)

#: Sheet frame of the openUC2 A3 format (cm): drawing area and title block.
FRAME = (2.0, 1.0, 41.0, 28.7)
TITLE_BLOCK_TOP = 8.2
TITLE_BLOCK_LEFT = 23.0

NICE_SCALES = (10, 8, 6, 5, 4, 3, 2.5, 2, 1.5, 1.25, 1, 0.8, 2 / 3, 0.5, 0.4, 1 / 3, 0.25, 0.2,
               1 / 6, 0.125, 0.1, 1 / 15, 0.05)


def log(msg: str = "", end: str = "\n") -> None:
    print(msg, end=end, flush=True)


def xml_escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _decimal_separator() -> str:
    """Inventor parses numbers in formatted text with the Windows locale (0,42 in German)."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(8)
        ctypes.windll.kernel32.GetLocaleInfoW(0x0400, 0x0E, buf, 8)  # LOCALE_USER_DEFAULT, LOCALE_SDECIMAL
        return buf.value or "."
    except Exception:
        return "."


DECIMAL = _decimal_separator()


def num(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".").replace(".", DECIMAL)


def prop_get(obj, name: str, *args):
    """A parameterised property get (``view.DrawingCurves(occ)``) that late binding mis-dispatches."""
    ole = obj._oleobj_
    dispid = ole.GetIDsOfNames(name)
    raw = [a._oleobj_ if hasattr(a, "_oleobj_") else a for a in args]
    result = ole.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYGET, True, *raw)
    if isinstance(result, pythoncom.TypeIIDs[pythoncom.IID_IDispatch]):
        return win32com.client.Dispatch(result)
    return result


# ---------------------------------------------------------------------------
# Reading the module
# ---------------------------------------------------------------------------

@dataclass
class Occ:
    """One occurrence of the module's tree, in the module's frame (mm)."""
    key: str
    name: str
    full: str
    kind: str                     # part | assembly | virtual
    bom: str | None
    visible: bool
    suppressed: bool
    grounded: bool
    transform: np.ndarray         # 4x4, translation in mm
    part_number: str
    description: str
    com: object                   # the occurrence (proxy)
    definition_bom: str | None = None
    children: list = field(default_factory=list)

    @property
    def stem(self) -> str:
        return Path(split_model_state(self.full)[0]).stem if self.full else self.name


def _matrix(m) -> np.ndarray:
    out = np.array([[m.Cell(r, c) for c in range(1, 5)] for r in range(1, 5)], dtype=float)
    out[:3, 3] *= 10.0  # cm -> mm
    return out


def _iprop(doc, group: str, name: str) -> str:
    value = safe(lambda: doc.PropertySets.Item(group).Item(name).Value)
    return "" if value is None else str(value)


def read_tree(asm_doc) -> list[Occ]:
    def read(occs, parent_key: str) -> list[Occ]:
        out = []
        for i in range(1, occs.Count + 1):
            occ = occs.Item(i)
            name = safe(lambda: occ.Name) or f"occurrence {i}"
            key = f"{parent_key}/{name}"
            suppressed = bool(safe(lambda: occ.Suppressed))
            desc = safe(lambda: occ.ReferencedDocumentDescriptor)
            full = (safe(lambda: desc.FullDocumentName) if desc is not None else None) or ""
            is_asm = safe(lambda: occ.DefinitionDocumentType) == kAssemblyDocumentObject
            kind = "virtual" if not full else ("assembly" if is_asm else "part")
            source = safe(lambda: desc.ReferencedDocument) if desc is not None else safe(lambda: occ.Definition)
            node = Occ(
                key=key, name=name, full=full, kind=kind,
                bom=BOM_NAMES.get(safe(lambda: occ.BOMStructure)),
                visible=safe(lambda: occ.Visible) is not False, suppressed=suppressed,
                grounded=bool(safe(lambda: occ.Grounded)),
                transform=_matrix(occ.Transformation) if not suppressed else np.eye(4),
                part_number=_iprop(source, "Design Tracking Properties", "Part Number") if source is not None else "",
                description=_iprop(source, "Design Tracking Properties", "Description") if source is not None else "",
                com=occ,
                definition_bom=BOM_NAMES.get(safe(lambda: occ.Definition.BOMStructure)),
            )
            if is_asm and not suppressed:
                node.children = read(occ.SubOccurrences, key)
            out.append(node)
        return out

    return read(asm_doc.ComponentDefinition.Occurrences, "")


def occ_mesh(occ) -> list[tuple[np.ndarray, np.ndarray]]:
    """Facets of a part occurrence (proxy) in the module's frame, mm."""
    meshes = []
    bodies = safe(lambda: occ.SurfaceBodies)
    if bodies is None:
        return meshes
    for b in range(1, bodies.Count + 1):
        body = bodies.Item(b)
        if safe(lambda: body.Visible) is False:
            continue
        try:
            _vc, _fc, coords, _normals, idx = body.CalculateFacets(0.01)
        except Exception:
            continue
        if not coords:
            continue
        v = np.array(coords, dtype=float).reshape(-1, 3) * 10.0
        f = np.array(idx, dtype=np.int64).reshape(-1, 3) - 1
        meshes.append((v, f))
    return meshes


# ---------------------------------------------------------------------------
# Units and groups
# ---------------------------------------------------------------------------

@dataclass
class Unit:
    """Something placed in the pictures and counted in the parts list."""
    key: str
    occ: Occ
    drawn: bool                   # False: listed, never drawn (hidden, cable strand, no solid)
    why_hidden: str = ""

    @property
    def component(self) -> str:
        """Parts-list identity: one row per (file, model state)."""
        return self.occ.full or f"virtual:{self.occ.name}"


def is_wire(meshes) -> bool:
    if not meshes:
        return False
    v = np.vstack([m[0] for m in meshes])
    ext = np.sort(v.max(axis=0) - v.min(axis=0))
    return ext[2] > 60 and ext[2] > 25 * max(ext[1], 0.1)


def drop_detached(members: list, units: list[Unit]) -> list:
    """Small parts modelled far from the rest of their group (the connector at the
    end of a 25 cm strand) are listed but not drawn: they would shrink every picture."""
    if len(members) < 3:
        return members
    base = next(m for m in members if m.key == ep.choose_base(members))
    box = base.bbox
    diag = float(np.linalg.norm(box[1] - box[0]))
    limit = max(30.0, 0.75 * diag)
    kept = []
    for m in members:
        if isinstance(m, ep.Body) and m is not base:
            mb = m.bbox
            gap = np.maximum(0.0, np.maximum(mb[0] - box[1], box[0] - mb[1]))
            if float(np.linalg.norm(gap)) > limit and float(np.linalg.norm(mb[1] - mb[0])) < 0.5 * diag:
                unit = next(u for u in units if u.key == m.key)
                unit.drawn = False
                unit.why_hidden = f"modelled {float(np.linalg.norm(gap)):.0f} mm away from the rest (cable end?)"
                continue
        kept.append(m)
    return kept


def is_group(node: Occ) -> bool:
    return (node.kind == "assembly" and node.bom not in ("purchased", "inseparable")
            and node.name.startswith(GROUP_PREFIXES))


def build_model(tree: list[Occ], key: str, label: str) -> tuple[ep.Group, list[Unit], list[str]]:
    """The planner's groups and bodies, and every unit for the parts list."""
    units: list[Unit] = []
    notes: list[str] = []

    def collect_meshes(node: Occ) -> list:
        if node.kind == "part":
            return occ_mesh(node.com)
        out = []
        for c in node.children:
            if c.suppressed or not c.visible or c.bom == "reference":
                continue
            out.extend(collect_meshes(c))
        return out

    def walk(nodes: list[Occ], gkey: str, glabel: str, grounded: bool, info: dict) -> ep.Group:
        members = []
        for n in nodes:
            if n.suppressed:
                notes.append(f"{n.name}: suppressed, left out")
                continue
            if n.bom == "reference":
                notes.append(f"{n.name}: reference component, left out")
                continue
            if n.kind == "virtual":
                units.append(Unit(n.key, n, drawn=False, why_hidden="virtual component"))
                continue
            if is_group(n):
                g = walk(n.children, n.key, n.name, n.grounded, {"part": n.full})
                if g.members:
                    members.append(g)
                continue
            if not n.visible:
                units.append(Unit(n.key, n, drawn=False, why_hidden="hidden in the assembly"))
                continue
            meshes = collect_meshes(n)
            if not meshes:
                units.append(Unit(n.key, n, drawn=False, why_hidden="no solid body"))
                continue
            if is_wire(meshes):
                units.append(Unit(n.key, n, drawn=False, why_hidden="cable strand"))
                continue
            v = np.vstack([m[0] for m in meshes])
            offset, faces = 0, []
            for mv, mf in meshes:
                faces.append(mf + offset)
                offset += len(mv)
            text = f"{n.name} {n.description}"
            body = ep.Body(n.key, n.name, v, np.vstack(faces), grounded=n.grounded, info={
                "part": n.full,
                "fastener": bool(FASTENER_RE.search(n.name) or FASTENER_RE.search(n.description)),
                "decal": bool(DECAL_RE.search(text)),
            })
            members.append(body)
            units.append(Unit(n.key, n, drawn=True))
        members = drop_detached(members, units)
        return ep.Group(gkey, glabel, members, grounded=grounded, info=info)

    root = walk(tree, key, label, True, {"part": key})
    return root, units, notes


# ---------------------------------------------------------------------------
# Inventor session
# ---------------------------------------------------------------------------

class Session:
    """Silent, invisible work in the running Inventor; leaves it as found."""

    def __init__(self, app):
        self.app = app
        self.tg = app.TransientGeometry
        self.to = app.TransientObjects
        self.silent = safe(lambda: app.SilentOperation, False)
        self.screen = safe(lambda: app.ScreenUpdating, True)
        self.loaded_before = {safe(lambda d=d: d.FullDocumentName) for d in app.Documents}
        project = safe(lambda: app.DesignProjectManager.ActiveDesignProject)
        self.project = safe(lambda: project.FullFileName) or ""
        self.templates = Path(safe(lambda: project.TemplatesPath) or ".")

    def __enter__(self):
        safe(lambda: setattr(self.app, "SilentOperation", True))
        return self

    def __exit__(self, *exc):
        self.release()
        safe(lambda: setattr(self.app, "ScreenUpdating", self.screen))
        safe(lambda: setattr(self.app, "SilentOperation", self.silent))
        return False

    def release(self) -> None:
        """Close what this run loaded and nothing references any more."""
        for _ in range(6):
            closed = 0
            for doc in list(self.app.Documents):
                name = safe(lambda: doc.FullDocumentName)
                if name in self.loaded_before or safe(lambda: doc.Views.Count, 1) or safe(lambda: doc.Dirty):
                    continue
                if safe(lambda: doc.ReferencingDocuments.Count, 1):
                    continue
                if safe(lambda: doc.Close(True), "x") is None:
                    closed += 1
            if not closed:
                break

    # -- documents ---------------------------------------------------------

    def template(self, kind: int, wanted: str | None) -> str:
        if wanted:
            return str(Path(wanted).resolve())
        if kind == kDrawingDocumentObject:
            cand = self.templates / "Standard_openUC2_2025.idw"
            if cand.exists():
                return str(cand)
        found = safe(lambda: self.app.FileManager.GetTemplateFile(kind))
        if found and kind == kDrawingDocumentObject and found.lower().endswith(".dwg"):
            idw = Path(found).with_suffix(".idw")
            found = str(idw) if idw.exists() else found
        return found or ""

    def matrix(self, t: np.ndarray):
        m = self.tg.CreateMatrix()
        c = t[:3, 3] / 10.0
        m.SetCoordinateSystem(self.tg.CreatePoint(*c), self.tg.CreateVector(*t[:3, 0]),
                              self.tg.CreateVector(*t[:3, 1]), self.tg.CreateVector(*t[:3, 2]))
        return m

    def point2d(self, x: float, y: float):
        return self.tg.CreatePoint2d(float(x), float(y))


# ---------------------------------------------------------------------------
# Scenes: one small assembly per picture
# ---------------------------------------------------------------------------

MODULE_PROPS = (
    ("Design Tracking Properties", ("Part Number", "Description", "Designer", "Stock Number", "Project",
                                    "Engineer", "Material", "Vendor", "Cost Center")),
    ("Inventor Summary Information", ("Title", "Subject", "Author", "Revision Number", "Comments")),
)


class Scene:
    """A saved, throw-away assembly that holds every unit once, in one pose."""

    def __init__(self, ses: Session, units: list[Unit], poses: dict[str, np.ndarray], shown: set[str],
                 module_doc, path: Path, template: str):
        self.ses = ses
        self.path = path
        self.doc = ses.app.Documents.Add(kAssemblyDocumentObject, template, False)
        self.occ: dict[str, object] = {}
        # Hidden units are hidden in a design view of our own; [Primary] keeps no visibility.
        reps = self.doc.ComponentDefinition.RepresentationsManager.DesignViewRepresentations
        rep = next((r for r in reps if not r.Name.startswith("[")), None) or reps.Add("Manual")
        rep.Activate()
        self.design_view = rep.Name
        occs = self.doc.ComponentDefinition.Occurrences
        for u in units:
            pose = poses.get(u.key, u.occ.transform)
            try:
                if u.occ.kind == "virtual":
                    new = occs.AddVirtual(u.occ.name, ses.matrix(pose))
                    for group, names in MODULE_PROPS[:1]:
                        for nm in ("Part Number", "Description"):
                            value = _iprop(u.occ.com.Definition, group, nm)
                            if value:
                                safe(lambda: setattr(new.Definition.PropertySets.Item(group).Item(nm), "Value", value))
                else:
                    new = occs.AddByComponentDefinition(u.occ.com.Definition, ses.matrix(pose))
            except Exception as exc:
                log(f"\n    ! could not place {u.occ.name}: {exc}")
                continue
            safe(lambda: setattr(new, "Grounded", True))
            self._copy_bom_structure(u.occ, new)
            self._copy_appearance(u.occ, new)
            if u.key not in shown:
                safe(lambda: setattr(new, "Visible", False))
            self.occ[u.key] = new
        for group, names in MODULE_PROPS:
            for nm in names:
                value = _iprop(module_doc, group, nm)
                if value:
                    safe(lambda: setattr(self.doc.PropertySets.Item(group).Item(nm), "Value", value))
        if path.exists():
            path.unlink()
        self.doc.SaveAs(str(path), False)

    def _copy_bom_structure(self, src: Occ, new) -> None:
        if src.bom and src.definition_bom and src.bom != src.definition_bom:
            code = next((k for k, v in BOM_NAMES.items() if v == src.bom), None)
            if code:
                safe(lambda: setattr(new, "BOMStructure", code))

    def _copy_appearance(self, src: Occ, new) -> None:
        source = safe(lambda: src.com.AppearanceSourceType)
        if source not in (kOverrideAppearance, kComponentOccurrenceAppearance):
            return
        asset = safe(lambda: src.com.Appearance)
        if asset is None:
            return
        local = safe(lambda: self.doc.AppearanceAssets.Item(asset.Name))
        if local is None:
            local = safe(lambda: asset.CopyTo(self.doc))
        if local is not None:
            safe(lambda: setattr(new, "Appearance", local))

    def close(self) -> None:
        safe(lambda: self.doc.Close(True))


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def view_basis(view_from: np.ndarray = VIEW_FROM) -> tuple[np.ndarray, np.ndarray]:
    """Screen right / up of an orthographic camera looking from *view_from* with Z up."""
    look = -view_from / np.linalg.norm(view_from)
    up = np.array([0.0, 0.0, 1.0]) - look * look[2]
    up /= np.linalg.norm(up)
    right = np.cross(look, up)
    return right, up


def projected_extent(points: np.ndarray, view_from: np.ndarray = VIEW_FROM) -> tuple[float, float]:
    right, up = view_basis(view_from)
    if len(points) == 0:
        return 1.0, 1.0
    return float(np.ptp(points @ right)), float(np.ptp(points @ up))


def choose_view(moves: list[np.ndarray]) -> np.ndarray:
    """The iso octant towards which the new parts move sideways (else the usual one).

    A part pulled out away from the camera hides behind what it goes into;
    vertical moves read the same from every octant.
    """
    def score(v: np.ndarray) -> float:
        vh = v[:2] / np.linalg.norm(v)
        return sum(max(0.0, float(m[:2] @ vh)) / max(np.linalg.norm(m), 1e-9) for m in moves)

    best = VIEW_FROM
    for cand in VIEW_CANDIDATES[1:]:
        if score(cand) > score(best) + 1e-6:
            best = cand
    return best


def fit_scale(extent_mm: tuple[float, float], box_cm: tuple[float, float]) -> float:
    """Largest standard scale at which *extent_mm* fits into *box_cm*."""
    w, h = max(extent_mm[0], 1e-3) / 10.0, max(extent_mm[1], 1e-3) / 10.0
    limit = min(box_cm[0] / w, box_cm[1] / h)
    for s in NICE_SCALES:
        if s <= limit:
            return s
    return limit


class Projection:
    """Exact model (mm) -> sheet (cm) map of an orthographic drawing view."""

    def __init__(self, ses: Session, view):
        o = view.ModelToSheetSpace(ses.tg.CreatePoint(0, 0, 0))
        cols = []
        for axis in np.eye(3):
            p = view.ModelToSheetSpace(ses.tg.CreatePoint(*axis))
            cols.append([p.X - o.X, p.Y - o.Y])
        self.a = np.array(cols).T / 10.0  # per mm
        self.b = np.array([o.X, o.Y])

    def __call__(self, pts_mm: np.ndarray) -> np.ndarray:
        pts = np.atleast_2d(pts_mm)
        return pts @ self.a.T + self.b


class Manual:
    """The drawing: one A3 sheet per page, exported to PDF."""

    def __init__(self, ses: Session, template: str, style: int, border: str, title_block: str | None):
        self.ses = ses
        self.style = style
        self.doc = ses.app.Documents.Add(kDrawingDocumentObject, template, False)
        self.template_sheets = [s for s in self.doc.Sheets]
        self.border = border
        self.title_block = title_block or self._template_title_block()
        self.sheets = []

    def _template_title_block(self) -> str:
        for s in self.template_sheets:
            if safe(lambda: s.Border.Name) == self.border and safe(lambda: s.TitleBlock.Name):
                return s.TitleBlock.Name
        return "openUC2 neu"

    def new_sheet(self, name: str):
        sheet = self.doc.Sheets.Add(kA3DrawingSheetSize, kLandscapePageOrientation, name)
        if safe(lambda: self.doc.BorderDefinitions.Item(self.border)) is not None:
            safe(lambda: sheet.AddBorder(self.doc.BorderDefinitions.Item(self.border)))
        tb = safe(lambda: self.doc.TitleBlockDefinitions.Item(self.title_block))
        if tb is not None:
            safe(lambda: sheet.AddTitleBlock(tb))
        if self.template_sheets:  # the template's own sheets go once ours exist
            for s in self.template_sheets:
                safe(lambda: s.Delete())
            self.template_sheets = []
        self.sheets.append(sheet)
        sheet.Activate()
        return sheet

    def add_view(self, sheet, scene: Scene, points_mm: np.ndarray, box: tuple[float, float, float, float],
                 view_from: np.ndarray = VIEW_FROM):
        """Base view of *scene*, scaled to fit *box* (x0, y0, x1, y1 in cm) and centred in it."""
        x0, y0, x1, y1 = box
        scale = fit_scale(projected_extent(points_mm, view_from), (x1 - x0, y1 - y0))
        cam = self.ses.to.CreateCamera()
        center = points_mm.mean(axis=0) / 10.0 if len(points_mm) else np.zeros(3)
        eye = center + view_from * 50.0
        cam.Eye = self.ses.tg.CreatePoint(*eye)
        cam.Target = self.ses.tg.CreatePoint(*center)
        cam.UpVector = self.ses.tg.CreateUnitVector(0, 0, 1)
        # The scene hides parts in its active design view; the drawing's
        # default ([Primary]) would show them all.
        options = self.ses.to.CreateNameValueMap()
        dvr = scene.design_view
        options.Add("DesignViewRepresentation", dvr)
        options.Add("DesignViewAssociative", True)
        anchor = self.ses.point2d((x0 + x1) / 2, (y0 + y1) / 2)
        try:
            view = sheet.DrawingViews.AddBaseView(scene.doc, anchor, float(scale), kArbitraryViewOrientation,
                                                  self.style, "", cam, options)
        except Exception as exc:
            log(f"\n    ! base view with design view {dvr!r} failed ({exc}); scene {scene.path.name}, "
                f"scale {scale}, eye {eye}, target {center}")
            raise
        safe(lambda: setattr(view, "ShowLabel", False))
        safe(lambda: setattr(view, "DisplayTangentEdges", False))
        # Centre the geometry itself (the view box can be off-centre from the anchor).
        proj = Projection(self.ses, view)
        pts = proj(points_mm)
        if len(pts):
            mid = (pts.min(axis=0) + pts.max(axis=0)) / 2
            want = np.array([(x0 + x1) / 2, (y0 + y1) / 2])
            c = view.Center
            view.Center = self.ses.point2d(c.X + want[0] - mid[0], c.Y + want[1] - mid[1])
            proj = Projection(self.ses, view)
        return view, proj

    def export_pdf(self, path: Path) -> None:
        app = self.ses.app
        pdf = app.ApplicationAddIns.ItemById(PDF_TRANSLATOR_ID)
        if not safe(lambda: pdf.Activated):
            pdf.Activate()
        ctx = self.ses.to.CreateTranslationContext()
        ctx.Type = kFileBrowseIOMechanism
        opts = self.ses.to.CreateNameValueMap()
        medium = self.ses.to.CreateDataMedium()
        if pdf.HasSaveCopyAsOptions(self.doc, ctx, opts):
            _nvm_put(opts, "All_Color_AS_Black", 0)
            _nvm_put(opts, "Remove_Line_Weights", 0)
            _nvm_put(opts, "Vector_Resolution", 400)
            _nvm_put(opts, "Sheet_Range", kPrintAllSheets)
        if path.exists():
            path.unlink()
        medium.FileName = str(path)
        pdf.SaveCopyAs(self.doc, ctx, opts, medium)

    def close(self) -> None:
        safe(lambda: self.doc.Close(True))


# -- annotations ------------------------------------------------------------

def visible_curve_points(ses: Session, view, occ, samples: int = 8, max_curves: int = 60) -> list[tuple]:
    """(curve, x, y) points on the visible outline of *occ* in *view*."""
    curves = safe(lambda: prop_get(view, "DrawingCurves", occ))
    out = []
    if curves is None:
        return out
    for i in range(1, min(curves.Count, max_curves) + 1):
        curve = curves.Item(i)
        segs = safe(lambda: curve.Segments)
        if segs is not None and segs.Count and all(safe(lambda k=k: segs.Item(k).HiddenLine) for k in range(1, segs.Count + 1)):
            continue
        ev = safe(lambda: curve.Evaluator2D)
        if ev is None:
            continue
        ext = safe(lambda: ev.GetParamExtents())
        if not ext:
            continue
        lo, hi = ext[0], ext[1]
        params = [lo + (hi - lo) * (k + 0.5) / samples for k in range(samples)]
        coords = safe(lambda: ev.GetPointAtParam(params, []))
        if not coords:
            continue
        if isinstance(coords, tuple) and len(coords) == 2 and isinstance(coords[1], (tuple, list)):
            coords = coords[1]
        for k in range(0, len(coords) - 1, 2):
            out.append((curve, coords[k], coords[k + 1]))
    return out


def spread(targets: list[float], lo: float, hi: float, gap: float) -> list[float]:
    """Positions near *targets* (sorted high to low) at least *gap* apart within [lo, hi]."""
    if not targets:
        return []
    order = sorted(range(len(targets)), key=lambda i: -targets[i])
    pos = [0.0] * len(targets)
    current = hi
    for i in order:
        current = min(targets[i], current)
        pos[i] = current
        current -= gap
    overflow = lo - min(pos)
    if overflow > 0:  # pushed below the frame: shift the column up, keeping the order
        current = lo
        for i in reversed(order):
            current = max(pos[i] + overflow, current)
            pos[i] = min(current, hi)
            current += gap
    return pos


def add_balloons(ses: Session, sheet, view, proj: Projection, picks: list[tuple[str, object, np.ndarray]],
                 keep_out: list[tuple[float, float, float, float]]) -> int:
    """One balloon per (label, occurrence, centre_mm), in columns left and right of the view."""
    if not picks:
        return 0
    vx0 = view.Center.X - view.Width / 2
    vx1 = view.Center.X + view.Width / 2
    vmid = view.Center.X
    left, right = [], []
    for label, occ, center in picks:
        pts = visible_curve_points(ses, view, occ)
        c2 = proj(center)[0]
        side = right if c2[0] >= vmid else left
        if not pts:
            continue
        # The outline point nearest the balloon side, at the part's height.
        if side is right:
            curve, x, y = max(pts, key=lambda p: p[1] - 0.15 * abs(p[2] - c2[1]))
        else:
            curve, x, y = min(pts, key=lambda p: p[1] + 0.15 * abs(p[2] - c2[1]))
        side.append((label, curve, x, y))
    made = 0
    x0f, y0f, x1f, y1f = FRAME
    for side, column_x in ((right, min(vx1 + 1.6, x1f - 0.8)), (left, max(vx0 - 1.6, x0f + 0.8))):
        if not side:
            continue
        lo, hi = y0f + 0.8, y1f - 0.8
        for kx0, ky0, kx1, ky1 in keep_out:  # do not run into the parts list / title block
            if kx0 - 0.6 <= column_x <= kx1 + 0.6:
                if ky0 > (lo + hi) / 2:
                    hi = min(hi, ky0 - 0.8)
                else:
                    lo = max(lo, ky1 + 0.8)
        ys = spread([s[3] for s in side], lo, hi, 1.25)
        for (label, curve, x, y), by in zip(side, ys):
            leader = ses.to.CreateObjectCollection()
            leader.Add(ses.point2d(column_x, by))
            leader.Add(sheet.CreateGeometryIntent(curve, ses.point2d(x, y)))
            if safe(lambda: sheet.Balloons.Add(leader)) is not None:
                made += 1
    return made


def draw_lines(ses: Session, view, segments: list[tuple[np.ndarray, np.ndarray]], arrow: bool,
               weight: float = 0.018, dashed: bool = False) -> None:
    """Sketch lines (sheet cm) on *view*, optionally with an arrowhead at the end point."""
    if not segments:
        return
    sketch = view.Sketches.Add()
    sketch.Edit()
    try:
        lines = sketch.SketchLines

        def line(a, b):
            ln = lines.AddByTwoPoints(sketch.SheetToSketchSpace(ses.point2d(*a)),
                                      sketch.SheetToSketchSpace(ses.point2d(*b)))
            safe(lambda: setattr(ln, "LineWeight", weight))
            safe(lambda: setattr(ln, "LineType", kDashedLineType if dashed else kContinuousLineType))
            return ln

        for a, b in segments:
            a, b = np.asarray(a, float), np.asarray(b, float)
            d = b - a
            n = np.linalg.norm(d)
            if n < 0.25:
                continue
            line(a, b)
            if arrow:
                u = d / n
                size = min(0.45, 0.35 * n)
                side = np.array([-u[1], u[0]])
                for s in (1, -1):
                    line(b, b - u * size + side * s * size * 0.45)
    finally:
        sketch.ExitEdit()


def add_note(ses: Session, sheet, x: float, y: float, text: str, size_cm: float, bold: bool = False):
    """A general note whose top-left corner is at (x, y)."""
    weight = " Bold='True'" if bold else ""
    body = f"<StyleOverride FontSize='{num(size_cm)}'{weight}>{xml_escape(text)}</StyleOverride>"
    return safe(lambda: sheet.DrawingNotes.GeneralNotes.AddFitted(ses.point2d(x, y), body))


def add_table(ses: Session, sheet, title: str, headers: list[str], rows: list[list[str]], top_right: tuple[float, float],
              widths: list[float] | None = None):
    """A custom table anchored at its top-right corner; *widths* in cm."""
    if not rows:
        return None
    contents = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, [c or " " for row in rows for c in row])
    col_widths = (win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [float(w) for w in widths])
                  if widths else pythoncom.Missing)
    # ColumnTitles is passed by reference, so pywin32 hands back (table, titles).
    result = safe(lambda: sheet.CustomTables.Add(title, ses.point2d(*top_right), len(headers), len(rows),
                                                  list(headers), contents, col_widths))
    table = result[0] if isinstance(result, tuple) else result
    if table is None:
        return None
    rb = safe(lambda: table.RangeBox)
    if rb is not None:  # anchor the table's top-right corner
        p = table.Position
        table.Position = ses.point2d(p.X + top_right[0] - rb.MaxPoint.X, p.Y + top_right[1] - rb.MaxPoint.Y)
    return table


# ---------------------------------------------------------------------------
# One module
# ---------------------------------------------------------------------------

@dataclass
class Options:
    out: Path
    style: int
    steps: bool = True
    gap: float = 8.0
    keep_drawing: bool = False
    overwrite: bool = False
    template_idw: str | None = None
    template_iam: str | None = None
    border: str = "A3"
    title_block: str | None = None
    trails: bool = True


def bom_order(plan: ep.Plan, units: list[Unit]) -> list[Unit]:
    """Units in the order they are first used, the ones never drawn last."""
    by_key = {u.key: u for u in units}
    seen: list[str] = []

    def add_member(member) -> None:
        if isinstance(member, ep.Group):
            gp = plan.groups[member.key]
            members = {m.key: m for m in member.members}
            for p in gp.placements:
                add_member(members[p.key])
        elif member.key in by_key and member.key not in seen:
            seen.append(member.key)

    add_member(plan.root)
    ordered = [by_key[k] for k in seen]
    ordered += [u for u in units if u.key not in seen]
    return ordered


def member_bodies(member) -> list[ep.Body]:
    return member.bodies() if isinstance(member, ep.Group) else [member]


def make_manual(ses: Session, iam: Path, opts: Options) -> dict:
    app = ses.app
    started = time.time()
    stem = iam.stem
    pdf_path = opts.out / f"{stem}.pdf"
    report_path = opts.out / f"{stem}.manual.json"
    if pdf_path.exists() and not opts.overwrite:
        log(f"  {stem}: PDF exists, skipping (use --overwrite)")
        return {"module": stem, "pdf": str(pdf_path), "skipped": "exists"}

    log(f"  {stem}")
    module = find_open_document(app, iam)
    opened_here = module is None
    if module is None:
        module = app.Documents.Open(str(iam), False)
    scenes: list[Scene] = []
    manual = None
    work = None
    warnings: list[str] = []
    try:
        if safe(lambda: module.DocumentType) != kAssemblyDocumentObject:
            raise RuntimeError("not an assembly")
        t0 = time.time()
        tree = read_tree(module)
        root, units, notes = build_model(tree, stem, stem)
        drawn = [u for u in units if u.drawn]
        log(f"    {len(units)} parts-list units, {len(drawn)} drawn ({time.time() - t0:.1f}s read)")
        if not drawn:
            raise RuntimeError("nothing to draw")
        t0 = time.time()
        plan = ep.plan(root, gap=opts.gap, log=lambda m: (warnings.append(m.strip()), log(m)))
        log(f"    plan: {len(plan.steps)} steps ({time.time() - t0:.1f}s)")

        order = bom_order(plan, units)
        bodies = {b.key: b for b in root.bodies()}
        item_of: dict[str, int] = {}
        for u in order:
            item_of.setdefault(u.component, len(item_of) + 1)
        count_of: dict[str, int] = {}
        for u in order:
            count_of[u.component] = count_of.get(u.component, 0) + 1
        unit_of = {u.key: u for u in units}

        work = (opts.out / f"{stem} - manual files") if opts.keep_drawing else Path(tempfile.mkdtemp(prefix="uc2manual_"))
        work.mkdir(parents=True, exist_ok=True)
        asm_template = ses.template(kAssemblyDocumentObject, opts.template_iam)
        manual = Manual(ses, ses.template(kDrawingDocumentObject, opts.template_idw), opts.style, opts.border,
                        opts.title_block)

        def pose(key: str, shift: np.ndarray) -> np.ndarray:
            t = unit_of[key].occ.transform.copy()
            t[:3, 3] += shift
            return t

        # ---- page 1: the whole module exploded, parts list, balloons ----
        poses = {k: pose(k, plan.body_displacement(k)) for k in bodies}
        shown = set(bodies)
        scene = Scene(ses, order, poses, shown, module, work / f"{stem} - 00 overview.iam", asm_template)
        scenes.append(scene)
        sheet = manual.new_sheet("Explosion")
        x0, y0, x1, y1 = FRAME
        overview_from = choose_view([plan.body_displacement(k) for k in bodies])
        view, proj = manual.add_view(sheet, scene, sample_points(bodies, plan.body_displacement),
                                     (x0 + 2.2, y0 + 0.6, TITLE_BLOCK_LEFT - 2.2, y1 - 0.6), overview_from)
        sheet.Activate()
        parts_list = sheet.PartsLists.Add(view, ses.point2d(x1, y1), kStructured)
        fit_parts_list(ses, parts_list, (x1, y1))
        mismatch = check_parts_list(parts_list, item_of, order)
        if mismatch:
            warnings.append(mismatch)
            log(f"    ! {mismatch}")
        rows = parts_list.PartsListRows.Count
        if parts_list.RangeBox.MinPoint.Y < TITLE_BLOCK_TOP + 0.3:
            # Too long for the explosion page: its own page with the finished module.
            parts_list.Delete()
            poses = {k: pose(k, np.zeros(3)) for k in bodies}
            assembled = Scene(ses, order, poses, set(bodies), module, work / f"{stem} - 00 assembled.iam", asm_template)
            scenes.append(assembled)
            parts_sheet = manual.new_sheet("Teileliste")
            small, _ = manual.add_view(parts_sheet, assembled, sample_points(bodies, lambda k: np.zeros(3)),
                                       (x0 + 1.0, TITLE_BLOCK_TOP + 1.0, x0 + 13.0, y1 - 1.0), overview_from)
            parts_sheet.Activate()
            fit_parts_list(ses, parts_sheet.PartsLists.Add(small, ses.point2d(x1, y1), kStructured), (x1, y1))
            sheet.Activate()
            pl_box = None
            log(f"    parts list ({rows} rows) on its own page")
        else:
            pl_box = parts_list.RangeBox
        picks = []
        for comp, item in sorted(item_of.items(), key=lambda kv: kv[1]):
            cands = [u for u in order if u.component == comp and u.drawn and u.key in scene.occ]
            if not cands:
                continue
            centre = {u.key: bodies[u.key].bbox.mean(axis=0) + plan.body_displacement(u.key) for u in cands}
            best = max(cands, key=lambda u: proj(centre[u.key])[0][0])
            picks.append((str(item), scene.occ[best.key], centre[best.key]))
        keep_out = [(TITLE_BLOCK_LEFT, y0, x1, TITLE_BLOCK_TOP)]
        if pl_box is not None:
            keep_out.append((pl_box.MinPoint.X, pl_box.MinPoint.Y, pl_box.MaxPoint.X, pl_box.MaxPoint.Y))
        n_balloons = add_balloons(ses, sheet, view, proj, picks, keep_out)
        if opts.trails:
            draw_lines(ses, view, overview_trails(plan, bodies, proj), arrow=False, weight=0.013)
        log(f"    page 1: exploded view {view.ScaleString}, {rows} rows, {n_balloons} balloons")

        # ---- step pages ----
        step_info = []
        if opts.steps:
            built_in = _steps_of_groups(plan)
            for step in plan.steps:
                info = step_page(ses, manual, plan, step, order, unit_of, bodies, item_of, module, work, stem,
                                 asm_template, scenes, opts, len(plan.steps), built_in)
                step_info.append(info)
            log(f"    {len(plan.steps)} step pages")

        opts.out.mkdir(parents=True, exist_ok=True)
        manual.export_pdf(pdf_path)
        if opts.keep_drawing:
            manual.doc.SaveAs(str(work / f"{stem} - manual.idw"), False)
        bom = [{"item": item_of[c], "qty": count_of[c],
                "part_number": next(u.occ.part_number for u in order if u.component == c),
                "description": next(u.occ.description for u in order if u.component == c),
                "file": c} for c in sorted(item_of, key=item_of.get)]
        report = {
            "module": stem, "assembly": str(iam), "pdf": str(pdf_path),
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "part_number": _iprop(module, "Design Tracking Properties", "Part Number"),
            "description": _iprop(module, "Design Tracking Properties", "Description"),
            "pages": 1 + len(step_info), "bom": bom, "steps": step_info,
            "not_drawn": [{"name": u.occ.name, "why": u.why_hidden} for u in units if not u.drawn],
            "left_out": notes, "warnings": warnings,
            "seconds": round(time.time() - started, 1),
        }
        report_path.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
        log(f"    -> {pdf_path.name} ({report['pages']} pages, {report['seconds']}s)")
        return report
    finally:
        if manual is not None:
            manual.close()
        for s in scenes:
            s.close()
        if opened_here:
            safe(lambda: module.Close(True))
        if work is not None and not opts.keep_drawing:
            shutil.rmtree(work, ignore_errors=True)


def fit_parts_list(ses: Session, parts_list, top_right: tuple[float, float]) -> None:
    """Room for the long openUC2 part numbers (fewer wrapped rows), top-right corner kept."""
    cols = parts_list.PartsListColumns
    if cols.Count == 4:
        for i, w in enumerate((1.6, 1.6, 7.0, 5.5), start=1):
            safe(lambda: setattr(cols.Item(i), "Width", w))
    rb = parts_list.RangeBox
    p = parts_list.Position
    parts_list.Position = ses.point2d(p.X + top_right[0] - rb.MaxPoint.X, p.Y + top_right[1] - rb.MaxPoint.Y)


def sample_points(bodies: dict[str, ep.Body], shift_of, keys=None, per_body: int = 1500) -> np.ndarray:
    """Mesh vertices (thinned) of the drawn bodies in their pose, for fitting the view."""
    keys = list(bodies) if keys is None else list(keys)
    return np.vstack([bodies[k].vertices[:: max(1, len(bodies[k].vertices) // per_body)] + shift_of(k) for k in keys])


def check_parts_list(parts_list, item_of: dict[str, int], order: list[Unit]) -> str:
    """Warn when Inventor numbered the rows differently from the step tables."""
    expected = {}
    for u in order:
        expected.setdefault(item_of[u.component], u.occ.part_number)
    mismatched = []
    for r in range(1, parts_list.PartsListRows.Count + 1):
        row = parts_list.PartsListRows.Item(r)
        item = safe(lambda: row.Item(1).Value)
        number = safe(lambda: row.Item(3).Value)
        try:
            item = int(item)
        except (TypeError, ValueError):
            continue
        if number and expected.get(item) and number != expected[item]:
            mismatched.append(f"{item}: {number} != {expected[item]}")
    return f"parts list numbering differs from the steps: {', '.join(mismatched)}" if mismatched else ""


def overview_trails(plan: ep.Plan, bodies: dict[str, ep.Body], proj: Projection) -> list:
    """For each moved body: from where it hangs back along its own offset; the same for each group."""
    segs = []

    def visit(group: ep.Group, carried: np.ndarray) -> None:
        gp = plan.groups[group.key]
        for m in group.members:
            own = gp.offsets[m.key]
            if isinstance(m, ep.Group):
                base = next(b for b in m.bodies() if b.key == _base_body(plan, m))
                end = base.bbox.mean(axis=0) + carried + plan.groups[m.key].offsets.get(base.key, np.zeros(3))
                if np.linalg.norm(own) > 0.5:
                    a = end + own
                    segs.append((proj(a)[0], proj(end)[0]))
                visit(m, carried + own)
            elif np.linalg.norm(own) > 0.5:
                c = m.bbox.mean(axis=0) + carried
                segs.append((proj(c + own)[0], proj(c)[0]))

    visit(plan.root, np.zeros(3))
    return segs


def _base_body(plan: ep.Plan, group: ep.Group) -> str:
    gp = plan.groups[group.key]
    members = {m.key: m for m in group.members}
    base = members[gp.base]
    while isinstance(base, ep.Group):
        inner = plan.groups[base.key]
        base = {m.key: m for m in base.members}[inner.base]
    return base.key


def _steps_of_groups(plan: ep.Plan) -> dict[str, list[int]]:
    """Group part id -> the step numbers that build it."""
    out: dict[str, list[int]] = {}
    for s in plan.steps:
        out.setdefault(s.group.info.get("part", s.group.key), []).append(s.number)
    return out


def step_arrows(proj: Projection, moving: list[tuple[np.ndarray, np.ndarray]], view_mid: np.ndarray) -> tuple[list, list]:
    """IKEA-style motion marks for (exploded points mm, offset mm) of each new member.

    Big parts get a solid arrow beside them, pointing where they go; small
    ones (screws, washers) a dashed line from their front into the hole.
    """
    arrows, dashes = [], []
    for pts, off in moving:
        e = proj(pts.mean(axis=0))[0]
        d = proj(pts.mean(axis=0) - off)[0]
        v = d - e
        dist = float(np.linalg.norm(v))
        if dist < 0.3:
            continue
        u = v / dist
        n = np.array([-u[1], u[0]])
        p2 = proj(pts)
        along = (p2 - e) @ u
        across = (p2 - e) @ n
        size = max(float(np.ptp(along)), float(np.ptp(across)))
        if size < 1.6:
            front = e + u * float(along.max())
            dashes.append((front, d))
            continue
        side = 1.0 if float((e - view_mid) @ n) >= 0 else -1.0
        lateral = (float(across.max()) if side > 0 else -float(across.min())) + 0.5
        start = e + n * side * lateral - u * min(0.4 * float(np.ptp(along)), 1.0)
        length = float(np.clip(0.55 * dist, 1.2, 3.0))
        arrows.append((start, start + u * length))
    return arrows, dashes


def step_page(ses: Session, manual: Manual, plan: ep.Plan, step: ep.Step, order: list[Unit],
              unit_of: dict[str, Unit], bodies: dict[str, ep.Body], item_of: dict[str, int], module, work: Path,
              stem: str, asm_template: str, scenes: list[Scene], opts: Options, total: int,
              built_in: dict[str, list[int]]) -> dict:
    members = {m.key: m for m in step.group.members}
    shift: dict[str, np.ndarray] = {}
    shown: set[str] = set()
    for key in step.present:
        for b in member_bodies(members[key]):
            shown.add(b.key)
            shift[b.key] = np.zeros(3)
    for p in step.new:
        for b in member_bodies(members[p.key]):
            shown.add(b.key)
            shift[b.key] = step.offsets[p.key]
    poses = {}
    for k, s in shift.items():
        t = unit_of[k].occ.transform.copy()
        t[:3, 3] += s
        poses[k] = t
    scene = Scene(ses, order, poses, shown, module, work / f"{stem} - {step.number:02d} step.iam", asm_template)
    scenes.append(scene)
    sheet = manual.new_sheet(f"Schritt {step.number}")

    # header: big step number, what is being built
    x0, y0, x1, y1 = FRAME
    add_note(ses, sheet, x0 + 0.9, y1 - 0.4, str(step.number), 1.6, bold=True)
    sub = step.group.label.split(":")[0]
    caption = f"{step.quantity}x  {sub}" if step.quantity > 1 else sub
    add_note(ses, sheet, x0 + 3.4, y1 - 0.7, caption, 0.42)
    add_note(ses, sheet, x0 + 3.4, y1 - 1.4, f"Schritt {step.number} / {total}", 0.3)

    # what goes in: parts with their parts-list item, pre-assemblies with their steps;
    # a group's first step also lists the part everything goes onto
    base_key = plan.groups[step.group.key].base
    listed = [members[p.key] for p in step.new]
    if step.present == [base_key]:
        listed.insert(0, members[base_key])
    new_parts: dict[str, int] = {}
    new_groups: list[ep.Group] = []
    for member in listed:
        if isinstance(member, ep.Group):
            new_groups.append(member)
            continue
        comp = unit_of[member.key].component
        new_parts[comp] = new_parts.get(comp, 0) + 1
    rows = []
    for comp, n in sorted(new_parts.items(), key=lambda kv: item_of[kv[0]]):
        u = next(x for x in order if x.component == comp)
        rows.append([str(item_of[comp]), f"{n * step.quantity}x", u.occ.part_number or u.occ.name, u.occ.description])
    group_rows: dict[str, list] = {}
    for g in new_groups:
        pid = g.info.get("part", g.key)
        nums = built_in.get(pid, [])
        where = (f"aus Schritt {nums[0]}" if len(nums) == 1 else f"aus Schritt {nums[0]}-{nums[-1]}") if nums else ""
        if pid in group_rows:
            group_rows[pid][1] += 1
        else:
            group_rows[pid] = [g.label.split(":")[0], 1, where]
    for label, n, where in group_rows.values():
        rows.append(["", f"{n * step.quantity}x", label, where])
    table = add_table(ses, sheet, f"TEILE FÜR SCHRITT {step.number}", ["OBJEKT", "ANZAHL", "BAUTEILNUMMER", "BESCHREIBUNG"],
                      rows, (x1, y1), widths=[1.6, 1.6, 7.0, 5.5])
    table_bottom = safe(lambda: table.RangeBox.MinPoint.Y, y1) if table is not None else y1

    pts = sample_points(bodies, lambda k: shift[k], shown)
    view_from = choose_view([step.offsets[p.key] for p in step.new])
    left_box = (x0 + 2.2, y0 + 0.6, TITLE_BLOCK_LEFT - 2.2, y1 - 2.4)
    wide_box = (x0 + 2.0, TITLE_BLOCK_TOP + 0.6, x1 - 2.0, min(table_bottom, y1 - 2.4) - 0.4)
    ext = projected_extent(pts, view_from)
    s_left = fit_scale(ext, (left_box[2] - left_box[0], left_box[3] - left_box[1]))
    s_wide = fit_scale(ext, (wide_box[2] - wide_box[0], wide_box[3] - wide_box[1]))
    box = wide_box if s_wide > s_left else left_box
    view, proj = manual.add_view(sheet, scene, pts, box, view_from)

    # motion marks
    view_mid = np.array([view.Center.X, view.Center.Y])
    moving = []
    for p in step.new:
        off = step.offsets[p.key]
        if np.linalg.norm(off) < 0.5:
            continue
        mb = member_bodies(members[p.key])
        moving.append((sample_points(bodies, lambda k: shift[k], [b.key for b in mb], per_body=300), off))
    arrows, dashes = step_arrows(proj, moving, view_mid)
    draw_lines(ses, view, arrows, arrow=True, weight=0.035)
    draw_lines(ses, view, dashes, arrow=False, weight=0.02, dashed=True)

    # balloons on the parts listed on this page (one per kind)
    new_keys = {m.key for m in listed if not isinstance(m, ep.Group)}
    picks = []
    for comp in sorted(new_parts, key=item_of.get):
        cands = [u for u in order if u.component == comp and u.key in new_keys and u.key in scene.occ]
        if not cands:
            continue
        centre = {u.key: bodies[u.key].bbox.mean(axis=0) + shift[u.key] for u in cands}
        best = max(cands, key=lambda u: proj(centre[u.key])[0][0])
        picks.append((str(item_of[comp]), scene.occ[best.key], centre[best.key]))
    keep_out = [(TITLE_BLOCK_LEFT, y0, x1, TITLE_BLOCK_TOP)]
    if table is not None:
        rb = table.RangeBox
        keep_out.append((rb.MinPoint.X, rb.MinPoint.Y, rb.MaxPoint.X, rb.MaxPoint.Y))
    add_balloons(ses, sheet, view, proj, picks, keep_out)
    return {
        "number": step.number, "group": step.group.label, "quantity": step.quantity,
        "parts": [{"item": int(r[0]) if r[0] else None, "qty": r[1], "part_number": r[2], "description": r[3]}
                  for r in rows],
        "directions": {members[p.key].label: plan.groups[step.group.key].direction_name(p.direction)
                       for p in step.new},
        "forced": [members[p.key].label for p in step.new if p.forced],
    }


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------

def modules_from_kit(app, kit: Path) -> list[Path]:
    """The assemblies placed at the top of a kit (a box of modules)."""
    doc = find_open_document(app, kit)
    opened = doc is None
    if doc is None:
        doc = app.Documents.Open(str(kit), False)
    try:
        components, _ = collect_components(doc)
        return [c.path for c in components if c.kind == "assembly"]
    finally:
        if opened:
            safe(lambda: doc.Close(True))


def kit_files(p: Path) -> list[Path]:
    """A kit .iam as given; for a folder the newest batch of each kit in it (see kit_bom.py)."""
    if not p.is_dir():
        return [p]
    from kit_bom import newest_kits
    found = newest_kits(p)  # KIT folder: one per sub-folder (CORE, INFINITY, ...)
    if not found:           # a single kit's folder
        found = newest_kits(p.parent)
        found = [k for k in found if k.parent == p]
    return found


def collect_inputs(args, app) -> list[tuple[Path, Path]]:
    """(assembly, output folder) pairs."""
    jobs: list[tuple[Path, Path]] = []
    out = args.out.resolve()
    for raw in args.paths:
        p = raw.resolve()
        if args.kit:
            for kit in kit_files(p):
                mods = modules_from_kit(app, kit)
                log(f"{kit.name}: {len(mods)} module(s)")
                jobs.extend((m, out / kit.stem) for m in mods)
        elif p.is_dir():
            files = sorted(p.rglob(args.pattern) if args.recursive else p.glob(args.pattern))
            files = [f for f in files if "OldVersions" not in f.parts and " - manual files" not in str(f.parent)]
            jobs.extend((f, out) for f in files)
        else:
            jobs.append((p, out))
    seen, unique = set(), []
    for iam, dest in jobs:
        k = (str(iam).lower(), str(dest).lower())
        if k not in seen:
            seen.add(k)
            unique.append((iam, dest))
    return unique


def main() -> int:
    _console_safe()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("paths", nargs="+", type=Path, help=".iam files, folders of them, or kits with --kit")
    ap.add_argument("--out", type=Path, default=Path("MANUALS"), help="output folder (default ./MANUALS)")
    ap.add_argument("--kit", action="store_true",
                    help="the paths are kit assemblies, or KIT folders (newest batch per kit, as kit_bom.py): one manual per module in them")
    ap.add_argument("--pattern", default="ASS - *.iam", help="file pattern inside folders (default 'ASS - *.iam')")
    ap.add_argument("--recursive", action="store_true", help="search folders recursively")
    ap.add_argument("--style", choices=sorted(VIEW_STYLES), default="shaded",
                    help="view style: shaded (default, like the presentation drawings) or lines (IKEA look)")
    ap.add_argument("--no-steps", action="store_true", help="only the exploded view with the parts list")
    ap.add_argument("--no-trails", action="store_true", help="no trail lines in the exploded view")
    ap.add_argument("--gap", type=float, default=8.0, help="gap between exploded parts in mm (default 8)")
    ap.add_argument("--keep-drawing", action="store_true",
                    help="keep the .idw and its scene assemblies in '<module> - manual files' for editing")
    ap.add_argument("--overwrite", action="store_true", help="redo modules whose PDF exists")
    ap.add_argument("--template", default=None, help="drawing template (default: the project's Standard_openUC2_2025.idw)")
    ap.add_argument("--title-block", default=None, help="title block name (default: the template's A3 one)")
    ap.add_argument("--dry-run", action="store_true", help="plan and print the steps, draw nothing")
    args = ap.parse_args()

    app = connect(args.paths[0].resolve() if args.paths[0].suffix.lower() == ".iam" else None)
    with Session(app) as ses:
        log(f"Inventor project: {ses.project}")
        jobs = collect_inputs(args, app)
        if not jobs:
            log("Nothing to do.")
            return 1
        log(f"{len(jobs)} module(s)\n")
        results = []
        for n, (iam, dest) in enumerate(jobs, 1):
            log(f"[{n}/{len(jobs)}]", end="")
            if args.dry_run:
                results.append(dry_run(ses, iam, args.gap))
                continue
            opts = Options(out=dest, style=VIEW_STYLES[args.style], steps=not args.no_steps, gap=args.gap,
                           keep_drawing=args.keep_drawing, overwrite=args.overwrite, template_idw=args.template,
                           title_block=args.title_block, trails=not args.no_trails)
            dest.mkdir(parents=True, exist_ok=True)
            try:
                results.append(make_manual(ses, iam, opts))
            except Exception as exc:
                log(f"    FAILED: {exc}")
                traceback.print_exc()
                results.append({"module": iam.stem, "assembly": str(iam), "failed": str(exc)})
        if not args.dry_run:
            by_dest: dict[Path, list] = {}
            for (iam, dest), r in zip(jobs, results):
                by_dest.setdefault(dest, []).append(r)
            for dest, rs in by_dest.items():
                write_index(dest / "manuals.json", rs)
        failed = [r for r in results if r.get("failed")]
        log(f"\n{len(results) - len(failed)} done, {len(failed)} failed")
        return 1 if failed else 0


INDEX_KEYS = ("module", "assembly", "pdf", "part_number", "description", "pages", "failed", "skipped")


def write_index(path: Path, results: list[dict]) -> None:
    """``manuals.json`` of an output folder: this run's modules merged into what is there."""
    entries: dict[str, dict] = {}
    if path.exists():
        try:
            for e in json.loads(path.read_text(encoding="utf-8")).get("manuals", []):
                entries[e.get("module")] = e
        except (ValueError, OSError):
            pass
    for r in results:
        old = entries.get(r.get("module"), {})
        if r.get("skipped") and old and not old.get("skipped"):
            continue  # the PDF from an earlier run is still the one on disk
        entries[r.get("module")] = {k: r.get(k) for k in INDEX_KEYS}
    path.write_text(json.dumps({"generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "manuals": sorted(entries.values(), key=lambda e: e.get("module") or "")},
                               indent=1, ensure_ascii=False), encoding="utf-8")


def dry_run(ses: Session, iam: Path, gap: float) -> dict:
    log(f"  {iam.stem}")
    module = find_open_document(ses.app, iam)
    opened = module is None
    if module is None:
        module = ses.app.Documents.Open(str(iam), False)
    try:
        root, units, notes = build_model(read_tree(module), iam.stem, iam.stem)
        plan = ep.plan(root, gap=gap)
        for s in plan.steps:
            members = {m.key: m for m in s.group.members}
            q = f"{s.quantity}x " if s.quantity > 1 else ""
            log(f"    step {s.number} {q}[{s.group.label.split(':')[0]}]: " + ", ".join(
                f"{members[p.key].label}({plan.groups[s.group.key].direction_name(p.direction)}{', forced' if p.forced else ''})"
                for p in s.new))
        for u in units:
            if not u.drawn:
                log(f"    listed, not drawn: {u.occ.name} ({u.why_hidden})")
        return {"module": iam.stem, "steps": len(plan.steps)}
    finally:
        if opened:
            safe(lambda: module.Close(True))


if __name__ == "__main__":
    sys.exit(main())
