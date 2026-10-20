"""Plan an exploded view and an assembly sequence from part meshes (no Inventor needed).

The planner works on *groups* (an assembly level: the module, a ``SUB - ...``
pre-assembly) whose *members* are rigid bodies (a part, a bought assembly, or a
child group moved as one). For every group it

1. measures which member blocks which along +-X, +-Y, +-Z (and along the
   normal of any plate that sits at an angle, such as a mirror on a 45 degree
   seat), from depth maps of the meshes (per pixel of the plane across the
   axis: nearest and farthest surface of each member),
2. takes members off one round at a time, around a fixed *base* member (the
   grounded / biggest one): a member leaves in a round when nothing still
   present blocks it along one of the six directions. Reversed, the rounds are
   the assembly steps; the direction is the one the part goes in with,
3. explodes: in assembly order every member moves along its direction until
   its box clears the boxes of everything placed before it, plus a gap.

Child groups are planned first; a parent clears their *exploded* extent, so
the explosions of all levels add up without collisions along the motion.
Everything is in millimetres in the module's coordinate frame.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

DIRECTIONS = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]], dtype=float)
DIRECTION_NAMES = ("+X", "-X", "+Y", "-Y", "+Z", "-Z")


def direction_index(axis: int, sign: int) -> int:
    return 2 * axis + (0 if sign > 0 else 1)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class Body:
    """A rigid thing to move: one part or a bought assembly."""
    key: str
    label: str
    vertices: np.ndarray            # (n, 3) mm, assembled position
    faces: np.ndarray               # (m, 3) indices into vertices
    grounded: bool = False
    info: dict = field(default_factory=dict)

    @property
    def bbox(self) -> np.ndarray:
        return np.array([self.vertices.min(axis=0), self.vertices.max(axis=0)])


@dataclass
class Group:
    """An assembly level whose members are assembled in steps."""
    key: str
    label: str
    members: list  # of Body | Group
    grounded: bool = False
    info: dict = field(default_factory=dict)

    def bodies(self) -> list[Body]:
        out: list[Body] = []
        for m in self.members:
            out.extend(m.bodies() if isinstance(m, Group) else [m])
        return out

    @property
    def bbox(self) -> np.ndarray:
        boxes = [b.bbox for b in self.bodies()]
        return np.array([np.min([b[0] for b in boxes], axis=0), np.max([b[1] for b in boxes], axis=0)])


@dataclass
class Placement:
    """How one member of a group goes in."""
    key: str
    direction: int          # index into DIRECTIONS; -1 for the base
    round: int              # assembly round (0 = base)
    forced: bool = False    # no free direction was found; least-blocked one used
    blocked_by: list = field(default_factory=list)  # members it rests against (blocks it opposite to direction)


@dataclass
class GroupPlan:
    group: Group
    base: str
    placements: list[Placement]          # assembly order (base first)
    offsets: dict[str, np.ndarray]       # member key -> displacement in the full explosion
    exploded_bbox: np.ndarray            # bbox of the group with its own and its children's explosions
    directions: np.ndarray = field(default_factory=lambda: DIRECTIONS.copy())  # what Placement.direction indexes

    def placement(self, key: str) -> Placement:
        return next(p for p in self.placements if p.key == key)

    def direction_name(self, index: int) -> str:
        return "base" if index < 0 else direction_label(self.directions[index])


@dataclass
class Step:
    """One page of the instructions: members of *group* added in one go."""
    group: Group
    number: int
    new: list[Placement]
    present: list[str]                   # members already in place (keys), base included
    offsets: dict[str, np.ndarray]       # displacement of the new members for this step's picture
    quantity: int = 1                    # identical copies of the group to build (3x the same screw set)


@dataclass
class Plan:
    root: Group
    groups: dict[str, GroupPlan]
    steps: list[Step]
    displacement: dict[str, np.ndarray]  # body key -> total displacement in the full explosion

    def body_displacement(self, key: str) -> np.ndarray:
        return self.displacement.get(key, np.zeros(3))


# ---------------------------------------------------------------------------
# Depth maps
# ---------------------------------------------------------------------------

def sample_surface(vertices: np.ndarray, faces: np.ndarray, step: float, max_points: int = 3_000_000) -> np.ndarray:
    """Points on the triangles, no further apart than *step* (plus the vertices)."""
    if len(faces) == 0:
        return vertices.astype(np.float32)
    a, b, c = vertices[faces[:, 0]], vertices[faces[:, 1]], vertices[faces[:, 2]]
    longest = np.max([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)], axis=0)
    n = np.clip(np.ceil(longest / step).astype(int), 1, 400)
    # Coarsen if the sampling would explode (huge flat faces at a fine pixel).
    total = int(np.sum((n + 1) * (n + 2) // 2))
    if total > max_points:
        n = np.maximum(1, (n * np.sqrt(max_points / total)).astype(int))
    chunks = [vertices.astype(np.float32)]
    for k in np.unique(n):
        sel = n == k
        i, j = np.meshgrid(np.arange(k + 1), np.arange(k + 1), indexing="ij")
        keep = (i + j) <= k
        u = (i[keep] / k).astype(np.float32)
        v = (j[keep] / k).astype(np.float32)
        w = 1.0 - u - v
        pts = (a[sel][:, None, :] * w[None, :, None] + b[sel][:, None, :] * u[None, :, None]
               + c[sel][:, None, :] * v[None, :, None])
        chunks.append(pts.reshape(-1, 3).astype(np.float32))
    return np.vstack(chunks)


@dataclass
class _Map:
    """Footprint of one body seen along one axis: pixel window + near/far depth."""
    i0: int
    j0: int
    lo: np.ndarray  # (ni, nj) min depth, +inf where empty
    hi: np.ndarray  # (ni, nj) max depth, -inf where empty
    mask: np.ndarray  # eroded footprint


def axis_frame(axis: np.ndarray) -> np.ndarray:
    """Rows u, v, w: an orthonormal frame whose w is *axis* (world axes map to themselves, permuted)."""
    w = axis / np.linalg.norm(axis)
    k = int(np.argmax(np.abs(w)))
    if abs(w[k]) > 1 - 1e-9:  # a world axis: keep the other two world axes, in order
        u, v = [np.eye(3)[a] for a in range(3) if a != k]
        return np.array([u, v, w])
    helper = np.eye(3)[int(np.argmin(np.abs(w)))]
    u = np.cross(helper, w)
    u /= np.linalg.norm(u)
    return np.array([u, np.cross(w, u), w])


class DepthMaps:
    """Per body and axis, the nearest and farthest surface over a pixel grid.

    The axes are X, Y, Z plus any extra unit vectors (the normal of a mirror
    on a 45 degree seat). *erode_mm* trims every footprint's rim: walls that
    touch side by side (an insert in the grooves of the cube posts) or differ
    only by tessellation must not read as one sitting in front of the other.
    """

    def __init__(self, items: dict[str, list[tuple[np.ndarray, np.ndarray]]], resolution: float | None = None,
                 erode_mm: float = 0.35, axes: np.ndarray | None = None):
        self.axes = np.eye(3) if axes is None else np.asarray(axes, float)
        self.frames = [axis_frame(a) for a in self.axes]
        allv = np.vstack([v for meshes in items.values() for v, _ in meshes])
        lo, hi = allv.min(axis=0), allv.max(axis=0)
        if resolution is None:
            resolution = float(np.clip(np.max(hi - lo) / 200.0, 0.15, 0.8))
        self.res = resolution
        # Grid origin per axis frame: below everything, in that frame's (u, v).
        self.origins = [(allv @ fr[:2].T).min(axis=0) - 2 * resolution for fr in self.frames]
        self.maps: dict[tuple[str, int], _Map] = {}
        from scipy import ndimage  # local: keep import cost out of plain imports
        structure = np.ones((3, 3), bool)
        erode = max(1, int(round(erode_mm / resolution)))
        for key, meshes in items.items():
            pts = np.vstack([sample_surface(v, f, resolution * 0.9) for v, f in meshes])
            for axis, (frame, origin) in enumerate(zip(self.frames, self.origins)):
                local = pts @ frame.T
                iu = np.floor((local[:, 0] - origin[0]) / resolution).astype(np.int64)
                iv = np.floor((local[:, 1] - origin[1]) / resolution).astype(np.int64)
                depth = local[:, 2]
                i0, j0 = int(iu.min()), int(iv.min())
                ni, nj = int(iu.max()) - i0 + 1, int(iv.max()) - j0 + 1
                flat = (iu - i0) * nj + (iv - j0)
                near = np.full(ni * nj, np.inf, np.float32)
                far = np.full(ni * nj, -np.inf, np.float32)
                order = np.argsort(flat, kind="stable")
                fs, ds = flat[order], depth[order]
                starts = np.flatnonzero(np.r_[True, fs[1:] != fs[:-1]])
                near[fs[starts]] = np.minimum.reduceat(ds, starts)
                far[fs[starts]] = np.maximum.reduceat(ds, starts)
                near, far = near.reshape(ni, nj), far.reshape(ni, nj)
                mask = np.isfinite(near)
                # Close pin-holes left by sparse sampling, then drop the rim so
                # bodies that merely touch side by side do not count as overlapping.
                mask = ndimage.binary_closing(mask, structure, iterations=1, border_value=0) | mask
                # Thin bodies seen edge-on (a washer from the side) would vanish
                # entirely; erode them less.
                full = int(mask.sum())
                for e in range(erode, 0, -1):
                    eroded = ndimage.binary_erosion(mask, structure, iterations=e, border_value=0)
                    if eroded.sum() >= 0.25 * full:
                        mask = eroded
                        break
                # Closed pixels have no depth; give them their neighbours'.
                if np.any(mask & ~np.isfinite(near)):
                    near = np.where(np.isfinite(near), near, ndimage.grey_erosion(np.where(np.isfinite(near), near, np.inf), size=3))
                    far = np.where(np.isfinite(far), far, ndimage.grey_dilation(np.where(np.isfinite(far), far, -np.inf), size=3))
                self.maps[(key, axis)] = _Map(i0, j0, near, far, mask)

    def blocking(self, mover: str, other: str, axis: int, tol: float, interference: float,
                 ahead_only: bool = False) -> tuple[int, int]:
        """Pixels where *other* blocks *mover* going (+axis, -axis).

        Per pixel each body is reduced to its nearest and farthest surface.
        *other* blocks a move when it sits wholly ahead of the mover's front
        (however thin: a foil on a plate), or when the two spans overlap and
        one reaches more than *interference* past the other's end on the
        side of the motion (it wraps it). Overlaps within *interference* are
        taken for CAD interference (a press fit, a 0.5 mm modelling overlap)
        rather than for a wall. With *ahead_only* only the first rule counts:
        a screw's thread is modelled into a tap-drill hole, so its shank
        "passes through" the part it holds without wrapping it.
        """
        a, b = self.maps[(mover, axis)], self.maps[(other, axis)]
        i0, j0 = max(a.i0, b.i0), max(a.j0, b.j0)
        i1 = min(a.i0 + a.lo.shape[0], b.i0 + b.lo.shape[0])
        j1 = min(a.j0 + a.lo.shape[1], b.j0 + b.lo.shape[1])
        if i1 <= i0 or j1 <= j0:
            return 0, 0
        sa = (slice(i0 - a.i0, i1 - a.i0), slice(j0 - a.j0, j1 - a.j0))
        sb = (slice(i0 - b.i0, i1 - b.i0), slice(j0 - b.j0, j1 - b.j0))
        both = a.mask[sa] & b.mask[sb]
        if not both.any():
            return 0, 0
        alo, ahi, blo, bhi = a.lo[sa][both], a.hi[sa][both], b.lo[sb][both], b.hi[sb][both]
        plus = blo >= ahi - tol
        minus = bhi <= alo + tol
        if not ahead_only:
            plus = plus | (bhi > ahi + interference) | (alo < blo - interference)
            minus = minus | (blo < alo - interference) | (ahi > bhi + interference)
        return int(np.count_nonzero(plus)), int(np.count_nonzero(minus))


# ---------------------------------------------------------------------------
# Planning one group
# ---------------------------------------------------------------------------

def _member_meshes(m) -> list[tuple[np.ndarray, np.ndarray]]:
    if isinstance(m, Group):
        return [(b.vertices, b.faces) for b in m.bodies() if len(b.vertices)]
    return [(m.vertices, m.faces)] if len(m.vertices) else []


def _box_volume(box: np.ndarray) -> float:
    return float(np.prod(np.maximum(box[1] - box[0], 1e-3)))


def choose_base(members: list) -> str:
    """The member everything else is assembled onto: grounded first, then the biggest."""
    def rank(m):
        return (bool(getattr(m, "grounded", False)), _box_volume(m.bbox))
    return max(members, key=rank).key


def _slender_axis(box: np.ndarray) -> int | None:
    ext = box[1] - box[0]
    order = np.argsort(ext)
    if ext[order[2]] > 1.6 * max(ext[order[1]], 1e-6):
        return int(order[2])
    return None


def _fastener_axis(box: np.ndarray) -> int | None:
    """The axis a screw, pin, washer or nut goes in along: its odd-one-out extent."""
    ext = box[1] - box[0]
    order = np.argsort(ext)
    if ext[order[2]] > 1.3 * ext[order[1]]:      # screw, pin: one long axis
        return int(order[2])
    if ext[order[0]] < 0.77 * ext[order[1]]:     # washer, nut: one short axis
        return int(order[0])
    return None


def tilted_plate_axes(members: list, limit: int = 4) -> list[np.ndarray]:
    """Normals of plate-like parts that sit at an angle (a mirror on a 45 degree seat).

    Such a part slides out along its normal, which none of X/Y/Z is; each
    normal becomes one more axis to test (both ways).
    """
    out: list[np.ndarray] = []
    for m in members:
        n = plate_normal(m)
        if n is None or np.max(np.abs(n)) > 0.97 or any(abs(float(n @ e)) > 0.99 for e in out):
            continue
        out.append(n)
        if len(out) >= limit:
            break
    return out


def plate_normal(member) -> np.ndarray | None:
    """Unit normal of a plate-like body (thinnest principal extent), else None."""
    if isinstance(member, Group) or len(member.vertices) < 4:
        return None
    v = member.vertices - member.vertices.mean(axis=0)
    _, vecs = np.linalg.eigh(v.T @ v)
    ext = np.ptp(v @ vecs, axis=0)  # along the principal axes, thinnest first
    if ext[0] > 0.35 * ext[1]:
        return None
    n = vecs[:, 0] / np.linalg.norm(vecs[:, 0])
    return n if n[int(np.argmax(np.abs(n)))] > 0 else -n


def direction_vectors(axes: np.ndarray) -> np.ndarray:
    """Index 2i is +axes[i], 2i+1 is -axes[i] (so ``d ^ 1`` is the opposite)."""
    return np.vstack([s * a for a in axes for s in (1.0, -1.0)])


def direction_label(v: np.ndarray) -> str:
    for i, name in enumerate(DIRECTION_NAMES):
        if float(DIRECTIONS[i] @ v) > 0.999:
            return name
    return "(" + ", ".join(f"{(c if abs(c) >= 0.005 else 0.0):+.2f}" for c in v) + ")"


def _frame_box(box: np.ndarray, frame: np.ndarray) -> np.ndarray:
    """The box (min/max corners) seen in a rotated frame: bounds of its 8 corners."""
    corners = np.array([[box[i][0], box[j][1], box[k][2]] for i in (0, 1) for j in (0, 1) for k in (0, 1)])
    local = corners @ frame.T
    return np.array([local.min(axis=0), local.max(axis=0)])


def stack_offsets(order: list[tuple[str, int]], boxes: dict[str, np.ndarray], placed: dict[str, np.ndarray],
                  gap: float, directions: np.ndarray = DIRECTIONS) -> dict[str, np.ndarray]:
    """Move each (key, direction) in turn until its box clears the boxes placed so far.

    *placed* maps keys already positioned to their (displaced) boxes and is
    extended in place. Returns the displacement of each key in *order*. For
    a tilted direction the boxes are compared in a frame along it.
    """
    out: dict[str, np.ndarray] = {}
    for key, d in order:
        box = boxes[key]
        if d < 0:
            out[key] = np.zeros(3)
            placed[key] = box
            continue
        vec = directions[d]
        frame = axis_frame(vec)
        mine = _frame_box(box, frame)
        need = 0.0
        for other in placed.values():
            theirs = _frame_box(other, frame)
            if any(mine[1][k] <= theirs[0][k] + 0.05 or theirs[1][k] <= mine[0][k] + 0.05 for k in (0, 1)):
                continue  # not in the way across the motion
            need = max(need, theirs[1][2] - mine[0][2] + gap)
        shift = vec * need
        out[key] = shift
        placed[key] = box + shift
    return out


def plan_group(group: Group, child_plans: dict[str, GroupPlan], gap: float = 8.0, tol: float = 0.15,
               interference: float = 0.75, min_area: float = 0.6, resolution: float | None = None,
               log=print) -> GroupPlan:
    """Assembly rounds and explosion offsets of one group.

    A member counts as blocked when at least *min_area* mm^2 of its footprint
    is blocked (tessellation noise and touching rims stay below that).
    Members with ``info["fastener"]`` (screws, pins, washers) only block and
    are only blocked by what sits wholly in front of them.
    """
    members = {m.key: m for m in group.members}
    if len(members) == 1:
        (only,) = members
        return GroupPlan(group, only, [Placement(only, -1, 0)], {only: np.zeros(3)},
                         _exploded_box(members[only], child_plans), DIRECTIONS.copy())
    extra = tilted_plate_axes(list(members.values()))
    axes = np.vstack([np.eye(3)] + [e[None, :] for e in extra])
    directions = direction_vectors(axes)
    maps = DepthMaps({k: _member_meshes(m) for k, m in members.items()}, resolution=resolution, axes=axes)
    min_pixels = max(2, int(np.ceil(min_area / maps.res ** 2)))
    keys = list(members)
    # pixels[k][o][d]: how much o blocks k moving along direction d
    pixels = {k: {o: np.zeros(len(directions), int) for o in keys if o != k} for k in keys}
    # Along its own axis a fastener's thread sits inside the part it holds
    # (tap-drill hole); across it, the shank blocks like any other body.
    fastener_axis = {}
    for k, m in members.items():
        fa = _fastener_axis(m.bbox) if getattr(m, "info", {}).get("fastener") else None
        fastener_axis[k] = None if fa is None else np.eye(3)[fa]
    normals = {k: plate_normal(m) for k, m in members.items()}
    for i, k in enumerate(keys):
        for o in keys[i + 1:]:
            for axis in range(len(axes)):
                ahead_only = any(f is not None and abs(float(f @ axes[axis])) > 0.95
                                 for f in (fastener_axis[k], fastener_axis[o]))
                plus, minus = maps.blocking(k, o, axis, tol, interference, ahead_only=ahead_only)
                pixels[k][o][direction_index(axis, +1)] = plus
                pixels[k][o][direction_index(axis, -1)] = minus
                # symmetric: o moving +axis is blocked by k exactly when k moving -axis is blocked by o
                pixels[o][k][direction_index(axis, +1)] = minus
                pixels[o][k][direction_index(axis, -1)] = plus

    base = choose_base(list(members.values()))
    base_center = members[base].bbox.mean(axis=0)
    remaining = [k for k in keys if k != base]
    removal_rounds: list[list[Placement]] = []

    def blockers(k: str, d: int, present: list[str]) -> list[str]:
        return [o for o in present if o != k and pixels[k][o][d] >= min_pixels]

    def score(k: str, d: int) -> float:
        box = members[k].bbox
        vec = directions[d]
        center = box.mean(axis=0)
        out = center - base_center
        norm = np.linalg.norm(out)
        s = float(np.dot(vec, out / norm)) if norm > 1e-6 else 0.0
        slender = _slender_axis(box)
        if slender is not None and abs(vec[slender]) > 0.99:
            s += 1.5
        n = normals[k]
        if n is not None and abs(float(vec @ n)) > 0.99:
            s += 0.6  # a plate slides along its normal
        elif d >= 6:
            s -= 0.2  # someone else's tilted axis: only when nothing plainer is free
        s += 0.05 * (vec[2] > 0.99)  # gentle preference for "from above"
        return s

    while remaining:
        present = remaining + [base]
        free: list[Placement] = []
        for k in remaining:
            options = [d for d in range(len(directions)) if not blockers(k, d, present)]
            if options:
                best = max(options, key=lambda d: score(k, d))
                free.append(Placement(k, best, 0))
        if not free:
            # Interlocked or overlapping CAD: take out what is least stuck.
            def stuck(kd):
                k, d = kd
                return sum(int(pixels[k][o][d]) for o in present if o != k)
            k, d = min(((k, d) for k in remaining for d in range(len(directions))),
                       key=lambda kd: (stuck(kd), -score(*kd)))
            log(f"    ! {members[k].label}: no free direction, taking it out along "
                f"{direction_label(directions[d])} ({stuck((k, d))} blocked px)")
            free = [Placement(k, d, 0, forced=True)]
        removal_rounds.append(free)
        gone = {p.key for p in free}
        remaining = [k for k in remaining if k not in gone]

    # What each member rests against: present at its removal and blocking it going back in.
    placements = [Placement(base, -1, 0)]
    present_after: list[str] = [base]
    for r, round_ in enumerate(reversed(removal_rounds), start=1):
        for p in round_:
            p.round = r
            opposite = p.direction ^ 1
            p.blocked_by = [o for o in present_after if pixels[p.key][o][opposite] >= min_pixels]
        placements.extend(round_)
        present_after.extend(p.key for p in round_)

    boxes = {k: _exploded_box(m, child_plans) for k, m in members.items()}
    offsets = stack_offsets([(p.key, p.direction) for p in placements], boxes, {}, gap, directions)
    # A parent clears this group's exploded extent. Parts modelled far from
    # the rest (a connector at the end of a 25 cm strand) would blow it up.
    attached = [k for k in keys if _box_distance(boxes[k], boxes[base]) <= max(15.0, 0.5 * _box_diagonal(boxes[base]))]
    exploded = [boxes[k] + offsets[k] for k in attached]
    exploded_bbox = np.array([np.min([b[0] for b in exploded], axis=0), np.max([b[1] for b in exploded], axis=0)])
    return GroupPlan(group, base, placements, offsets, exploded_bbox, directions)


def _box_distance(a: np.ndarray, b: np.ndarray) -> float:
    gap = np.maximum(0.0, np.maximum(a[0] - b[1], b[0] - a[1]))
    return float(np.linalg.norm(gap))


def _box_diagonal(a: np.ndarray) -> float:
    return float(np.linalg.norm(a[1] - a[0]))


def _exploded_box(member, child_plans: dict[str, GroupPlan]) -> np.ndarray:
    if isinstance(member, Group) and member.key in child_plans:
        return child_plans[member.key].exploded_bbox
    return member.bbox


# ---------------------------------------------------------------------------
# Whole module
# ---------------------------------------------------------------------------

def plan(root: Group, gap: float = 8.0, tol: float = 0.15, max_new_per_step: int = 2, log=print) -> Plan:
    """Plan every group bottom-up, then derive the full explosion and the steps."""
    plans: dict[str, GroupPlan] = {}

    def visit(g: Group) -> None:
        for m in g.members:
            if isinstance(m, Group):
                visit(m)
        plans[g.key] = plan_group(g, plans, gap=gap, tol=tol, log=log)

    visit(root)

    displacement: dict[str, np.ndarray] = {}

    def accumulate(g: Group, carried: np.ndarray) -> None:
        gp = plans[g.key]
        for m in g.members:
            shift = carried + gp.offsets[m.key]
            if isinstance(m, Group):
                accumulate(m, shift)
            else:
                displacement[m.key] = shift

    accumulate(root, np.zeros(3))
    steps = make_steps(root, plans, gap=gap, max_new_per_step=max_new_per_step)
    return Plan(root, plans, steps, displacement)


def make_steps(root: Group, plans: dict[str, GroupPlan], gap: float, max_new_per_step: int) -> list[Step]:
    """Steps from the assembly rounds, child groups before their parent.

    A round is split per part type (all four screws of one kind together);
    neighbouring batches are merged again while they share their direction(s)
    and the step keeps at most *max_new_per_step* part types, so a ring that
    follows its lens from above shares the lens's page.
    """
    steps: list[Step] = []
    copies: dict[str, int] = {}

    def count(g: Group) -> None:
        for m in g.members:
            if isinstance(m, Group):
                pid = m.info.get("part", m.key)
                copies[pid] = copies.get(pid, 0) + 1
                count(m)

    count(root)
    seen: set[str] = set()

    def visit(g: Group) -> None:
        for m in g.members:
            if isinstance(m, Group) and len(m.members) > 1:
                pid = m.info.get("part", m.key)
                if pid in seen:  # the same sub-assembly again: built once, "3x"
                    continue
                seen.add(pid)
                visit(m)
        gp = plans[g.key]
        members = {m.key: m for m in g.members}
        quantity = copies.get(g.info.get("part", g.key), 1)

        def part(p: Placement) -> str:
            return members[p.key].info.get("part", p.key)

        by_round: dict[int, list[Placement]] = {}
        decals: list[Placement] = []  # stickers go on last, all on one page
        for p in gp.placements:
            if p.direction < 0:
                continue
            if members[p.key].info.get("decal"):
                decals.append(p)
            else:
                by_round.setdefault(p.round, []).append(p)
        typed: list[list[Placement]] = []
        for r in sorted(by_round):
            kinds: dict[str, list[Placement]] = {}
            for p in by_round[r]:
                kinds.setdefault(part(p), []).append(p)
            typed.extend(kinds.values())
        batches: list[list[Placement]] = []
        for batch in typed:
            if batches:
                last = batches[-1]
                same_dir = {p.direction for p in last} == {p.direction for p in batch}
                distinct = len({part(p) for p in last + batch})
                if same_dir and distinct <= max_new_per_step:
                    last.extend(batch)
                    continue
            batches.append(list(batch))
        if decals:
            batches.append(decals)
        present = [gp.base]
        for batch in batches:
            boxes = {k: _exploded_box(members[k], {}) for k in members}  # children shown assembled
            placed = {k: boxes[k] for k in present}
            offsets = stack_offsets([(p.key, p.direction) for p in batch], boxes, placed, gap, gp.directions)
            steps.append(Step(g, len(steps) + 1, batch, list(present), offsets, quantity))
            present.extend(p.key for p in batch)

    visit(root)
    return steps
