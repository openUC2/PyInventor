#!/usr/bin/env python3
"""Read what is inside each openUC2 kit, straight from the KIT assemblies (read-only).

    python kit_bom.py <KIT folder or .iam> [...] --out <dir>

A folder is scanned one level deep; per sub-folder the newest batch is read
(``KIT - CORE - COR-25-02.iam`` -> batch 25-02; files with a suffix such as
``_BD`` or ``-BD`` are skipped). Uses Inventor Apprentice, so it runs beside an
open Inventor without touching its session and never saves.

Writes ``<out>/<kit>.json`` per kit: the top-level items with their count,
BOM structure and iProperties, and for every sub-assembly its leaf parts
(through SUB and phantom levels) so a module's optic can be named.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

try:
    import pythoncom
    import win32com.client
except ImportError:
    sys.exit("pywin32 not found. Install it with: pip install pywin32")

#: Inventor Apprentice. Its ProgID is not registered for 64-bit Python, the CLSID is.
APPRENTICE_CLSID = "{C343ED84-A129-11D3-B799-0060B0F159EF}"
kAssemblyDocumentObject = 12291
BOM = {51969: "default", 51970: "normal", 51971: "phantom", 51972: "reference",
       51973: "purchased", 51974: "inseparable", 51975: "varies"}
_MODEL_STATE_RE = re.compile(r"^(?P<path>.*?)<(?P<state>[^<>]*)>$")
_BATCH_RE = re.compile(r"(\d{2})-(\d{2})$")


def safe(fn, default=None):
    """Inventor's COM surface raises for properties that merely don't apply."""
    try:
        return fn()
    except Exception:
        return default


def split_model_state(full: str) -> tuple[str, str | None]:
    m = _MODEL_STATE_RE.match(full or "")
    return (m.group("path"), m.group("state") or None) if m else (full, None)


def iprops(doc) -> dict:
    def prop(group, name):
        return safe(lambda: doc.PropertySets.Item(group).Item(name).Value)
    return {
        "part_number": prop("Design Tracking Properties", "Part Number"),
        "description": prop("Design Tracking Properties", "Description"),
        "stock_number": prop("Design Tracking Properties", "Stock Number"),
        "cost": prop("Design Tracking Properties", "Cost"),
        "vendor": prop("Design Tracking Properties", "Vendor"),
        "revision": prop("Inventor Summary Information", "Revision Number"),
    }


def leaf_parts(comp_def, acc: dict, subs: dict, depth: int = 0) -> None:
    """Count every part below *comp_def*; reference occurrences are not BOM items."""
    occs = safe(lambda: comp_def.Occurrences)
    if occs is None or depth > 8:
        return
    for i in range(1, safe(lambda: occs.Count, 0) + 1):
        occ = occs.Item(i)
        if safe(lambda: occ.Suppressed) is True or BOM.get(safe(lambda: occ.BOMStructure)) == "reference":
            continue
        full = safe(lambda: occ.ReferencedDocumentDescriptor.FullDocumentName)
        if not full:
            continue
        stem = Path(split_model_state(full)[0]).stem
        if safe(lambda: occ.DefinitionDocumentType) == kAssemblyDocumentObject:
            subs[stem] = subs.get(stem, 0) + 1
            sub = safe(lambda: occ.Definition)
            if sub is not None:
                leaf_parts(sub, acc, subs, depth + 1)
        else:
            acc[stem] = acc.get(stem, 0) + 1


def read_kit(app, path: Path) -> dict:
    doc = app.Open(str(path))
    try:
        occs = doc.ComponentDefinition.Occurrences
        items: dict[tuple, dict] = {}
        skipped = []
        for i in range(1, occs.Count + 1):
            occ = occs.Item(i)
            name = safe(lambda: occ.Name) or f"<occurrence {i}>"
            if safe(lambda: occ.Suppressed) is True:
                skipped.append(f"{name} (suppressed)")
                continue
            desc = safe(lambda: occ.ReferencedDocumentDescriptor)
            full = safe(lambda: desc.FullDocumentName) if desc else None
            if not full:
                skipped.append(f"{name} (virtual component)")
                continue
            file, state = split_model_state(full)
            key = (file.lower(), state)
            if key not in items:
                is_asm = safe(lambda: occ.DefinitionDocumentType) == kAssemblyDocumentObject
                ref = safe(lambda: desc.ReferencedDocument)
                item = {
                    "stem": Path(file).stem, "path": file, "exists": Path(file).exists(),
                    "kind": "assembly" if is_asm else "part", "model_state": state,
                    "bom_structure": BOM.get(safe(lambda: occ.BOMStructure)),
                    "iprops": iprops(ref) if ref is not None else {},
                    "occurrences": [], "hidden": [],
                }
                if is_asm:
                    acc, subs = {}, {}
                    sub = safe(lambda: occ.Definition)
                    if sub is not None:
                        leaf_parts(sub, acc, subs)
                    item["contents"], item["sub_assemblies"] = dict(sorted(acc.items())), subs
                items[key] = item
            items[key]["occurrences"].append(name)
            if safe(lambda: occ.Visible) is False:
                items[key]["hidden"].append(name)
        for item in items.values():
            item["count"] = len(item["occurrences"])
        return {
            "kit": path.stem, "path": str(path),
            "modified": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(path.stat().st_mtime)),
            "read_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "kit_iprops": iprops(doc), "items": list(items.values()), "skipped": skipped,
        }
    finally:
        safe(lambda: doc.Close())


def newest_kits(folder: Path) -> list[Path]:
    """The newest batch per sub-folder of the KIT folder."""
    found = []
    for sub in sorted(p for p in folder.iterdir() if p.is_dir() and p.name != "OldVersions"):
        batches = [(m.groups(), p) for p in sub.glob("KIT*.iam") if (m := _BATCH_RE.search(p.stem))]
        if batches:
            found.append(max(batches)[1])
    return found


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        safe(lambda: stream.reconfigure(errors="replace"))
    parser = argparse.ArgumentParser(description="Read the contents of openUC2 KIT assemblies.")
    parser.add_argument("paths", nargs="+", type=Path, help="KIT folder (newest batch per sub-folder) or kit .iam files")
    parser.add_argument("--out", type=Path, required=True, help="Folder for the JSON files")
    args = parser.parse_args()

    kits = []
    for p in args.paths:
        kits.extend(newest_kits(p) if p.is_dir() else [p])
    args.out.mkdir(parents=True, exist_ok=True)

    pythoncom.CoInitialize()
    app = win32com.client.Dispatch(APPRENTICE_CLSID)
    print("Apprentice project:", safe(lambda: app.DesignProjectManager.ActiveDesignProject.FullFileName))
    for kit in kits:
        started = time.time()
        print(f"  {kit.name} ...", end=" ", flush=True)
        try:
            data = read_kit(app, kit)
        except Exception as exc:
            print(f"FAILED ({exc})")
            continue
        (args.out / f"{kit.stem}.json").write_text(
            json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        missing = sum(not i["exists"] for i in data["items"])
        print(f"{len(data['items'])} items{f', {missing} missing files' if missing else ''} ({time.time() - started:.1f}s)")


if __name__ == "__main__":
    main()
