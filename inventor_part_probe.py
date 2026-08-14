#!/usr/bin/env python3
"""Probe an Autodesk Inventor part (.ipt) through COM and dump its geometry
recipe as JSON: parameters, feature tree, sketches (entities + dimensions),
work features, face geometry (exact radii / cone angles / plane positions),
body vertices and mass properties. Optionally exports a fresh STEP copy.

The JSON is the ground truth used to re-author openUC2 parts as parametric
CadQuery code (see openuc2-cadquery). All lengths are converted from
Inventor's internal database units (cm) to millimetres, all angles to degrees.

Usage:
  python inventor_part_probe.py "PART.ipt" [more.ipt ...] --out-dir DIR [--step]

Requires a running (or startable) licensed Autodesk Inventor instance.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
from pathlib import Path

try:
    from win32com.client import Dispatch, GetActiveObject
except ImportError:
    sys.exit("pywin32 not found. Install it with: pip install pywin32")

# Caps so text-engraved molded parts don't produce megabyte dumps.
# Overridable via --max-faces / --max-vertices.
MAX_FACES = 600
MAX_VERTICES = 6000
MAX_SKETCH_POINTS = 300
MAX_SPLINE_FITPOINTS = 60

CM = 10.0  # internal database length unit (cm) -> mm

LENGTH_UNITS = {"mm", "cm", "m", "in", "ft", "um", "µm", "mil", "micron"}


def connect_inventor():
    try:
        return GetActiveObject("Inventor.Application")
    except Exception:
        app = Dispatch("Inventor.Application")
        app.Visible = True
        return app


def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def rnd(x, n=6):
    try:
        return round(float(x), n)
    except Exception:
        return None


def pt(p):
    """Inventor Point/Point2d -> mm list."""
    if p is None:
        return None
    z = safe(lambda: p.Z)
    if z is None:
        return [rnd(p.X * CM), rnd(p.Y * CM)]
    return [rnd(p.X * CM), rnd(p.Y * CM), rnd(z * CM)]


def vec(v):
    if v is None:
        return None
    return [rnd(v.X, 9), rnd(v.Y, 9), rnd(v.Z, 9)]


def conv_value(value, units):
    """Convert an internal parameter value (cm / rad) to mm / deg."""
    if value is None:
        return None
    u = (units or "").strip().lower()
    if u in LENGTH_UNITS:
        return rnd(value * CM)
    if u.startswith("deg") or u.startswith("rad"):
        return rnd(math.degrees(value))
    return rnd(value)


def dump_parameters(cd):
    out = []
    for group, tag in ((safe(lambda: cd.Parameters.ModelParameters), "model"),
                       (safe(lambda: cd.Parameters.UserParameters), "user"),
                       (safe(lambda: cd.Parameters.ReferenceParameters), "reference")):
        if group is None:
            continue
        for p in group:
            units = safe(lambda: p.Units)
            out.append({
                "name": safe(lambda: p.Name),
                "kind": tag,
                "expression": safe(lambda: p.Expression),
                "units": units,
                "value": conv_value(safe(lambda: p.Value), units),
                "comment": safe(lambda: p.Comment) or None,
            })
    return out


def dump_feature_parameters(feat):
    """Generic capture of every parameter a feature consumes."""
    out = []
    params = safe(lambda: feat.Parameters)
    if params is None:
        return out
    try:
        for p in params:
            units = safe(lambda: p.Units)
            out.append({
                "name": safe(lambda: p.Name),
                "expression": safe(lambda: p.Expression),
                "value": conv_value(safe(lambda: p.Value), units),
                "units": units,
            })
    except Exception:
        pass
    return out


def parent_feature_names(feat):
    names = []
    pf = safe(lambda: feat.ParentFeatures)
    if pf is not None:
        try:
            names = [safe(lambda f=f: f.Name) for f in pf]
        except Exception:
            pass
    return names


def profile_sketch_name(feat):
    return safe(lambda: feat.Profile.Parent.Name)


def curve_info(sent):
    """Geometry of one sketch entity referenced from a profile."""
    d = {}
    d["s"] = safe(lambda: pt(sent.StartSketchPoint.Geometry))
    d["e"] = safe(lambda: pt(sent.EndSketchPoint.Geometry))
    c = safe(lambda: pt(sent.CenterSketchPoint.Geometry))
    if c is not None:
        d["c"] = c
        d["r_mm"] = safe(lambda: rnd(sent.Radius * CM))
        d["sweep_deg"] = safe(lambda: rnd(math.degrees(sent.SweepAngle)))
    if d.get("s") is None and d.get("c") is not None and d.get("r_mm") is not None:
        d["kind"] = "circle"
    elif d.get("c") is not None:
        d["kind"] = "arc"
    else:
        d["kind"] = "line"
    return {k: v for k, v in d.items() if v is not None}


def dump_profile(feat):
    """Profile of an extrude/revolve: list of paths, each a list of curves."""
    paths = []
    prof = safe(lambda: feat.Profile)
    if prof is None:
        return paths
    try:
        for path in prof:
            p = {
                "closed": safe(lambda: path.Closed),
                "add_material": safe(lambda: path.AddsMaterial),
                "curves": [],
            }
            try:
                for pe in path:
                    se = safe(lambda: pe.SketchEntity)
                    if se is not None:
                        p["curves"].append(curve_info(se))
            except Exception:
                pass
            paths.append(p)
    except Exception:
        pass
    return paths


def revolve_axis_info(rv):
    ax = safe(lambda: rv.AxisEntity)
    if ax is None:
        return None
    name = safe(lambda: ax.Name)
    if name:
        return {"name": name}
    # sketch line as axis
    d = {
        "s": safe(lambda: pt(ax.StartSketchPoint.Geometry)),
        "e": safe(lambda: pt(ax.EndSketchPoint.Geometry)),
    }
    if d["s"] is not None:
        return d
    ln = safe(lambda: ax.Line)
    if ln is not None:
        return {"root_mm": safe(lambda: pt(ln.RootPoint)),
                "direction": safe(lambda: vec(ln.Direction))}
    return None


def dump_extrudes(fs):
    out = []
    for ex in safe(lambda: fs.ExtrudeFeatures) or []:
        d = {
            "name": safe(lambda: ex.Name),
            "suppressed": safe(lambda: ex.Suppressed),
            "operation": safe(lambda: ex.Operation),
            "sketch": profile_sketch_name(ex),
            "extent_type": safe(lambda: ex.ExtentType),
            "params": dump_feature_parameters(ex),
        }
        ext = safe(lambda: ex.Definition.Extent)
        if ext is not None:
            d["distance_mm"] = safe(lambda: conv_value(ext.Distance.Value, "mm"))
            d["distance_expr"] = safe(lambda: ext.Distance.Expression)
            d["direction"] = safe(lambda: ext.Direction)
        d["taper_deg"] = safe(lambda: conv_value(ex.Definition.Extent.TaperAngle.Value, "deg"))
        d["taper_expr"] = safe(lambda: ex.Definition.Extent.TaperAngle.Expression)
        d["extent_two_distance_mm"] = safe(
            lambda: conv_value(ex.Definition.ExtentTwo.Distance.Value, "mm"))
        d["profile_paths"] = dump_profile(ex)
        out.append(d)
    return out


def dump_revolves(fs):
    out = []
    for rv in safe(lambda: fs.RevolveFeatures) or []:
        d = {
            "name": safe(lambda: rv.Name),
            "suppressed": safe(lambda: rv.Suppressed),
            "operation": safe(lambda: rv.Operation),
            "sketch": profile_sketch_name(rv),
            "extent_type": safe(lambda: rv.ExtentType),
            "angle_deg": safe(lambda: conv_value(rv.Definition.Extent.Angle.Value, "deg")),
            "angle_expr": safe(lambda: rv.Definition.Extent.Angle.Expression),
            "axis": revolve_axis_info(rv),
            "params": dump_feature_parameters(rv),
            "profile_paths": dump_profile(rv),
        }
        out.append(d)
    return out


def hole_center_points(h):
    pts = []
    col = safe(lambda: h.HoleCenterPoints)
    if col is None:
        return pts
    try:
        for item in col:
            p = (safe(lambda: item.Geometry3d) or safe(lambda: item.Point)
                 or safe(lambda: item.Geometry))
            pts.append(pt(p))
    except Exception:
        pass
    return pts


def dump_holes(fs):
    out = []
    for h in safe(lambda: fs.HoleFeatures) or []:
        d = {
            "name": safe(lambda: h.Name),
            "suppressed": safe(lambda: h.Suppressed),
            "diameter_mm": safe(lambda: conv_value(h.HoleDiameter.Value, "mm")),
            "diameter_expr": safe(lambda: h.HoleDiameter.Expression),
            "tapped": safe(lambda: h.Tapped),
            "thread": safe(lambda: h.TapInfo.ThreadDesignation),
            "extent_type": safe(lambda: h.ExtentType),
            "centers_mm": hole_center_points(h),
            "cbore_diameter_mm": safe(lambda: conv_value(h.CBoreDiameter.Value, "mm")),
            "cbore_depth_mm": safe(lambda: conv_value(h.CBoreDepth.Value, "mm")),
            "csink_diameter_mm": safe(lambda: conv_value(h.CSinkDiameter.Value, "mm")),
            "csink_angle_deg": safe(lambda: conv_value(h.CSinkAngle.Value, "deg")),
            "params": dump_feature_parameters(h),
        }
        out.append(d)
    return out


def dump_fillets(fs):
    out = []
    for fl in safe(lambda: fs.FilletFeatures) or []:
        d = {
            "name": safe(lambda: fl.Name),
            "suppressed": safe(lambda: fl.Suppressed),
            "edge_sets": [],
            "params": dump_feature_parameters(fl),
        }
        sets = safe(lambda: fl.Definition.EdgeSetItems)
        if sets is not None:
            try:
                for es in sets:
                    d["edge_sets"].append({
                        "radius_mm": safe(lambda: conv_value(es.Radius.Value, "mm")),
                        "radius_expr": safe(lambda: es.Radius.Expression),
                        "edge_count": safe(lambda: es.Edges.Count),
                    })
            except Exception:
                pass
        out.append(d)
    return out


def dump_chamfers(fs):
    out = []
    for ch in safe(lambda: fs.ChamferFeatures) or []:
        out.append({
            "name": safe(lambda: ch.Name),
            "suppressed": safe(lambda: ch.Suppressed),
            "definition_type": safe(lambda: ch.Definition.Type),
            "params": dump_feature_parameters(ch),
        })
    return out


def dump_circular_patterns(fs):
    out = []
    for cp in safe(lambda: fs.CircularPatternFeatures) or []:
        out.append({
            "name": safe(lambda: cp.Name),
            "suppressed": safe(lambda: cp.Suppressed),
            "count": safe(lambda: int(cp.Definition.Count.Value)),
            "count_expr": safe(lambda: cp.Definition.Count.Expression),
            "angle_deg": safe(lambda: conv_value(cp.Definition.Angle.Value, "deg")),
            "angle_expr": safe(lambda: cp.Definition.Angle.Expression),
            "fit_within_angle": safe(lambda: cp.Definition.FitWithinAngle),
            "axis_name": safe(lambda: cp.Definition.RotationAxis.Name),
            "parents": parent_feature_names(cp),
        })
    return out


def dump_rect_patterns(fs):
    out = []
    for rp in safe(lambda: fs.RectangularPatternFeatures) or []:
        out.append({
            "name": safe(lambda: rp.Name),
            "suppressed": safe(lambda: rp.Suppressed),
            "count_x": safe(lambda: int(rp.Definition.XCount.Value)),
            "spacing_x_mm": safe(lambda: conv_value(rp.Definition.XSpacing.Value, "mm")),
            "count_y": safe(lambda: int(rp.Definition.YCount.Value)),
            "spacing_y_mm": safe(lambda: conv_value(rp.Definition.YSpacing.Value, "mm")),
            "parents": parent_feature_names(rp),
        })
    return out


def dump_mirrors(fs):
    out = []
    for mf in safe(lambda: fs.MirrorFeatures) or []:
        out.append({
            "name": safe(lambda: mf.Name),
            "suppressed": safe(lambda: mf.Suppressed),
            "plane": safe(lambda: mf.Definition.MirrorPlaneEntity.Name),
            "parents": parent_feature_names(mf),
        })
    return out


def dump_threads(fs):
    out = []
    for th in safe(lambda: fs.ThreadFeatures) or []:
        out.append({
            "name": safe(lambda: th.Name),
            "suppressed": safe(lambda: th.Suppressed),
            "designation": safe(lambda: th.ThreadInfo.ThreadDesignation),
            "internal": safe(lambda: th.ThreadInfo.Internal),
            "full_depth": safe(lambda: th.FullDepth),
        })
    return out


def dump_generic_feature_order(cd):
    out = []
    feats = safe(lambda: cd.Features)
    if feats is None:
        return out
    try:
        for f in feats:
            out.append({
                "name": safe(lambda: f.Name),
                "type": safe(lambda: f.Type),
                "suppressed": safe(lambda: f.Suppressed),
                "params": dump_feature_parameters(f),
            })
    except Exception:
        pass
    return out


def dump_work_features(cd):
    planes, axes, points = [], [], []
    for wp in safe(lambda: cd.WorkPlanes) or []:
        planes.append({
            "name": safe(lambda: wp.Name),
            "root_point_mm": safe(lambda: pt(wp.Plane.RootPoint)),
            "normal": safe(lambda: vec(wp.Plane.Normal)),
        })
    for wa in safe(lambda: cd.WorkAxes) or []:
        axes.append({
            "name": safe(lambda: wa.Name),
            "root_point_mm": safe(lambda: pt(wa.Line.RootPoint)),
            "direction": safe(lambda: vec(wa.Line.Direction)),
        })
    for wpt in safe(lambda: cd.WorkPoints) or []:
        points.append({
            "name": safe(lambda: wpt.Name),
            "point_mm": safe(lambda: pt(wpt.Point)),
        })
    return {"planes": planes, "axes": axes, "points": points}


def sketch_frame(sk, tg):
    """Model-space origin / x / y direction of a planar sketch (mm)."""
    try:
        o = sk.SketchToModelSpace(tg.CreatePoint2d(0.0, 0.0))
        px = sk.SketchToModelSpace(tg.CreatePoint2d(1.0, 0.0))
        py = sk.SketchToModelSpace(tg.CreatePoint2d(0.0, 1.0))
        origin = pt(o)
        xd = [rnd(px.X - o.X, 9), rnd(px.Y - o.Y, 9), rnd(px.Z - o.Z, 9)]
        yd = [rnd(py.X - o.X, 9), rnd(py.Y - o.Y, 9), rnd(py.Z - o.Z, 9)]
        return origin, xd, yd
    except Exception:
        return None, None, None


def dump_sketch(sk, tg):
    origin, xdir, ydir = sketch_frame(sk, tg)
    d = {
        "name": safe(lambda: sk.Name),
        "plane_entity": safe(lambda: sk.PlanarEntity.Name) or "face-or-unnamed",
        "origin_mm": origin,
        "x_dir": xdir,
        "y_dir": ydir,
        "profile_count": safe(lambda: sk.Profiles.Count),
        "lines": [],
        "circles": [],
        "arcs": [],
        "ellipses": [],
        "splines": [],
        "points": [],
        "text_boxes": [],
        "dimensions": [],
    }
    for ln in safe(lambda: sk.SketchLines) or []:
        d["lines"].append({
            "s": safe(lambda: pt(ln.StartSketchPoint.Geometry)),
            "e": safe(lambda: pt(ln.EndSketchPoint.Geometry)),
            "construction": safe(lambda: ln.Construction),
        })
    for c in safe(lambda: sk.SketchCircles) or []:
        d["circles"].append({
            "c": safe(lambda: pt(c.CenterSketchPoint.Geometry)),
            "r_mm": safe(lambda: rnd(c.Radius * CM)),
            "construction": safe(lambda: c.Construction),
        })
    for a in safe(lambda: sk.SketchArcs) or []:
        d["arcs"].append({
            "c": safe(lambda: pt(a.CenterSketchPoint.Geometry)),
            "r_mm": safe(lambda: rnd(a.Radius * CM)),
            "s": safe(lambda: pt(a.StartSketchPoint.Geometry)),
            "e": safe(lambda: pt(a.EndSketchPoint.Geometry)),
            "sweep_deg": safe(lambda: rnd(math.degrees(a.SweepAngle))),
            "construction": safe(lambda: a.Construction),
        })
    for el in safe(lambda: sk.SketchEllipses) or []:
        d["ellipses"].append({
            "c": safe(lambda: pt(el.CenterSketchPoint.Geometry)),
            "major_mm": safe(lambda: rnd(el.MajorRadius * CM)),
            "minor_mm": safe(lambda: rnd(el.MinorRadius * CM)),
        })
    for sp in safe(lambda: sk.SketchSplines) or []:
        fit = []
        try:
            for fp in sp.FitPoints:
                fit.append(pt(fp.Geometry))
                if len(fit) >= MAX_SPLINE_FITPOINTS:
                    break
        except Exception:
            pass
        d["splines"].append({"fit_points": fit})
    n_pts = 0
    for p in safe(lambda: sk.SketchPoints) or []:
        if n_pts >= MAX_SKETCH_POINTS:
            d["points_truncated"] = True
            break
        g = safe(lambda: pt(p.Geometry))
        if g is not None:
            d["points"].append(g)
            n_pts += 1
    for tb in safe(lambda: sk.TextBoxes) or []:
        d["text_boxes"].append({
            "text": safe(lambda: tb.Text),
            "origin": safe(lambda: pt(tb.Origin)),
        })
    for dim in safe(lambda: sk.DimensionConstraints) or []:
        prm = safe(lambda: dim.Parameter)
        units = safe(lambda: prm.Units) if prm is not None else None
        d["dimensions"].append({
            "param": safe(lambda: prm.Name) if prm is not None else None,
            "expression": safe(lambda: prm.Expression) if prm is not None else None,
            "value": conv_value(safe(lambda: prm.Value), units) if prm is not None else None,
            "units": units,
            "driven": safe(lambda: dim.Driven),
        })
    return d


def classify_surface(info):
    if info.get("half_angle_deg") is not None:
        return "cone"
    if info.get("radius_mm") is not None and info.get("axis") is not None:
        return "cylinder"
    if info.get("normal") is not None:
        return "plane"
    if info.get("major_radius_mm") is not None:
        return "torus"
    if info.get("radius_mm") is not None:
        return "sphere"
    return "other"


def dump_face(face):
    info = {"area_mm2": safe(lambda: rnd(face.Evaluator.Area * CM * CM))}
    g = safe(lambda: face.Geometry)
    if g is not None:
        r = safe(lambda: g.Radius)
        if r is not None:
            info["radius_mm"] = rnd(r * CM)
        ha = safe(lambda: g.HalfAngle)
        if ha is not None:
            info["half_angle_deg"] = rnd(math.degrees(ha))
        info["major_radius_mm"] = safe(lambda: rnd(g.MajorRadius * CM))
        info["minor_radius_mm"] = safe(lambda: rnd(g.MinorRadius * CM))
        rp = safe(lambda: g.RootPoint)
        if rp is not None:
            info["root_point_mm"] = pt(rp)
        bp = safe(lambda: g.BasePoint)
        if bp is not None:
            info["base_point_mm"] = pt(bp)
        n = safe(lambda: g.Normal)
        if n is not None:
            info["normal"] = vec(n)
        ax = safe(lambda: g.AxisVector)
        if ax is not None:
            info["axis"] = vec(ax)
    info = {k: v for k, v in info.items() if v is not None}
    info["surface"] = classify_surface(info)
    return info


def dump_bodies(cd):
    out = []
    for body in safe(lambda: cd.SurfaceBodies) or []:
        b = {
            "name": safe(lambda: body.Name),
            "face_count": safe(lambda: body.Faces.Count),
            "edge_count": safe(lambda: body.Edges.Count),
            "vertex_count": safe(lambda: body.Vertices.Count),
        }
        rb = safe(lambda: body.RangeBox)
        if rb is not None:
            b["bbox_min_mm"] = pt(rb.MinPoint)
            b["bbox_max_mm"] = pt(rb.MaxPoint)
        faces = []
        try:
            for face in body.Faces:
                faces.append(dump_face(face))
                if len(faces) >= MAX_FACES:
                    b["faces_truncated"] = True
                    break
        except Exception:
            pass
        # Largest faces first: those carry the outer shape.
        faces.sort(key=lambda f: -(f.get("area_mm2") or 0.0))
        b["faces"] = faces
        verts = []
        try:
            for v in body.Vertices:
                verts.append(pt(v.Point))
                if len(verts) >= MAX_VERTICES:
                    b["vertices_truncated"] = True
                    break
        except Exception:
            pass
        b["vertices_mm"] = verts
        out.append(b)
    return out


def dump_iproperties(doc):
    out = {}
    try:
        ps = doc.PropertySets.Item("Design Tracking Properties")
        for key in ("Part Number", "Description", "Project"):
            out[key.lower().replace(" ", "_")] = safe(lambda k=key: ps.Item(k).Value)
    except Exception:
        pass
    return out


def probe_document(app, path: Path, out_dir: Path, export_step: bool):
    tg = app.TransientGeometry
    # Reuse an already-open document (do not disturb the user's session).
    doc = None
    was_open = False
    for d in app.Documents:
        if safe(lambda: d.FullFileName, "").lower() == str(path).lower():
            doc = d
            was_open = True
            break
    if doc is None:
        print(f"  opening {path.name} ...", flush=True)
        doc = app.Documents.Open(str(path), False)  # invisible
    else:
        print(f"  already open: {path.name}", flush=True)

    try:
        cd = doc.ComponentDefinition
        fs = cd.Features
        data = {
            "file": str(path),
            "iproperties": dump_iproperties(doc),
            "parameters": dump_parameters(cd),
            "work_features": dump_work_features(cd),
            "feature_order": dump_generic_feature_order(cd),
            "features": {
                "extrudes": dump_extrudes(fs),
                "revolves": dump_revolves(fs),
                "holes": dump_holes(fs),
                "fillets": dump_fillets(fs),
                "chamfers": dump_chamfers(fs),
                "circular_patterns": dump_circular_patterns(fs),
                "rectangular_patterns": dump_rect_patterns(fs),
                "mirrors": dump_mirrors(fs),
                "threads": dump_threads(fs),
            },
            "sketches": [],
            "bodies": [],
        }
        mp = safe(lambda: cd.MassProperties)
        if mp is not None:
            data["mass_properties"] = {
                "volume_mm3": safe(lambda: rnd(mp.Volume * 1000.0)),
                "area_mm2": safe(lambda: rnd(mp.Area * 100.0)),
                "centroid_mm": safe(lambda: pt(mp.CenterOfMass)),
            }
        print("    parameters/features done, dumping sketches ...", flush=True)
        for sk in safe(lambda: cd.Sketches) or []:
            data["sketches"].append(dump_sketch(sk, tg))
        print("    sketches done, dumping bodies ...", flush=True)
        data["bodies"] = dump_bodies(cd)

        stem = path.stem.replace(" ", "_")
        json_path = out_dir / f"{stem}.json"
        json_path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        print(f"    wrote {json_path}", flush=True)

        if export_step:
            stp_path = out_dir / f"{stem}.step"
            try:
                doc.SaveAs(str(stp_path), True)  # SaveCopyAs
                print(f"    wrote {stp_path}", flush=True)
            except Exception as exc:
                print(f"    STEP export FAILED: {exc}", flush=True)
    finally:
        if not was_open:
            safe(lambda: doc.Close(True))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("parts", nargs="+", type=Path)
    ap.add_argument("--out-dir", type=Path, default=Path("extracted"))
    ap.add_argument("--step", action="store_true", help="also export a STEP copy")
    ap.add_argument("--max-faces", type=int, default=None)
    ap.add_argument("--max-vertices", type=int, default=None)
    args = ap.parse_args()

    global MAX_FACES, MAX_VERTICES
    if args.max_faces:
        MAX_FACES = args.max_faces
    if args.max_vertices:
        MAX_VERTICES = args.max_vertices

    args.out_dir.mkdir(parents=True, exist_ok=True)

    print("Connecting to Autodesk Inventor ...", flush=True)
    app = connect_inventor()
    safe(lambda: setattr(app, "SilentOperation", True))
    try:
        for p in args.parts:
            p = p.resolve()
            if not p.exists():
                print(f"  MISSING: {p}")
                continue
            print(f"Probing {p.name}", flush=True)
            try:
                probe_document(app, p, args.out_dir, args.step)
            except Exception:
                traceback.print_exc()
    finally:
        safe(lambda: setattr(app, "SilentOperation", False))


if __name__ == "__main__":
    main()
