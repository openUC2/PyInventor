"""explode_plan on boxes: no Inventor needed.  python -m pytest tests"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import explode_plan as ep  # noqa: E402

_FACES = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                   [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])


def boxes(*spans) -> tuple[np.ndarray, np.ndarray]:
    """One mesh of several axis-aligned boxes ((x0, y0, z0), (x1, y1, z1))."""
    vs, fs = [], []
    for k, (lo, hi) in enumerate(spans):
        (x0, y0, z0), (x1, y1, z1) = lo, hi
        vs.append(np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                            [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], float))
        fs.append(_FACES + 8 * k)
    return np.vstack(vs), np.vstack(fs)


def body(key, *spans, grounded=False, **info) -> ep.Body:
    v, f = boxes(*spans)
    return ep.Body(key, key, v, f, grounded=grounded, info={"part": key, **info})


def direction(plan: ep.Plan, group: str, key: str) -> str:
    gp = plan.groups[group]
    return gp.direction_name(gp.placement(key).direction)


def test_cap_goes_on_from_above():
    base = body("base", ((0, 0, 0), (20, 20, 3)), grounded=True)
    cap = body("cap", ((0, 0, 3), (20, 20, 6)))
    plan = ep.plan(ep.Group("m", "m", [base, cap]), log=lambda m: None)
    assert plan.groups["m"].base == "base"
    assert direction(plan, "m", "cap") == "+Z"
    # Exploded clear of the base by the gap: its bottom (z=3) ends up at the base top + 8.
    assert 3 + plan.body_displacement("cap")[2] >= 3 + 8 - 1e-6
    assert np.allclose(plan.body_displacement("base"), 0)


def test_block_leaves_a_channel_through_its_open_side():
    channel = body("channel", ((0, 0, 0), (30, 30, 3)),          # floor
                   ((0, 0, 3), (3, 30, 15)), ((27, 0, 3), (30, 30, 15)),  # walls in x
                   grounded=True)
    block = body("block", ((5, 5, 3), (25, 25, 10)))
    plan = ep.plan(ep.Group("m", "m", [channel, block]), log=lambda m: None)
    # Open towards +Z and along +-Y (no walls there), never through a wall or the floor.
    assert direction(plan, "m", "block") in ("+Z", "+Y", "-Y")
    assert not plan.groups["m"].placement("block").forced


def test_screw_comes_last_even_with_its_thread_inside_the_base():
    base = body("base", ((0, 0, 0), (30, 30, 10)), grounded=True)
    # Plate with a 4 mm square hole at the centre.
    plate = body("plate", ((0, 0, 10), (13, 30, 13)), ((17, 0, 10), (30, 30, 13)),
                 ((13, 0, 10), (17, 13, 13)), ((13, 17, 10), (17, 30, 13)))
    # Head on the plate, shank through the hole and 6 mm into the base (as CAD threads are).
    screw = body("screw", ((11, 11, 13), (19, 19, 16)), ((13.2, 13.2, 4), (16.8, 16.8, 13)), fastener=True)
    plan = ep.plan(ep.Group("m", "m", [base, plate, screw]), log=lambda m: None)
    gp = plan.groups["m"]
    order = [p.key for p in gp.placements]
    assert order.index("plate") < order.index("screw")
    assert direction(plan, "m", "screw") == "+Z"
    assert direction(plan, "m", "plate") == "+Z"
    assert not any(p.forced for p in gp.placements)
    # The screw hovers above the exploded plate.
    plate_top = 13 + plan.body_displacement("plate")[2]
    assert 4 + plan.body_displacement("screw")[2] > plate_top


def test_identical_sub_assemblies_are_built_once():
    def screw_set(n: int, x: float) -> ep.Group:
        washer = body(f"washer{n}", ((x, 0, 5), (x + 6, 6, 5.5)), fastener=True)
        washer.info["part"] = "washer"
        screw = body(f"screw{n}", ((x + 1, 1, 5.5), (x + 5, 5, 8)), ((x + 2, 2, 0), (x + 4, 4, 5.5)), fastener=True,
                     grounded=True)
        screw.info["part"] = "screw"
        return ep.Group(f"set{n}", "SUB - screw set", [screw, washer], info={"part": "screw-set.iam"})

    base = body("plate", ((-5, -5, -10), (40, 10, 0)), grounded=True)
    root = ep.Group("m", "m", [base, screw_set(1, 0), screw_set(2, 20)])
    plan = ep.plan(root, log=lambda m: None)
    sub_steps = [s for s in plan.steps if s.group.label == "SUB - screw set"]
    assert len(sub_steps) >= 1
    assert all(s.quantity == 2 for s in sub_steps)
    assert len({s.group.key for s in sub_steps}) == 1
    # The parent places both sets.
    top = [s for s in plan.steps if s.group.key == "m"]
    assert {p.key for s in top for p in s.new} == {"set1", "set2"}


def test_stack_offsets_clear_previous_boxes():
    boxes_ = {"a": np.array([[0, 0, 0], [10, 10, 2]], float), "b": np.array([[2, 2, 1], [8, 8, 5]], float)}
    out = ep.stack_offsets([("a", -1), ("b", 4)], boxes_, {}, gap=3.0)
    assert np.allclose(out["a"], 0)
    assert np.isclose(out["b"][2], 2 - 1 + 3)


def test_plate_on_a_45_degree_seat_leaves_along_its_normal():
    # Wedge: right-angled prism, slope from (20, y, 0) to (0, y, 20), normal (1, 0, 1)/sqrt2.
    tri = np.array([[0, 0], [20, 0], [0, 20]], float)
    v = np.array([[x, y, z] for y in (0.0, 20.0) for x, z in tri])
    f = np.array([[0, 1, 2], [3, 5, 4], [0, 3, 4], [0, 4, 1], [1, 4, 5], [1, 5, 2], [2, 5, 3], [2, 3, 0]])
    wedge = ep.Body("wedge", "wedge", v, f, grounded=True, info={"part": "wedge"})
    # A 1 mm plate lying on the slope.
    n = np.array([1.0, 0.0, 1.0]) / np.sqrt(2)
    u = np.array([-1.0, 0.0, 1.0]) / np.sqrt(2)
    local, faces = boxes(((-6, 3, 0), (6, 17, 1)))
    centre = np.array([10.0, 0.0, 10.0])
    plate_v = centre + local[:, [0]] * u + local[:, [1]] * np.array([0.0, 1.0, 0.0]) + local[:, [2]] * n
    plate = ep.Body("plate", "plate", plate_v, faces, info={"part": "plate"})
    plan = ep.plan(ep.Group("m", "m", [wedge, plate]), log=lambda m: None)
    gp = plan.groups["m"]
    p = gp.placement("plate")
    assert not p.forced
    assert float(gp.directions[p.direction] @ n) > 0.99
    # Exploded off the slope along the normal, clear of the wedge's box.
    shift = plan.body_displacement("plate")
    assert np.allclose(shift / np.linalg.norm(shift), n, atol=1e-6)
