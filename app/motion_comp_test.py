"""Unit checks for page-to-reel composition (no Playwright video encode)."""
from ir.migrate import ensure_current
from ir.motion import build_from_design, interpolate_pose, layers_from_design, validate
from ui_style_dna_test import make_ir


def check(name: str, cond: bool, extra=""):
    if not cond:
        raise AssertionError(f"{name}: {extra}")
    print("[OK]", name)


def main():
    pose = interpolate_pose(
        [{"t": 0, "opacity": 0, "y": 40}, {"t": 100, "opacity": 1, "y": 0}],
        50,
    )
    check("midpoint eases between keyframes", 0.4 < pose["opacity"] < 0.6 and 15 < pose["y"] < 25, str(pose))

    ir = ensure_current(make_ir())
    layers = layers_from_design(ir)
    check("page sections become layers", len(layers) >= 1, str(layers))
    motion = build_from_design(ir, {"width": 1080, "height": 1920, "fps": 30})
    check("composition has keyframed layers", bool(motion.get("layers")) and motion["layers"][0]["keyframes"], str(motion.get("layers")))
    check("single live scene, not a slideshow stack", len(motion["scenes"]) == 1, str(motion["scenes"]))
    errors = validate(motion)
    check("comp Motion IR validates", errors == [], str(errors))
    print("ALL MOTION COMP CHECKS PASSED")


if __name__ == "__main__":
    main()
