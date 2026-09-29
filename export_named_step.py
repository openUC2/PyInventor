#!/usr/bin/env python3
"""Export named Inventor documents to STEP (AP214), one output name per input.

Reads a JSON manifest: [{"src": "<.ipt|.iam>", "out": "<slug>.stp"}, ...].
Documents already open in the running Inventor are left open; anything this
script opens, it closes.

Usage: python export_named_step.py manifest.json --out DIR [--overwrite]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pythoncom
import win32com.client

STEP_TRANSLATOR_ID = "{90AF7F40-0C01-11D5-8E83-0010B541CD80}"
kFileBrowseIOMechanism = 13059
AP214 = 3


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


class StepExporter:
    def __init__(self, app, protocol=AP214):
        self.app = app
        self.protocol = protocol
        self.translator = app.ApplicationAddIns.ItemById(STEP_TRANSLATOR_ID)
        if not safe(lambda: self.translator.Activated):
            self.translator.Activate()

    def export(self, doc, out_path: Path) -> None:
        t = self.app.TransientObjects
        context = t.CreateTranslationContext()
        context.Type = kFileBrowseIOMechanism
        options = t.CreateNameValueMap()
        medium = t.CreateDataMedium()
        if self.translator.HasSaveCopyAsOptions(doc, context, options):
            _nvm_put(options, "ApplicationProtocolType", self.protocol)
            _nvm_put(options, "IncludeSketches", False)
        medium.FileName = str(out_path)
        self.translator.SaveCopyAs(doc, context, options, medium)



def probe(doc) -> dict:
    """iProperties + the model's range box in mm — enough to identify a part."""
    info = {}
    for setname, keys in (
        ("Design Tracking Properties", ("Part Number", "Description", "Stock Number")),
        ("Inventor Summary Information", ("Comments",)),
        ("Summary Information", ("Title", "Author")),
    ):
        for key in keys:
            v = safe(lambda s=setname, k=key: doc.PropertySets.Item(s).Item(k).Value)
            if v:
                info[key] = str(v)
    box = safe(lambda: doc.ComponentDefinition.RangeBox)
    if box is not None:
        lo, hi = box.MinPoint, box.MaxPoint
        info["size_mm"] = [round((a - b) * 10, 2) for a, b in
                           ((hi.X, lo.X), (hi.Y, lo.Y), (hi.Z, lo.Z))]
        info["min_mm"] = [round(v * 10, 2) for v in (lo.X, lo.Y, lo.Z)]
    return info


def connect():
    try:
        return win32com.client.GetActiveObject("Inventor.Application")
    except Exception:
        app = win32com.client.Dispatch("Inventor.Application")
        app.Visible = True
        return app


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--out", required=True)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    jobs = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    app = connect()
    prev_silent = safe(lambda: app.SilentOperation, False)
    try:
        app.SilentOperation = True
    except Exception:
        pass

    already_open = {
        (safe(lambda d=d: d.FullFileName) or "").lower()
        for d in app.Documents
    }
    exporter = StepExporter(app)
    results = []

    for job in jobs:
        src = Path(job["src"])
        dst = out_dir / job["out"]
        rec = {"src": str(src), "out": str(dst)}
        if not src.exists():
            rec["status"] = "missing-source"
            results.append(rec)
            print(f"MISSING  {src}", flush=True)
            continue
        if dst.exists() and not args.overwrite:
            rec["status"] = "skipped-exists"
            results.append(rec)
            print(f"SKIP     {dst.name} (exists)", flush=True)
            continue

        opened_here = str(src).lower() not in already_open
        t0 = time.time()
        doc = None
        try:
            doc = app.Documents.Open(str(src), False) if opened_here else \
                app.Documents.ItemByName(str(src))
            exporter.export(doc, dst)
            rec["status"] = "ok"
            rec["seconds"] = round(time.time() - t0, 1)
            rec["bytes"] = dst.stat().st_size if dst.exists() else 0
            rec["probe"] = probe(doc)
            print(f"OK       {dst.name}  ({rec['bytes']/1e6:.1f} MB, {rec['seconds']}s)",
                  flush=True)
        except Exception as exc:
            rec["status"] = "error"
            rec["error"] = str(exc)
            print(f"ERROR    {src.name}: {exc}", flush=True)
        finally:
            if opened_here and doc is not None:
                safe(lambda: doc.Close(True))
        results.append(rec)

    try:
        app.SilentOperation = prev_silent
    except Exception:
        pass

    report = out_dir / "export-report.json"
    report.write_text(json.dumps(results, indent=2), encoding="utf-8")
    bad = [r for r in results if r["status"] not in ("ok", "skipped-exists")]
    print(f"\n{len(results) - len(bad)}/{len(results)} exported -> {out_dir}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
