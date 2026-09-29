"""Top-level occurrence names of one or more Inventor assemblies (browser order)."""
import os
import sys
from pathlib import Path
import win32com.client


def safe(fn, d=None):
    try:
        return fn()
    except Exception:
        return d


app = win32com.client.GetActiveObject("Inventor.Application")
already = {(safe(lambda d=d: d.FullFileName) or "").lower() for d in app.Documents}
try:
    app.SilentOperation = True
except Exception:
    pass

for arg in sys.argv[1:]:
    p = Path(arg)
    print(f"\n=== {p.name} ===")
    if not p.exists():
        print("  MISSING")
        continue
    mine = str(p).lower() not in already
    if mine:
        doc = app.Documents.Open(str(p), False)
    else:
        doc = next(d for d in app.Documents
                   if (safe(lambda d=d: d.FullFileName) or "").lower() == str(p).lower())
    try:
        def walk(occs, depth):
            for occ in occs:
                name = safe(lambda: occ.Name, "?")
                t = safe(lambda: occ.Transformation.Translation)
                pos = "" if t is None else \
                    f"  @ ({t.X*10:8.2f},{t.Y*10:8.2f},{t.Z*10:8.2f})"
                sup = " [suppressed]" if safe(lambda: occ.Suppressed, False) else ""
                vis = "" if safe(lambda: occ.Visible, True) else " [hidden]"
                print(f"{'  ' * depth}- {name}{pos}{sup}{vis}")
                if depth < DEPTH:
                    kids = safe(lambda: occ.SubOccurrences)
                    if kids is not None and safe(lambda: kids.Count, 0):
                        walk(kids, depth + 1)
        DEPTH = int(os.environ.get("DEPTH", "1"))
        walk(doc.ComponentDefinition.Occurrences, 0)
    finally:
        if mine:
            safe(lambda: doc.Close(True))
