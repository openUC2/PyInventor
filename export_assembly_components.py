#!/usr/bin/env python3
"""Export every top-level component of ONE Inventor assembly to coloured STEP + GLB.

Where ``batch_iam_to_stp_glb.py`` globs a folder of .iam files, this walks a
single open assembly (e.g. a KIT) and exports each component shown at the top
level of Inventor's model browser -- cube modules ("ASS - ..."), purchased parts
("BUY - ..."), loose parts ("PRT - ...") and so on -- as its own .stp and .glb.

Three things make that more than a loop over filenames:

  * STEP colours. ``Document.SaveAs`` reuses whatever protocol the STEP dialog
    was last left on, and AP203 carries no colour. This drives the STEP
    translator add-in explicitly and pins AP214 (``--ap``), so the exports keep
    their appearances.
  * Model states. An occurrence can reference a *variant* of its document -- the
    browser shows it as ``BUY - Sample box - XXX.ipt<geschlossen>``. Exporting
    the file's default state would silently ship the wrong geometry, so the
    referenced state is activated for the export and restored afterwards.
  * Express mode. Touching ``occurrence.Definition`` forces a full load of every
    child document and can hang for minutes on a large KIT. The browser walk
    reads only ``ReferencedDocumentDescriptor``, then opens each unique document
    once, on its own.

Requirements: a running licensed Autodesk Inventor, pywin32, cascadio, pygltflib.

Usage:
  python export_assembly_components.py "KIT.iam" --out DIR [options]
  python export_assembly_components.py --active --out DIR

Examples:
  python export_assembly_components.py ^
      "C:\\Users\\benir\\Documents\\openUC2-CAD-new\\workspace\\KIT\\CORE\\KIT - CORE - COR-25-02.iam" ^
      --out "C:\\Users\\benir\\Documents\\openUC2-CAD-EXPORT\\KIT-CORE-COR-25-02"

  # see what would be exported, touching nothing
  python export_assembly_components.py "KIT.iam" --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    import pythoncom
    import win32com.client
except ImportError:
    sys.exit("pywin32 not found. Install it with: pip install pywin32")

try:
    import cascadio
except ImportError:
    sys.exit("cascadio not found. Install it with: pip install cascadio")

# add_mm_scale is the openUC2 naming contract; keep one implementation of it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from batch_iam_to_stp_glb import add_mm_scale  # noqa: E402

#: Inventor.Application. Inventor registers itself in the ROT more than once,
#: so matches are de-duplicated by window caption rather than by moniker.
INVENTOR_CLSID = "{B6B5DC40-96E3-11D2-B774-0060B0F159EF}"
STEP_TRANSLATOR_ID = "{90AF7F40-0C01-11D5-8E83-0010B541CD80}"

kFileBrowseIOMechanism = 13059
kPartDocumentObject = 12290
kAssemblyDocumentObject = 12291

#: --ap value -> the translator's ApplicationProtocolType. AP203 has no colour.
AP_PROTOCOL = {"203": 2, "214": 3, "242": 4}

PRIMARY_STATE = "[Primary]"

#: Occurrence paths carry their model state as a suffix: "part.ipt<geschlossen>".
_MODEL_STATE_RE = re.compile(r"^(?P<path>.*?)<(?P<state>[^<>]*)>$")

_ILLEGAL_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe(fn, default=None):
    """Inventor's COM surface raises for properties that merely don't apply."""
    try:
        return fn()
    except Exception:
        return default


def _console_safe() -> None:
    """The console is cp1252; part names contain U+00B0 and friends."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Connecting to the right Inventor
# ---------------------------------------------------------------------------

def inventor_instances() -> list:
    """Every live Inventor.Application, newest registration last."""
    ctx = pythoncom.CreateBindCtx(0)
    rot = pythoncom.GetRunningObjectTable()
    wanted = "!" + INVENTOR_CLSID.lower()
    seen: set = set()
    apps: list = []
    for moniker in rot:
        try:
            if moniker.GetDisplayName(ctx, None).lower() != wanted:
                continue
            unknown = rot.GetObject(moniker)
            app = win32com.client.Dispatch(unknown.QueryInterface(pythoncom.IID_IDispatch))
        except Exception:
            continue
        key = safe(lambda: app.Caption) or len(apps)
        if key in seen:
            continue
        seen.add(key)
        apps.append(app)
    return apps


def find_open_document(app, path: Path):
    target = str(path).lower()
    for doc in safe(lambda: app.Documents, []) or []:
        if (safe(lambda: doc.FullFileName) or "").lower() == target:
            return doc
    return None


def connect(target: Path | None):
    """Pick the Inventor instance that already holds *target*, else the first."""
    apps = inventor_instances()
    if not apps:
        print("No running Inventor found; starting one ...", flush=True)
        app = win32com.client.Dispatch("Inventor.Application")
        app.Visible = True
        return app
    if target is not None and len(apps) > 1:
        for app in apps:
            if find_open_document(app, target) is not None:
                return app
    return apps[0]


# ---------------------------------------------------------------------------
# Walking the browser tree
# ---------------------------------------------------------------------------

@dataclass
class Component:
    """One unique (document, model state) pair behind the top-level browser nodes."""
    path: Path
    model_state: str | None
    doc_type: int
    names: list[str] = field(default_factory=list)  # browser occurrence names
    #: The state actually exported, once known. May differ from model_state when
    #: the parent references a state the child no longer has.
    resolved_state: str | None = None
    #: Why no file was produced, so a null path in the manifest isn't ambiguous.
    skip_reason: str | None = None

    @property
    def stem(self) -> str:
        """Output basename: file stem, plus the model state when it isn't primary.

        Uses the state actually exported, so a file is never named after a
        variant its geometry doesn't come from.
        """
        state = self.resolved_state if self.resolved_state is not None else self.model_state
        stem = self.path.stem
        if state and state != PRIMARY_STATE:
            stem = f"{stem}__{state}"
        return _ILLEGAL_FILENAME.sub("_", stem).strip()

    @property
    def kind(self) -> str:
        return "assembly" if self.doc_type == kAssemblyDocumentObject else "part"


def split_model_state(full_document_name: str) -> tuple[str, str | None]:
    """``"...ipt<geschlossen>"`` -> ``("...ipt", "geschlossen")``."""
    match = _MODEL_STATE_RE.match(full_document_name)
    if not match:
        return full_document_name, None
    return match.group("path"), match.group("state") or None


def collect_components(asm_doc, include_hidden: bool = False) -> tuple[list[Component], list[str]]:
    """Top-level occurrences, de-duplicated by (document, model state).

    Reads only the occurrence's referenced-document *descriptor*, never its
    Definition -- the latter forces express-mode documents to load in full.
    Browser folders ("Puzzles", "Samples") group nodes visually but do not nest
    the occurrences, so a flat walk already matches what the browser shows.
    """
    occurrences = asm_doc.ComponentDefinition.Occurrences
    components: dict[tuple, Component] = {}
    skipped: list[str] = []

    for i in range(1, occurrences.Count + 1):
        occ = occurrences.Item(i)
        name = safe(lambda: occ.Name) or f"<occurrence {i}>"

        if safe(lambda: occ.Suppressed) is True:
            skipped.append(f"{name} (suppressed)")
            continue
        if not include_hidden and safe(lambda: occ.Visible) is False:
            skipped.append(f"{name} (hidden)")
            continue

        descriptor = safe(lambda: occ.ReferencedDocumentDescriptor)
        full_name = safe(lambda: descriptor.FullDocumentName) if descriptor else None
        if not full_name:
            skipped.append(f"{name} (virtual component - no document)")
            continue

        raw_path, state = split_model_state(full_name)
        path = Path(raw_path)
        key = (str(path).lower(), state)
        if key not in components:
            components[key] = Component(
                path=path,
                model_state=state,
                doc_type=safe(lambda: occ.DefinitionDocumentType) or kPartDocumentObject,
            )
        components[key].names.append(name)

    return list(components.values()), skipped


# ---------------------------------------------------------------------------
# STEP export
# ---------------------------------------------------------------------------

def _nvm_put(options, key: str, value) -> None:
    """Set a NameValueMap entry.

    ``Add`` only works for keys that don't exist yet, and pywin32 cannot express
    a parameterised property put (``Value(key) = v`` in VBA), so fall back to
    invoking the property directly.
    """
    try:
        options.Add(key, value)
        return
    except Exception:
        pass
    dispid = options._oleobj_.GetIDsOfNames("Value")
    options._oleobj_.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYPUT, 0, key, value)


class StepExporter:
    """SaveCopyAs through the STEP translator, with the protocol pinned."""

    def __init__(self, app, protocol: int):
        self.app = app
        self.protocol = protocol
        self.translator = app.ApplicationAddIns.ItemById(STEP_TRANSLATOR_ID)
        if not safe(lambda: self.translator.Activated):
            self.translator.Activate()

    def export(self, doc, out_path: Path) -> None:
        transient = self.app.TransientObjects
        context = transient.CreateTranslationContext()
        context.Type = kFileBrowseIOMechanism
        options = transient.CreateNameValueMap()
        medium = transient.CreateDataMedium()

        if self.translator.HasSaveCopyAsOptions(doc, context, options):
            _nvm_put(options, "ApplicationProtocolType", self.protocol)
            _nvm_put(options, "IncludeSketches", False)

        medium.FileName = str(out_path)
        self.translator.SaveCopyAs(doc, context, options, medium)


# ---------------------------------------------------------------------------
# Model states
# ---------------------------------------------------------------------------

def active_model_state(doc) -> str | None:
    return safe(lambda: doc.ComponentDefinition.ModelStates.ActiveModelState.Name)


def activate_model_state(doc, wanted: str) -> str | None:
    """Activate *wanted*; return whichever state ends up active.

    An assembly can reference a state that was later renamed or deleted in the
    child document -- Inventor's own browser quietly falls back to [Primary]
    there, and so do we. Returning the real name lets the caller avoid naming
    the output after a variant it doesn't contain.
    """
    states = safe(lambda: doc.ComponentDefinition.ModelStates)
    if states is None:
        return None
    for i in range(1, safe(lambda: states.Count, 0) + 1):
        state = states.Item(i)
        if safe(lambda: state.Name) == wanted:
            try:
                state.Activate()
                return wanted
            except Exception as exc:
                print(f"\n      ! could not activate model state {wanted!r}: {exc}", end="")
                break
    else:
        print(f"\n      ! model state {wanted!r} is gone from the file; "
              f"exporting {active_model_state(doc)!r}", end="")
    return active_model_state(doc)


def has_no_geometry(doc) -> bool:
    """True for skeleton parts -- work planes, points and iMates but no body.

    openUC2 uses these to carry the grid and its iMates (MAS - 0002 - Frame
    6x6 iMates has 96 work points and no solid). They export as a valid but
    empty STEP and a 272-byte GLB, which is only ever noise downstream.
    """
    if safe(lambda: doc.DocumentType) != kPartDocumentObject:
        return False
    return safe(lambda: doc.ComponentDefinition.SurfaceBodies.Count) == 0


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def export_components(
    app,
    components: list[Component],
    stp_dir: Path,
    exporter: StepExporter,
    honour_model_states: bool = True,
    overwrite: bool = False,
    keep_empty: bool = False,
) -> dict[str, Path]:
    """Open each component document once, export STEP, leave the session as found."""
    stp_dir.mkdir(parents=True, exist_ok=True)
    produced: dict[str, Path] = {}
    ok = skipped = failed = empty = 0

    for n, comp in enumerate(components, 1):
        label = f"[{n}/{len(components)}] {comp.stem}"

        if not comp.path.exists():
            print(f"  {label}: MISSING source {comp.path}")
            comp.skip_reason = "source file not found"
            failed += 1
            continue

        stp_path = stp_dir / f"{comp.stem}.stp"
        if stp_path.exists() and not overwrite:
            print(f"  {label}: STP exists, skipping")
            produced[comp.stem] = stp_path
            skipped += 1
            continue

        print(f"  {label} ...", end=" ", flush=True)
        doc = find_open_document(app, comp.path)
        was_open = doc is not None
        previous_state = None
        started = time.time()
        try:
            if doc is None:
                doc = app.Documents.Open(str(comp.path), False)  # invisible

            if honour_model_states and comp.model_state:
                previous_state = active_model_state(doc)
                comp.resolved_state = activate_model_state(doc, comp.model_state)
                if comp.resolved_state == previous_state:
                    previous_state = None  # nothing was changed, nothing to restore
                # The state may have resolved to something else, which renames
                # the output; re-check that the new name isn't already there.
                stp_path = stp_dir / f"{comp.stem}.stp"
                if stp_path.exists() and not overwrite:
                    print("STP exists, skipping")
                    produced[comp.stem] = stp_path
                    skipped += 1
                    continue

            if not keep_empty and has_no_geometry(doc):
                print("no solid body (reference geometry), skipping")
                comp.skip_reason = "no solid body (skeleton / reference geometry)"
                empty += 1
                continue

            exporter.export(doc, stp_path)
            print(f"ok ({time.time() - started:.1f}s)")
            produced[comp.stem] = stp_path
            ok += 1
        except Exception as exc:
            print(f"FAILED ({exc})")
            comp.skip_reason = f"export failed: {exc}"
            failed += 1
        finally:
            if doc is not None:
                if previous_state:
                    activate_model_state(doc, previous_state)
                if not was_open:
                    safe(lambda: doc.Close(True))  # SkipSave

    summary = f"\nSTEP: {ok} exported, {skipped} skipped, {failed} failed"
    if empty:
        summary += f", {empty} without geometry"
    print(f"{summary} -> {stp_dir}")
    return produced


def convert_to_glb(
    stp_files: dict[str, Path],
    glb_dir: Path,
    tol_linear: float,
    tol_angular: float,
    overwrite: bool = False,
) -> dict[str, Path]:
    glb_dir.mkdir(parents=True, exist_ok=True)
    produced: dict[str, Path] = {}
    ok = skipped = failed = 0

    for n, (stem, stp_path) in enumerate(stp_files.items(), 1):
        glb_path = glb_dir / (stem.replace(" ", "_") + ".glb")
        label = f"[{n}/{len(stp_files)}] {glb_path.name}"

        if glb_path.exists() and not overwrite:
            print(f"  {label}: GLB exists, skipping")
            produced[stem] = glb_path
            skipped += 1
            continue

        print(f"  {label} ...", end=" ", flush=True)
        try:
            cascadio.step_to_glb(
                str(stp_path),
                str(glb_path),
                tol_linear=tol_linear,
                tol_angular=tol_angular,
            )
            add_mm_scale(glb_path)
            print("ok")
            produced[stem] = glb_path
            ok += 1
        except Exception as exc:
            print(f"FAILED ({exc})")
            failed += 1

    print(f"\nGLB: {ok} converted, {skipped} skipped, {failed} failed -> {glb_dir}")
    return produced


def write_manifest(
    path: Path,
    assembly: Path,
    components: list[Component],
    stp_files: dict[str, Path],
    glb_files: dict[str, Path],
    skipped: list[str],
    protocol: str,
) -> None:
    payload = {
        "assembly": str(assembly),
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "step_protocol": f"AP{protocol}",
        "components": [
            {
                "stem": c.stem,
                "source": str(c.path),
                "kind": c.kind,
                "model_state": c.model_state,
                "exported_model_state": c.resolved_state,
                "occurrences": c.names,
                "instance_count": len(c.names),
                "stp": str(stp_files[c.stem]) if c.stem in stp_files else None,
                "glb": str(glb_files[c.stem]) if c.stem in glb_files else None,
                "skipped_because": c.skip_reason,
            }
            for c in components
        ],
        "skipped_occurrences": skipped,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Manifest: {path}")


def main() -> None:
    _console_safe()
    parser = argparse.ArgumentParser(
        description="Export each top-level component of one Inventor assembly to STEP + GLB.",
    )
    parser.add_argument("assembly", nargs="?", type=Path,
                        help="The .iam to walk. Omit and pass --active to use the open one.")
    parser.add_argument("--active", action="store_true",
                        help="Use Inventor's active document instead of a path.")
    parser.add_argument("--out", type=Path, default=None, metavar="DIR",
                        help="Output folder (default: ./EXPORT/<assembly stem>). "
                             "STP/ and GLB/ are created inside it.")
    parser.add_argument("--ap", choices=sorted(AP_PROTOCOL), default="214",
                        help="STEP application protocol (default: 214). "
                             "AP203 carries no colour.")
    parser.add_argument("--tol-linear", type=float, default=0.1, metavar="F",
                        help="GLB linear tessellation tolerance (default: 0.1).")
    parser.add_argument("--tol-angular", type=float, default=0.5, metavar="F",
                        help="GLB angular tessellation tolerance in radians (default: 0.5).")
    parser.add_argument("--include-hidden", action="store_true",
                        help="Also export occurrences hidden in the browser.")
    parser.add_argument("--include-root", action="store_true",
                        help="Also export the whole assembly as one file.")
    parser.add_argument("--no-model-states", action="store_true",
                        help="Export each document's active state, ignoring the "
                             "state the occurrence references.")
    parser.add_argument("--keep-empty", action="store_true",
                        help="Also export parts with no solid body (skeleton / "
                             "reference geometry), which produce empty files.")
    parser.add_argument("--overwrite", action="store_true",
                        help="Re-export files that already exist.")
    parser.add_argument("--stp-only", action="store_true", help="Skip GLB conversion.")
    parser.add_argument("--dry-run", action="store_true",
                        help="List what would be exported and stop.")
    args = parser.parse_args()

    if not args.assembly and not args.active:
        parser.error("give an assembly path, or --active to use the open document")

    target = args.assembly.resolve() if args.assembly else None
    app = connect(target)

    if args.active:
        asm_doc = app.ActiveDocument
        if safe(lambda: asm_doc.DocumentType) != kAssemblyDocumentObject:
            sys.exit(f"Active document is not an assembly: {safe(lambda: asm_doc.FullFileName)}")
    else:
        asm_doc = find_open_document(app, target)
        if asm_doc is None:
            if not target.exists():
                sys.exit(f"Assembly not found: {target}")
            print(f"Opening {target.name} ...", flush=True)
            asm_doc = app.Documents.Open(str(target), False)

    assembly_path = Path(safe(lambda: asm_doc.FullFileName) or target)
    out_dir = (args.out or Path.cwd() / "EXPORT" / assembly_path.stem).resolve()

    print(f"Assembly : {assembly_path}")
    print(f"Output   : {out_dir}")
    print(f"STEP     : AP{args.ap}{' (no colour!)' if args.ap == '203' else ' with colours'}")
    print()

    components, skipped = collect_components(asm_doc, args.include_hidden)
    if args.include_root:
        components.insert(0, Component(
            path=assembly_path,
            model_state=None,
            doc_type=kAssemblyDocumentObject,
            names=["<root assembly>"],
        ))

    total_occurrences = sum(len(c.names) for c in components)
    print(f"{len(components)} unique component(s) from {total_occurrences} occurrence(s):")
    for comp in components:
        state = f"  <{comp.model_state}>" if comp.model_state else ""
        count = f" x{len(comp.names)}" if len(comp.names) > 1 else ""
        print(f"  - [{comp.kind:8}] {comp.stem}{count}{state}")
    if skipped:
        print(f"\nSkipped {len(skipped)} occurrence(s):")
        for entry in skipped:
            print(f"  - {entry}")
    print()

    if args.dry_run:
        print("--dry-run: nothing exported.")
        return
    if not components:
        sys.exit("Nothing to export.")

    exporter = StepExporter(app, AP_PROTOCOL[args.ap])
    safe(lambda: setattr(app, "SilentOperation", True))
    try:
        stp_files = export_components(
            app, components, out_dir / "STP", exporter,
            honour_model_states=not args.no_model_states,
            overwrite=args.overwrite,
            keep_empty=args.keep_empty,
        )
    finally:
        safe(lambda: setattr(app, "SilentOperation", False))

    glb_files: dict[str, Path] = {}
    if not args.stp_only:
        print()
        glb_files = convert_to_glb(
            stp_files, out_dir / "GLB", args.tol_linear, args.tol_angular, args.overwrite,
        )

    print()
    write_manifest(out_dir / "manifest.json", assembly_path, components,
                   stp_files, glb_files, skipped, args.ap)


if __name__ == "__main__":
    main()
