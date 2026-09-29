#!/usr/bin/env python3
"""Export an Inventor assembly to STEP with only the parts that give it its shape.

Electronics, fasteners, cables and most purchased parts carry most of a
production export's bytes and none of its silhouette: FRAME #0008 is 269 MB,
of which ~200 MB is boards, backpacks and the Raspberry Pi and 47 MB is
twenty-five puzzle joints. This hides them and exports what is left.

How it works, and why it is safe to run while the file is open:

  * Inventor's STEP writer skips HIDDEN components, and `Visible = False`
    can be set on a sub-occurrence proxy at any depth from the parent. So
    nothing needs suppressing and no child document is edited.
  * The work happens on a private sibling copy of the top-level .iam (same
    folder, so every reference resolves; inside the project workspace, so it
    is modifiable). The copy is closed without saving and deleted. The
    original — even one open and dirty in your session — is never touched.
  * Rules are data (`--config`), so the same script runs on any assembly.
    Every node name the optikit spec uses can be protected with `--keep`.

Requirements: a running licensed Autodesk Inventor with the assembly's
project active, pywin32.

Usage:
  python export_shape_step.py "FRAME #0008 - Microscope incl accessories.iam" --out DIR
  python export_shape_step.py "…iam" --dry-run           # classify, export nothing
  python export_shape_step.py "…iam" --config rules.json --keep "Electronics box" "HIKROBOT"
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    import pythoncom
    import win32com.client
except ImportError:
    sys.exit("pywin32 not found. Install it with: pip install pywin32")

STEP_TRANSLATOR_ID = "{90AF7F40-0C01-11D5-8E83-0010B541CD80}"
kFileBrowseIOMechanism = 13059
kAssemblyDocumentObject = 12291
AP_PROTOCOL = {"203": 2, "214": 3, "242": 4}

# ---------------------------------------------------------------------------
# Rules. Order matters: the first rule that matches decides. `keep` patterns
# (and --keep) win over everything.
# ---------------------------------------------------------------------------

DEFAULT_RULES: dict = {
    # Never hide these, whatever the other rules say (regex, case-insensitive).
    "keep": [
        r"camera|usbcam|\bcam\b", r"objectiv", r"\blens\b(?!\s*head)|LEND|ACL25", r"tubus",
        r"mirror|dichroic|filter", r"stepping motor|nema", r"electronics box",
    ],
    # Hide: openUC2/FRAME electronics numbering (5xxx), boards, hubs, cables.
    # Deliberately no bare "usb"/"connector": `Upper cladding Z stage with USB`
    # is a cover and `Connector spindel` a spindle.
    "electronics": [
        r"^(FR110|FRAME)\s*-\s*5\d{3}\s*-", r"^(BRD|ELE)\s*-", r"raspberry.?pi|raspi",
        r"\bpcb\b|\bboard\b|backpack|hat[\s-]|\bhub\b|stacking header|solder jumper",
        r"esp32|xiao|\bmcu\b|tmc2209|motor ?driver|power supply|cooler|cooling star|\bfan\b",
        r"wifi|sd card|micro.?sd|argb|led light bar|light barrier|hard drive|battery|display",
    ],
    # Hide: cables themselves — not the ducts, guides and covers that route them.
    "cable": [
        r"(^|[\s-])(cable|kabel)s?\b(?!\s*(duct|guide|holder|divider|cover|chain|clip|tie))",
        r"schleppkabel|\bwires?\b|patch cable|jumper",
    ],
    # Hide: the standard-parts library and loose hardware by name.
    "fastener": [
        r"^(ISO|DIN|GB/T|ANSI|JIS|BS|NF|UNI|SFS)[\s_-]",
        r"screw|washer|threaded pin|sleeve nut|hexagon|hex nut|circlip|dowel",
        r"grub|spring pin|retaining ring|magnet|threaded bushing|insert nut",
        r"cover cap|star knob|schraube|mutter|scheibe|bolt",
    ],
    # Hide: the puzzle joints between cubes — joints, not shape.
    "joint": [r"PUZ\d|puzzle"],
    # Hide: what sits INSIDE a cube — openUC2's PRT-2xxx inserts, master
    # inserts and lock rings (the 1xxx cube halves and plates stay). Disable
    # with `--skip-rule insert` when the cube contents matter.
    # Parts only: `ASS - 2058 - CUBTBSHOLD28.5` is the CUBE that holds one.
    "insert": [r"^PRT\s*-\s*2\d{3}\s*-", r"^PRT\s*-.*(MASINS|MASLCK|TBSHOLD|\bINS[A-Z])"],
    # Purchased parts are hidden unless a `keep` pattern claims them.
    "buy_prefix": r"^BUY\s*-",
    # Leaf parts smaller than this (largest bounding-box side, mm) are hidden.
    "small_mm": 12.0,
}


@dataclass
class Rules:
    keep: list[re.Pattern]
    named: dict[str, list[re.Pattern]]
    buy_prefix: re.Pattern | None
    small_mm: float
    protect: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, config: dict, protect: list[str]) -> Rules:
        rx = lambda pats: [re.compile(p, re.I) for p in pats]  # noqa: E731
        named = {k: rx(v) for k, v in config.items()
                 if isinstance(v, list) and k != "keep"}
        return cls(
            keep=rx(config.get("keep", [])),
            named=named,
            buy_prefix=re.compile(config["buy_prefix"], re.I) if config.get("buy_prefix") else None,
            small_mm=float(config.get("small_mm", 0) or 0),
            protect=[p.lower() for p in protect],
        )

    def classify(self, name: str, *, is_part: bool, extent_mm: float, content_center: bool) -> str | None:
        """The rule that hides this occurrence, or None to keep it."""
        low = name.lower()
        if any(p in low for p in self.protect) or any(r.search(name) for r in self.keep):
            return None
        if content_center:
            return "standard"
        for why, patterns in self.named.items():
            if any(r.search(name) for r in patterns):
                return why
        if self.buy_prefix is not None and self.buy_prefix.search(name):
            return "buy"
        if is_part and 0 < extent_mm < self.small_mm:
            return "small"
        return None


# ---------------------------------------------------------------------------
# Inventor helpers
# ---------------------------------------------------------------------------

def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _nvm_put(options, key, value):
    try:
        options.Add(key, value)
        return
    except Exception:
        pass
    dispid = options._oleobj_.GetIDsOfNames("Value")
    options._oleobj_.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYPUT, 0, key, value)


def export_step(app, doc, out_path: Path, protocol: int) -> None:
    translator = app.ApplicationAddIns.ItemById(STEP_TRANSLATOR_ID)
    if not safe(lambda: translator.Activated):
        translator.Activate()
    t = app.TransientObjects
    context = t.CreateTranslationContext()
    context.Type = kFileBrowseIOMechanism
    options = t.CreateNameValueMap()
    medium = t.CreateDataMedium()
    if translator.HasSaveCopyAsOptions(doc, context, options):
        _nvm_put(options, "ApplicationProtocolType", protocol)
        _nvm_put(options, "IncludeSketches", False)
    medium.FileName = str(out_path)
    translator.SaveCopyAs(doc, context, options, medium)


def extent_mm(occ) -> float:
    box = safe(lambda: occ.RangeBox)
    if box is None:
        return -1.0
    lo, hi = box.MinPoint, box.MaxPoint
    return max(hi.X - lo.X, hi.Y - lo.Y, hi.Z - lo.Z) * 10.0  # cm → mm


def occurrence_path(occ) -> str:
    """Browser path, root-relative: `Hardware:1/Stage:1/screw:3`."""
    names = []
    cur = occ
    while cur is not None:
        names.append(safe(lambda: cur.Name, "?"))
        cur = safe(lambda: cur.ParentOccurrence)
    return "/".join(reversed(names))


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------

@dataclass
class Tally:
    hidden: dict[str, int] = field(default_factory=dict)
    kept: int = 0
    hidden_list: list[dict] = field(default_factory=list)

    def hide(self, why: str, occ, name: str) -> None:
        self.hidden[why] = self.hidden.get(why, 0) + 1
        self.hidden_list.append({"rule": why, "node": occurrence_path(occ), "name": name})


def walk(occurrences, rules: Rules, cc_path: str, tally: Tally, apply: bool) -> None:
    for occ in occurrences:
        if safe(lambda: occ.Suppressed, False) or not safe(lambda: occ.Visible, True):
            continue
        name = safe(lambda: occ.Name, "")
        ddoc = safe(lambda: occ.Definition.Document)
        is_part = safe(lambda: ddoc.DocumentType) != kAssemblyDocumentObject
        file = (safe(lambda: ddoc.FullFileName) or "").lower()
        content_center = (bool(cc_path) and file.startswith(cc_path)) or (
            "/content center files/" in file.replace("\\", "/")
        )
        why = rules.classify(name, is_part=is_part, extent_mm=extent_mm(occ),
                             content_center=content_center)
        if why is not None:
            tally.hide(why, occ, name)
            if apply:
                try:
                    occ.Visible = False
                except Exception as exc:
                    tally.hidden_list[-1]["error"] = str(exc)[:120]
            continue  # a hidden subassembly takes its children with it
        tally.kept += 1
        if not is_part:
            kids = safe(lambda: occ.SubOccurrences)
            if kids is not None and safe(lambda: kids.Count, 0):
                walk(kids, rules, cc_path, tally, apply)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("assembly", nargs="?", help="the top-level .iam")
    ap.add_argument("--out", default=None, help="output directory (default: beside the .iam)")
    ap.add_argument("--name", default=None, help="output STEP name (default: '<stem> - shape.stp')")
    ap.add_argument("--config", default=None, help="rules JSON (default: the built-in DEFAULT_RULES)")
    ap.add_argument("--keep", nargs="*", default=[],
                    help="substrings that are never hidden, e.g. the optikit spec's node names")
    ap.add_argument("--small-mm", type=float, default=None,
                    help="override the small-part threshold (0 disables)")
    ap.add_argument("--skip-rule", action="append", default=[], metavar="NAME",
                    help="disable one rule (electronics, cable, fastener, joint, insert, "
                         "buy_prefix, small_mm); repeatable")
    ap.add_argument("--ap", choices=sorted(AP_PROTOCOL), default="214")
    ap.add_argument("--dry-run", action="store_true", help="classify and report, export nothing")
    ap.add_argument("--dump-rules", action="store_true", help="print DEFAULT_RULES as JSON and exit")
    args = ap.parse_args()

    if args.dump_rules:
        print(json.dumps(DEFAULT_RULES, indent=2))
        return 0
    if not args.assembly:
        ap.error("the assembly .iam is required")

    src = Path(args.assembly).resolve()
    if not src.is_file():
        print(f"ERROR: no such assembly: {src}", file=sys.stderr)
        return 2
    config = dict(DEFAULT_RULES)
    if args.config:
        config.update(json.loads(Path(args.config).read_text(encoding="utf-8")))
    if args.small_mm is not None:
        config["small_mm"] = args.small_mm
    for name in args.skip_rule:
        if name not in config or name == "keep":
            ap.error(f"no such rule: {name!r} (rules: {', '.join(k for k in config if k != 'keep')})")
        config[name] = [] if isinstance(config[name], list) else (0 if name == "small_mm" else "")
    rules = Rules.load(config, args.keep)

    out_dir = Path(args.out) if args.out else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_step = out_dir / (args.name or f"{src.stem} - shape.stp")
    out_report = out_step.with_suffix(".report.json")

    app = win32com.client.GetActiveObject("Inventor.Application")
    cc_path = (safe(lambda: app.DesignProjectManager.ActiveDesignProject.ContentCenterPath) or "").lower()
    dirty_before = {d.FullFileName for d in app.Documents if safe(lambda d=d: d.FullFileName) and safe(lambda d=d: d.Dirty)}

    # The private copy: same folder so references resolve, a name nothing else uses.
    copy = src.with_name(f"{src.stem} - optikit-shape-tmp{src.suffix}")
    if copy.exists():
        copy.unlink()
    shutil.copy2(src, copy)

    prev_silent = safe(lambda: app.SilentOperation, False)
    prev_screen = safe(lambda: app.ScreenUpdating, True)
    doc = None
    t0 = time.time()
    tally = Tally()
    report: dict = {
        "source": str(src), "exported": time.strftime("%Y-%m-%d"),
        "rules": {k: v for k, v in config.items()}, "keep": args.keep,
        "referenced_documents_dirty_in_session": [],
    }
    try:
        app.SilentOperation = True
        app.ScreenUpdating = False
        doc = app.Documents.Open(str(copy), False)
        if not doc.IsModifiable:
            print("ERROR: the copy opened read-only — is the assembly's project active in Inventor?",
                  file=sys.stderr)
            return 2

        definition = doc.ComponentDefinition
        # Referenced documents come from memory: an edited, unsaved child shows
        # its edited state. Say so rather than silently export it.
        dirty_refs = sorted(
            d.DisplayName for d in app.Documents
            if safe(lambda d=d: d.Dirty) and d.FullFileName and d.FullFileName != str(copy)
        )
        report["referenced_documents_dirty_in_session"] = dirty_refs
        if dirty_refs:
            print(f"note: {len(dirty_refs)} referenced document(s) have unsaved edits in your "
                  f"session; the export shows them as they are in memory", flush=True)

        walk(definition.Occurrences, rules, cc_path, tally, apply=not args.dry_run)
        total_hidden = sum(tally.hidden.values())
        summary = ", ".join(f"{k} {v}" for k, v in sorted(tally.hidden.items(), key=lambda kv: -kv[1]))
        print(f"kept {tally.kept} occurrence(s), hid {total_hidden}: {summary}", flush=True)

        report.update({"kept": tally.kept, "hidden": tally.hidden, "hidden_list": tally.hidden_list})
        if args.dry_run:
            out_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"dry run - report in {out_report}")
            return 0

        t1 = time.time()
        export_step(app, doc, out_step, AP_PROTOCOL[args.ap])
        size = out_step.stat().st_size if out_step.is_file() else 0
        report.update({"step": str(out_step), "bytes": size,
                       "seconds": {"walk": round(t1 - t0, 1), "export": round(time.time() - t1, 1)}})
        print(f"wrote {out_step}  ({size / 1e6:.1f} MB, export {time.time() - t1:.0f}s)")
        out_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 0
    finally:
        if doc is not None:
            safe(lambda: setattr(doc, "Dirty", False))
            safe(lambda: doc.Close(True))  # SkipSave: the copy is never written
        safe(lambda: setattr(app, "ScreenUpdating", prev_screen))
        safe(lambda: setattr(app, "SilentOperation", prev_silent))
        copy.unlink(missing_ok=True)
        dirty_after = {d.FullFileName for d in app.Documents if safe(lambda d=d: d.FullFileName) and safe(lambda d=d: d.Dirty)}
        newly = sorted(dirty_after - dirty_before)
        if newly:
            print(f"WARNING: {len(newly)} document(s) became dirty during the run — this should "
                  f"not happen, please report it:\n  " + "\n  ".join(newly), file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
