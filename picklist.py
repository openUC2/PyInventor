#!/usr/bin/env python3
"""Pick list for the warehouse: everything needed to build a kit's modules, as one PDF.

    python picklist.py "MANUALS/KIT - CORE - COR-25-02" --kit "...\\KIT\\CORE\\KIT - CORE - COR-25-02.iam"
    python picklist.py "MANUALS"                     # every <module>.manual.json in the folder
    python assembly_manual.py --kit "...\\KIT\\CORE" --picklist     # manuals first, then this

Reads the parts lists that ``assembly_manual.py`` stored in ``<module>.manual.json``
(no Inventor session needed) and writes ``<title> - Teileliste.pdf`` (+ ``.csv``):

  * the list: every part with its Inventor name, quantity, BUY/PRT and the
    modules it goes into, with a box to tick; a kit's modules are counted as
    often as the kit holds them, and parts placed loose in the kit are added;
  * one page (more if needed) of pictures of the BUY parts and one of the PRT
    parts, each with its list position and quantity, to find them on the shelf.

The pictures are rendered from the part files through Inventor Apprentice
(``part_render.py``), so it runs beside an Inventor that is busy with something
else, and they are cached next to the PDF for the next run.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

#: Bump when the pictures change, so cached ones are redrawn.
RENDER_VERSION = "2"
PAPER = {"a4": (297.0, 210.0), "a3": (420.0, 297.0)}
_MODEL_STATE_RE = re.compile(r"^(?P<path>.*?)<(?P<state>[^<>]*)>$")
_STANDARD_RE = re.compile(r"^(ISO|DIN|EN|STD)\b|screw|schraube|washer|scheibe|\bpin\b|stift|\bnut\b|mutter|"
                          r"o-ring", re.I)


@dataclass
class Item:
    key: str                    # full document name (path<model state>) or virtual:<name>
    part_number: str
    description: str
    qty: int = 0
    used_in: dict = field(default_factory=dict)   # module label -> quantity
    pos: int = 0
    image: Path | None = None

    @property
    def name(self) -> str:
        return self.part_number or Path(_MODEL_STATE_RE.sub(r"\g<path>", self.key)).stem

    @property
    def category(self) -> str:
        """PRT: openUC2's own (mostly printed) parts; BUY: everything bought, standard parts, electronics."""
        return "PRT" if re.match(r"\s*PRT\b", self.name, re.I) else "BUY"

    @property
    def sort_key(self) -> tuple:
        n = self.name
        group = 0 if n.upper().startswith("BUY") else (2 if _STANDARD_RE.search(n) else 1)
        return (group, re.sub(r"\d+", lambda m: m.group().zfill(6), n.lower()))


def module_label(stem: str) -> str:
    """'ASS - 2021 - CUBLEND40F50 - V04' -> '2021'."""
    m = re.match(r"^\s*[A-Z]+\s*-\s*(\d+)\b", stem)
    return m.group(1) if m else stem


# ---------------------------------------------------------------------------
# Collecting
# ---------------------------------------------------------------------------

def load_manuals(folder: Path, only: set[str] | None = None) -> dict[str, dict]:
    out = {}
    for js in sorted(folder.glob("*.manual.json")):
        try:
            data = json.loads(js.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        stem = data.get("module") or js.name[: -len(".manual.json")]
        if only is None or stem in only:
            out[stem] = data
    return out


def kit_contents(kit: Path) -> tuple[dict[str, int], list[dict]]:
    """Module counts by stem and the loose parts of a kit assembly (read with Apprentice)."""
    from kit_bom import read_kit
    from part_render import Apprentice
    data = read_kit(Apprentice(), kit)
    modules: dict[str, int] = {}
    loose: list[dict] = []
    for it in data["items"]:
        if it.get("bom_structure") in ("reference", "phantom") and it["kind"] == "part":
            continue
        if it["kind"] == "assembly":
            modules[it["stem"]] = modules.get(it["stem"], 0) + it["count"]
        else:
            loose.append(it)
    return modules, loose


def collect(manuals: dict[str, dict], module_counts: dict[str, int] | None = None,
            loose: list[dict] | None = None) -> list[Item]:
    items: dict[str, Item] = {}
    for stem, data in manuals.items():
        k = (module_counts or {}).get(stem, 1)
        if module_counts is not None and stem not in module_counts:
            continue  # a manual in the folder that is not part of this kit
        label = module_label(stem)
        for row in data.get("bom", []):
            key = row.get("file") or f"virtual:{row.get('part_number')}"
            it = items.setdefault(key, Item(key, row.get("part_number") or "", row.get("description") or ""))
            n = int(row.get("qty") or 0) * k
            it.qty += n
            it.used_in[label] = it.used_in.get(label, 0) + n
    for row in loose or []:
        key = row["path"] + (f"<{row['model_state']}>" if row.get("model_state") else "")
        props = row.get("iprops") or {}
        it = items.setdefault(key, Item(key, props.get("part_number") or row["stem"], props.get("description") or ""))
        it.qty += row["count"]
        it.used_in["Kit"] = it.used_in.get("Kit", 0) + row["count"]
    ordered = sorted((i for i in items.values() if i.category == "BUY"), key=lambda i: i.sort_key)
    ordered += sorted((i for i in items.values() if i.category == "PRT"), key=lambda i: i.sort_key)
    for n, it in enumerate(ordered, 1):
        it.pos = n
    return ordered


# ---------------------------------------------------------------------------
# Pictures
# ---------------------------------------------------------------------------

def render_images(items: list[Item], cache: Path, size: int = 420, log=print) -> None:
    from PIL import Image
    from part_render import Apprentice, part_meshes, render
    cache.mkdir(parents=True, exist_ok=True)
    prefix = f"v{RENDER_VERSION}-"
    for old in cache.glob("*.png"):
        if not old.name.startswith(prefix):
            old.unlink(missing_ok=True)  # drawn by an older version
    app = None
    todo = []
    for it in items:
        if it.key.startswith("virtual:"):
            continue
        path = Path(_MODEL_STATE_RE.sub(r"\g<path>", it.key))
        stamp = f"{it.key}|{path.stat().st_mtime if path.exists() else 0}|{size}"
        png = cache / (prefix + hashlib.sha1(stamp.encode("utf-8")).hexdigest()[:16] + ".png")
        if png.exists():
            it.image = png
        else:
            todo.append((it, png))
    for n, (it, png) in enumerate(todo, 1):
        if app is None:
            app = Apprentice()
        t0 = time.time()
        meshes = part_meshes(app, it.key)
        if not meshes:
            log(f"    [{n}/{len(todo)}] {it.name}: no geometry")
            continue
        Image.fromarray(render(meshes, size=size, view_from=None)).save(png)  # flat parts face-on
        it.image = png
        log(f"    [{n}/{len(todo)}] {it.name} ({time.time() - t0:.1f}s)")


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _logo(manuals: dict[str, dict]) -> Path | None:
    """The openUC2 logo from the CAD workspace the modules come from."""
    for data in manuals.values():
        p = Path(data.get("assembly", ""))
        for parent in p.parents:
            cand = parent / "openUC2-GmbH-Logo.png"
            if cand.exists():
                return cand
    return None


class Pages:
    """Matplotlib pages in millimetres, origin bottom left."""

    def __init__(self, path: Path, paper: str, title: str, subtitle: str, logo: Path | None):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
        matplotlib.rcParams["pdf.fonttype"] = 42
        matplotlib.rcParams["font.family"] = "DejaVu Sans"
        self.plt = plt
        self.W, self.H = PAPER[paper]
        self.pdf = PdfPages(str(path))
        self.title, self.subtitle = title, subtitle
        self.logo = None
        if logo is not None:
            from PIL import Image
            self.logo = np.asarray(Image.open(logo).convert("RGBA"))
        self.figs = []

    def new(self, heading: str):
        fig = self.plt.figure(figsize=(self.W / 25.4, self.H / 25.4))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, self.W)
        ax.set_ylim(0, self.H)
        ax.axis("off")
        m = 10.0
        ax.text(m, self.H - m - 1, self.title, fontsize=14, weight="bold", va="top")
        ax.text(m, self.H - m - 8.5, heading, fontsize=10.5, va="top", color="#333333")
        ax.text(m + 105, self.H - m - 8.5, self.subtitle, fontsize=8, va="top", color="#666666")
        if self.logo is not None:
            h = 11.0
            w = h * self.logo.shape[1] / self.logo.shape[0]
            ax.imshow(self.logo, extent=(self.W - m - w, self.W - m, self.H - m - h, self.H - m), aspect="auto",
                      interpolation="antialiased", zorder=3)
        ax.plot([m, self.W - m], [self.H - m - 14.5, self.H - m - 14.5], color="#999999", lw=0.6)
        self.figs.append((fig, ax))
        return ax

    @property
    def top(self) -> float:
        return self.H - 10.0 - 17.0

    def close(self) -> None:
        total = len(self.figs)
        for n, (fig, ax) in enumerate(self.figs, 1):
            ax.text(self.W - 10, 6, f"Seite {n} / {total}", fontsize=7, ha="right", color="#666666")
            ax.text(10, 6, "openUC2 · Teileliste aus Inventor (assembly_manual.py / picklist.py) · "
                    + time.strftime("%d.%m.%Y"), fontsize=6.5, color="#888888")
            self.pdf.savefig(fig)
            self.plt.close(fig)
        self.pdf.close()


def _fit(text: str, width_mm: float, size_pt: float, lines: int = 1) -> list[str]:
    """Wrap to *lines* lines of about *width_mm* (DejaVu: ~0.2 mm per pt per char), ellipsis if longer."""
    per_line = max(4, int(width_mm / (0.195 * size_pt)))
    wrapped = textwrap.wrap(text or "", per_line, break_long_words=True) or [""]
    if len(wrapped) > lines:
        wrapped = wrapped[:lines]
        wrapped[-1] = wrapped[-1][: max(1, per_line - 1)].rstrip() + "…"
    return wrapped


def _used_in(it: Item) -> str:
    return ", ".join(f"{k} ({v}x)" if v > 1 else k for k, v in it.used_in.items())


def list_pages(pages: Pages, items: list[Item]) -> None:
    from matplotlib.patches import Rectangle
    m = 10.0
    cols = [("", 6), ("POS", 10), ("ANZ.", 12), ("BAUTEILNUMMER (Inventor)", 92), ("BESCHREIBUNG", 70),
            ("TYP", 12), ("VERWENDET IN", 0)]
    width = pages.W - 2 * m
    cols[-1] = (cols[-1][0], width - sum(w for _, w in cols[:-1]))
    xs = np.cumsum([m] + [w for _, w in cols])
    size = 7.3
    line_h = 3.4

    rows: list[tuple[str, object]] = []
    for cat, label in (("BUY", "BUY – Kaufteile, Normteile, Elektronik"), ("PRT", "PRT – eigene Teile (Druck/Fertigung)")):
        group = [i for i in items if i.category == cat]
        if group:
            rows.append(("group", f"{label}   ({len(group)} Positionen, {sum(i.qty for i in group)} Stück)"))
            rows.extend(("item", i) for i in group)

    def page():
        ax = pages.new("Liste – alle Teile zum Bauen")
        y = pages.top
        ax.add_patch(Rectangle((m, y - 5.2), width, 5.2, color="#e6e6e6", lw=0))
        for (title, _), x in zip(cols, xs):
            ax.text(x + 1.2, y - 2.6, title, fontsize=7, weight="bold", va="center")
        return ax, y - 5.2

    ax, y = page()
    stripe = False
    for kind, obj in rows:
        if kind == "group":
            h = 6.0
        else:
            pn = _fit(obj.name, cols[3][1] - 2, size, 2)
            ds = _fit(obj.description, cols[4][1] - 2, size, 2)
            us = _fit(_used_in(obj), cols[6][1] - 2, size - 0.6, 2)
            h = max(len(pn), len(ds), len(us)) * line_h + 2.0
        if y - h < 12:
            ax, y = page()
            stripe = False
        if kind == "group":
            ax.text(m + 1.2, y - 3.6, obj, fontsize=8, weight="bold", va="center", color="#1a4d80")
            ax.plot([m, m + width], [y - h, y - h], color="#1a4d80", lw=0.6)
            y -= h
            continue
        if stripe:
            ax.add_patch(Rectangle((m, y - h), width, h, color="#f4f4f4", lw=0))
        stripe = not stripe
        cy = y - 1.0 - line_h / 2
        ax.add_patch(Rectangle((xs[0] + 1.3, cy - 1.6), 3.2, 3.2, fill=False, lw=0.6, ec="#555555"))
        ax.text(xs[1] + 1.2, cy, str(obj.pos), fontsize=size, va="center")
        ax.text(xs[2] + 1.2, cy, f"{obj.qty}x", fontsize=size + 0.5, va="center", weight="bold")
        for k, s in enumerate(pn):
            ax.text(xs[3] + 1.2, cy - k * line_h, s, fontsize=size, va="center")
        for k, s in enumerate(ds):
            ax.text(xs[4] + 1.2, cy - k * line_h, s, fontsize=size, va="center", color="#333333")
        ax.text(xs[5] + 1.2, cy, obj.category, fontsize=size, va="center",
                color="#1a4d80" if obj.category == "BUY" else "#8a4b00")
        for k, s in enumerate(us):
            ax.text(xs[6] + 1.2, cy - k * line_h, s, fontsize=size - 0.6, va="center", color="#444444")
        y -= h


def _grid(n: int, area_w: float, area_h: float, min_w: float = 34.0) -> tuple[int, int, float, float]:
    """Columns, rows, cell width, cell height: the biggest cells that hold *n* on one page."""
    best = None
    for c in range(2, 13):
        w = area_w / c
        h = w * 1.12
        r = int(area_h // h)
        if r < 1:
            continue
        if c * r >= n:
            return c, r, w, h
        best = (c, r, w, h)
        if w < min_w:
            break
    return best


def picture_pages(pages: Pages, items: list[Item], heading: str) -> None:
    from matplotlib.patches import FancyBboxPatch
    from PIL import Image
    if not items:
        return
    m = 10.0
    area_w, area_h = pages.W - 2 * m, pages.top - 12.0
    c, r, w, h = _grid(len(items), area_w, area_h)
    per_page = c * r
    for start in range(0, len(items), per_page):
        chunk = items[start:start + per_page]
        more = f" ({start // per_page + 1}/{(len(items) - 1) // per_page + 1})" if len(items) > per_page else ""
        ax = pages.new(heading + more)
        for k, it in enumerate(chunk):
            col, row = k % c, k // c
            x0 = m + col * w
            y1 = pages.top - row * h
            pad = 1.2
            ax.add_patch(FancyBboxPatch((x0 + pad, y1 - h + pad), w - 2 * pad, h - 2 * pad,
                                        boxstyle="round,pad=0,rounding_size=1.6", fill=False, lw=0.5, ec="#bbbbbb"))
            text_h = 11.5
            box = (x0 + 2 * pad, y1 - h + text_h, w - 4 * pad, h - text_h - 7.5)  # x, y, w, h: below the top strip
            if it.image is not None:
                img = np.asarray(Image.open(it.image))
                ih, iw = img.shape[:2]
                s = min(box[2] / iw, box[3] / ih)
                dw, dh = iw * s, ih * s
                cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
                ax.imshow(img, extent=(cx - dw / 2, cx + dw / 2, cy - dh / 2, cy + dh / 2), aspect="auto",
                          interpolation="antialiased", zorder=2)
            else:
                ax.text(box[0] + box[2] / 2, box[1] + box[3] / 2, "kein CAD", fontsize=7, ha="center",
                        va="center", color="#999999")
            ax.text(x0 + 2.8, y1 - 4.2, f"Pos. {it.pos}", fontsize=7, va="center", color="#555555")
            ax.text(x0 + w - 2.8, y1 - 4.4, f"{it.qty}x", fontsize=12, weight="bold", ha="right", va="center")
            lines = _fit(it.name, w - 6, 6.2, 2)
            for j, s in enumerate(lines):
                ax.text(x0 + 2.8, y1 - h + text_h - 2.4 - j * 2.9, s, fontsize=6.2, weight="bold", va="center")
            desc = _fit(it.description, w - 6, 5.6, 1)[0]
            ax.text(x0 + 2.8, y1 - h + 3.4, desc, fontsize=5.6, va="center", color="#555555")


def make_picklist(folder: Path, title: str | None = None, kit: Path | None = None, only: set[str] | None = None,
                  paper: str = "a4", log=print) -> Path | None:
    """Write ``<title> - Teileliste.pdf`` (+ .csv) into *folder*; returns the PDF path."""
    folder = Path(folder)
    manuals = load_manuals(folder, only)
    if only and set(only) - set(manuals):
        log("  ! no manual for: " + ", ".join(sorted(set(only) - set(manuals))))
    module_counts, loose = (None, None)
    if kit is not None:
        log(f"  reading {kit.name} ...")
        module_counts, loose = kit_contents(kit)
        missing = [s for s in module_counts if s not in manuals]
        if missing:
            log(f"  ! no manual (yet) for {len(missing)} module(s) of the kit: " + ", ".join(missing))
    if not manuals and not loose:
        log("  no *.manual.json found - run assembly_manual.py first")
        return None
    items = collect(manuals, module_counts, loose)
    title = title or (kit.stem if kit else folder.name)
    n_modules = sum(module_counts.values()) if module_counts else len(manuals)
    log(f"  {len(items)} positions, {sum(i.qty for i in items)} pieces from {n_modules} module(s)"
        + (f" + {len(loose)} loose kit part(s)" if loose else ""))
    render_images(items, folder / ".picklist-images", log=log)

    pdf = folder / f"{title} - Teileliste.pdf"
    subtitle = (f"{n_modules} Module · {len(items)} Positionen · {sum(i.qty for i in items)} Teile"
                f" · Stand {time.strftime('%d.%m.%Y')}")
    pages = Pages(pdf, paper, f"Teileliste – {title}", subtitle, _logo(manuals))
    list_pages(pages, items)
    picture_pages(pages, [i for i in items if i.category == "BUY"], "BUY-Teile – Bilder zum Suchen im Lager")
    picture_pages(pages, [i for i in items if i.category == "PRT"], "PRT-Teile – Bilder zum Suchen im Lager")
    pages.close()

    with open(folder / f"{title} - Teileliste.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["Pos", "Anzahl", "Bauteilnummer", "Beschreibung", "Typ", "Verwendet in", "Datei"])
        for it in items:
            w.writerow([it.pos, it.qty, it.name, it.description, it.category, _used_in(it), it.key])
    log(f"  -> {pdf.name}")
    return pdf


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("folder", type=Path, help="folder with <module>.manual.json files (an assembly_manual.py output)")
    ap.add_argument("--kit", type=Path, default=None, help="the kit .iam: module counts and loose kit parts")
    ap.add_argument("--title", default=None, help="title and file name (default: kit or folder name)")
    ap.add_argument("--modules", nargs="*", default=None, help="only these module stems")
    ap.add_argument("--paper", choices=sorted(PAPER), default="a4", help="page size, landscape (default a4)")
    args = ap.parse_args()
    pdf = make_picklist(args.folder.resolve(), args.title, args.kit.resolve() if args.kit else None,
                        set(args.modules) if args.modules else None, args.paper)
    return 0 if pdf else 1


if __name__ == "__main__":
    sys.exit(main())
