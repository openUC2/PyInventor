"""Small shaded CAD pictures of Inventor parts, rendered in numpy (no Inventor window needed).

Meshes come from Inventor Apprentice (``SurfaceBody.CalculateFacets`` on the file),
so this runs beside a busy Inventor without touching its session or project.
The picture is an iso view from front-left-top with Z up, like the manuals:
smooth shading in the part's appearance colour and dark outlines at
silhouettes and creases, transparent background.

    from part_render import Apprentice, part_meshes, render
    app = Apprentice()
    meshes = part_meshes(app, r"...\\PRT - 1003 - CUBHLF111 - V04.ipt")
    rgba = render(meshes, size=480)          # (480, 480, 4) uint8
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

APPRENTICE_CLSID = "{C343ED84-A129-11D3-B799-0060B0F159EF}"
kAssemblyDocumentObject = 12291
VIEW_FROM = np.array([-1.0, -1.0, 1.0])
_MODEL_STATE_RE = re.compile(r"^(?P<path>.*?)<(?P<state>[^<>]*)>$")


def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


@dataclass
class Mesh:
    vertices: np.ndarray   # (n, 3) mm
    normals: np.ndarray    # (n, 3) unit, per vertex
    faces: np.ndarray      # (m, 3)
    color: tuple           # rgb 0..1
    opacity: float = 1.0


# ---------------------------------------------------------------------------
# Reading meshes with Apprentice
# ---------------------------------------------------------------------------

def Apprentice():
    """Inventor's read-only file server (its ProgID is not registered for 64-bit Python)."""
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    return win32com.client.Dispatch(APPRENTICE_CLSID)


GREY = ((0.72, 0.72, 0.72), 1.0)


def _style_color(style) -> tuple[tuple, float]:
    """Diffuse colour and opacity of a render style (Apprentice has no appearance assets)."""
    rgb = safe(lambda: style.GetDiffuseColor())
    if not rgb or len(rgb) < 3:
        return GREY
    opacity = safe(lambda: float(style.Opacity), 1.0) or 1.0
    return (rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0), float(np.clip(opacity, 0.25, 1.0))


def _doc_color(doc) -> tuple[tuple, float]:
    return _style_color(safe(lambda: doc.ActiveRenderStyle)) if doc is not None else GREY


def _facets(body):
    """(coords, normals, indices) of a body, None if it has none. Apprentice sometimes returns an
    empty set at the tolerance just used for another part (seen after an ISO O-ring), so retry coarser."""
    for tol in (0.01, 0.02, 0.05):   # cm
        try:
            _vc, _fc, coords, normals, idx = body.CalculateFacets(tol)
        except Exception:
            continue
        if isinstance(coords, (tuple, list)) and len(coords) >= 9 and isinstance(idx, (tuple, list)) and len(idx) >= 3:
            return coords, normals, idx
    return None


def _body_meshes(bodies, color=GREY) -> list[Mesh]:
    out = []
    for i in range(1, safe(lambda: bodies.Count, 0) + 1):
        body = bodies.Item(i)
        if safe(lambda: body.Visible) is False:
            continue
        facets = _facets(body)
        if facets is None:
            continue  # empty body (a sketch-only or failed solid)
        coords, normals, idx = facets
        v = np.array(coords, float).reshape(-1, 3) * 10.0
        n = np.array(normals, float).reshape(-1, 3) if isinstance(normals, (tuple, list)) else np.zeros((0, 3))
        f = np.array(idx, np.int64).reshape(-1, 3) - 1
        out.append(Mesh(v, n, f, color[0], color[1]))
    return out


def _occurrence_meshes(occs, depth: int = 0) -> list[Mesh]:
    out = []
    for i in range(1, safe(lambda: occs.Count, 0) + 1):
        occ = occs.Item(i)
        if safe(lambda: occ.Suppressed) or safe(lambda: occ.Visible) is False:
            continue
        if safe(lambda: occ.DefinitionDocumentType) == kAssemblyDocumentObject:
            if depth < 8:
                out.extend(_occurrence_meshes(occ.SubOccurrences, depth + 1))
            continue
        color = _doc_color(safe(lambda: occ.ReferencedDocumentDescriptor.ReferencedDocument))
        out.extend(_body_meshes(safe(lambda: occ.SurfaceBodies), color))
    return out


def part_meshes(app, full_document_name: str) -> list[Mesh]:
    """Meshes of a part or assembly file (``path`` or ``path<model state>``), in mm."""
    m = _MODEL_STATE_RE.match(full_document_name)
    candidates = [full_document_name] + ([m.group("path")] if m else [])
    doc = None
    for name in candidates:
        doc = safe(lambda: app.Open(name))
        if doc is not None:
            break
    if doc is None:
        return []
    try:
        cd = doc.ComponentDefinition
        if safe(lambda: doc.DocumentType) == kAssemblyDocumentObject:
            return _occurrence_meshes(cd.Occurrences)
        return _body_meshes(cd.SurfaceBodies, _doc_color(doc))
    finally:
        safe(lambda: doc.Close())


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

#: Iso corners from above, Z up; the first is the manuals' view.
VIEW_CANDIDATES = (VIEW_FROM, np.array([1.0, -1.0, 1.0]), np.array([-1.0, 1.0, 1.0]), np.array([1.0, 1.0, 1.0]))


def best_view(meshes: list[Mesh], keep: float = 0.8) -> np.ndarray:
    """The iso corner that shows the part largest (a plate seen edge-on is useless);
    the usual one unless another shows clearly more."""
    from scipy.spatial import ConvexHull
    v = np.vstack([m.vertices for m in meshes])
    if len(v) > 6000:
        v = v[:: len(v) // 6000 + 1]
    areas = []
    for cand in VIEW_CANDIDATES:
        right, up, _ = _basis(cand)
        try:
            areas.append(ConvexHull(np.stack([v @ right, v @ up], axis=1)).volume)
        except Exception:
            areas.append(0.0)
    if areas[0] >= keep * max(areas):
        return VIEW_CANDIDATES[0]
    return VIEW_CANDIDATES[int(np.argmax(areas))]


def _basis(view_from: np.ndarray):
    eye = view_from / np.linalg.norm(view_from)
    look = -eye
    up = np.array([0.0, 0.0, 1.0]) - look * look[2]
    up /= np.linalg.norm(up)
    right = np.cross(look, up)
    return right, up, eye


def _subdivide(p, z, n, c, limit):
    """Split triangles (T, 3, ...) until every edge is shorter than *limit* pixels."""
    out = [[], [], [], []]
    for _ in range(14):
        e = np.max(np.stack([np.linalg.norm(p[:, 1] - p[:, 0], axis=1), np.linalg.norm(p[:, 2] - p[:, 1], axis=1),
                             np.linalg.norm(p[:, 0] - p[:, 2], axis=1)]), axis=0)
        small = e <= limit
        for acc, arr in zip(out, (p, z, n, c)):
            acc.append(arr[small])
        if small.all():
            break
        p, z, n, c = p[~small], z[~small], n[~small], c[~small]

        def mid(a):
            m01, m12, m20 = (a[:, 0] + a[:, 1]) / 2, (a[:, 1] + a[:, 2]) / 2, (a[:, 2] + a[:, 0]) / 2
            return np.concatenate([np.stack([a[:, 0], m01, m20], 1), np.stack([m01, a[:, 1], m12], 1),
                                   np.stack([m20, m12, a[:, 2]], 1), np.stack([m01, m12, m20], 1)])

        p, z, n, c = mid(p), mid(z), mid(n), mid(c)
    else:
        for acc, arr in zip(out, (p, z, n, c)):
            acc.append(arr)
    return [np.concatenate(a) for a in out]


def render(meshes: list[Mesh], size: int = 480, view_from: np.ndarray | None = VIEW_FROM, supersample: int = 2,
           margin: float = 0.06, outline=(0.16, 0.16, 0.18)) -> np.ndarray:
    """RGBA image (size x size, uint8) of the meshes, shaded, outlined, transparent background.

    *view_from* None picks the iso corner that shows the part best (``best_view``).
    """
    W = size * supersample
    img = np.zeros((size, size, 4), np.uint8)
    if not meshes:
        return img
    if view_from is None:
        view_from = best_view(meshes)
    right, up, eye = _basis(view_from)
    allv = np.vstack([m.vertices for m in meshes])
    xy = np.stack([allv @ right, allv @ up], axis=1)
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    span = float(max(hi[0] - lo[0], hi[1] - lo[1], 1e-6))
    scale = W * (1 - 2 * margin) / span
    offset = np.array([W, W]) / 2 - (lo + hi) / 2 * scale

    P, Z, N, C = [], [], [], []
    for m in meshes:
        f = m.faces
        if len(f) == 0:
            continue
        v = m.vertices[f]                       # (T, 3, 3)
        nv = m.normals[f] if len(m.normals) == len(m.vertices) else np.repeat(
            np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])[:, None, :], 3, axis=1)
        nv = nv / (np.linalg.norm(nv, axis=2, keepdims=True) + 1e-12)
        front = nv.mean(axis=1) @ eye > -0.15   # back faces cannot win the depth test anyway
        v, nv = v[front], nv[front]
        p = np.stack([v @ right, v @ up], axis=2) * scale + offset
        p[..., 1] = W - p[..., 1]               # image rows grow downwards
        P.append(p)
        Z.append(v @ eye)
        N.append(nv)
        rgba = np.array(list(m.color) + [m.opacity])
        C.append(np.broadcast_to(rgba, (len(v), 3, 4)).copy())
    if not P:
        return img
    p, z, n, c = _subdivide(np.concatenate(P), np.concatenate(Z), np.concatenate(N), np.concatenate(C), 3.0)

    # Rasterise every (small) triangle over a 4x4 pixel stamp with edge functions.
    k = 4
    base = np.floor(p.min(axis=1)).astype(np.int64)            # (T, 2)
    gx, gy = np.meshgrid(np.arange(k), np.arange(k))
    off = np.stack([gx.ravel(), gy.ravel()], axis=1)           # (k*k, 2)
    pix = base[:, None, :] + off[None, :, :]                    # (T, k*k, 2)
    q = pix + 0.5
    a, b, cc = p[:, 0][:, None, :], p[:, 1][:, None, :], p[:, 2][:, None, :]

    def edge(u, w, r):
        return (w[..., 0] - u[..., 0]) * (r[..., 1] - u[..., 1]) - (w[..., 1] - u[..., 1]) * (r[..., 0] - u[..., 0])

    area = edge(a, b, cc)
    area = np.where(np.abs(area) < 1e-12, 1e-12, area)
    w0 = edge(b, cc, q) / area
    w1 = edge(cc, a, q) / area
    w2 = 1.0 - w0 - w1
    eps = -1e-4
    inside = (w0 >= eps) & (w1 >= eps) & (w2 >= eps)
    inside &= (pix[..., 0] >= 0) & (pix[..., 0] < W) & (pix[..., 1] >= 0) & (pix[..., 1] < W)
    t_idx, s_idx = np.nonzero(inside)
    if len(t_idx) == 0:
        return img
    ww = np.stack([w0[t_idx, s_idx], w1[t_idx, s_idx], w2[t_idx, s_idx]], axis=1)    # (F, 3)
    depth = np.einsum("fi,fi->f", ww, z[t_idx])
    normal = np.einsum("fi,fij->fj", ww, n[t_idx])
    color = np.einsum("fi,fij->fj", ww, c[t_idx])
    flat = pix[t_idx, s_idx, 1] * W + pix[t_idx, s_idx, 0]

    # Z-buffer: nearest fragment per pixel (largest depth towards the eye).
    order = np.lexsort((-depth, flat))
    flat, depth, normal, color = flat[order], depth[order], normal[order], color[order]
    first = np.r_[True, flat[1:] != flat[:-1]]
    flat, depth, normal, color = flat[first], depth[first], normal[first], color[first]

    D = np.full(W * W, -np.inf)
    D[flat] = depth
    Nb = np.zeros((W * W, 3))
    Nb[flat] = normal / (np.linalg.norm(normal, axis=1, keepdims=True) + 1e-12)
    rgb = np.ones((W * W, 3))
    alpha = np.zeros(W * W)

    # Light from the upper left, slightly towards the viewer; soft ambient.
    light = -0.45 * right + 0.65 * up + 0.6 * eye
    light /= np.linalg.norm(light)
    half = light + eye
    half /= np.linalg.norm(half)
    nn = Nb[flat]
    nn = np.where((nn @ eye)[:, None] < 0, -nn, nn)            # two-sided
    diff = np.clip(nn @ light, 0, 1)
    spec = np.clip(nn @ half, 0, 1) ** 28
    shade = 0.42 + 0.58 * diff
    base_rgb = 0.2 + 0.8 * color[:, :3]                         # black parts keep visible shading
    op = color[:, 3]
    lit = np.clip(base_rgb * shade[:, None] + 0.18 * spec[:, None], 0, 1)
    lit = lit * op[:, None] + (1 - op[:, None]) * 0.92        # see-through parts read lighter
    rgb[flat] = lit
    alpha[flat] = 1.0

    D = D.reshape(W, W)
    Nb = Nb.reshape(W, W, 3)
    fg = np.isfinite(D)
    # Outlines: silhouette, depth steps and creases between neighbouring pixels.
    step = 0.012 * span                                         # mm
    cos_crease = np.cos(np.radians(38))
    edges = np.zeros((W, W), bool)
    for dy, dx in ((0, 1), (1, 0)):
        a_fg, b_fg = fg[: W - dy, : W - dx], fg[dy:, dx:]
        a_d, b_d = D[: W - dy, : W - dx], D[dy:, dx:]
        a_n, b_n = Nb[: W - dy, : W - dx], Nb[dy:, dx:]
        sil = a_fg != b_fg
        both = a_fg & b_fg
        diff_d = np.where(both, np.where(both, a_d, 0.0) - np.where(both, b_d, 0.0), 0.0)
        jump = both & (np.abs(diff_d) > step)
        crease = both & (np.einsum("ijk,ijk->ij", a_n, b_n) < cos_crease)
        e = sil | jump | crease
        edges[: W - dy, : W - dx] |= e
        edges[dy:, dx:] |= e & (jump | crease)
    rgb = rgb.reshape(W, W, 3)
    alpha = alpha.reshape(W, W)
    rgb[edges] = outline
    alpha[edges] = 1.0

    # Downsample (box filter) for anti-aliasing; premultiply so the rim blends cleanly.
    s = supersample
    pre = rgb * alpha[..., None]
    pre = pre.reshape(size, s, size, s, 3).mean(axis=(1, 3))
    a_out = alpha.reshape(size, s, size, s).mean(axis=(1, 3))
    col = np.where(a_out[..., None] > 1e-6, pre / np.maximum(a_out[..., None], 1e-6), 1.0)
    img[..., :3] = np.clip(col * 255, 0, 255).astype(np.uint8)
    img[..., 3] = np.clip(a_out * 255, 0, 255).astype(np.uint8)
    return img
