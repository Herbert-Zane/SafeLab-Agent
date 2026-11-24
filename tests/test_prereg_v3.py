"""preregistration_v3.md and the code that runs and analyses it agree."""
import hashlib
import importlib.util
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PREREG = (REPO/"experiments"/"preregistration_v3.md").read_text(encoding="utf-8")


def load(name):
    spec = importlib.util.spec_from_file_location(name, REPO/"experiments"/f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha12(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:12]


def test_pinned_configs_and_briefs_match_the_files_and_the_preregistration():
    design = load("run_v3").BATCHES["confirm_v3"]
    for key, digest in design["pins"].items():
        path = REPO/key if key.startswith("configs/") else None
        if path is None and key.endswith(".cards.json"):
            path = REPO/"experiments"/"briefs"/key
        if path is not None:
            assert sha12(path) == digest, key
        assert f"`{digest}`" in PREREG, key


def test_cells_seed_n_and_versions_are_the_preregistered_ones():
    run_v3 = load("run_v3")
    design = run_v3.BATCHES["confirm_v3"]
    assert design["grid"] == (("Applab", "ws"), ("Blab", "ws"), ("Llab", "ws"), ("Clab", "ws"))
    assert design["n"] == 40 and "每格 n = 40，共 160 次" in PREREG
    assert design["seed"] == 20261125 and "20261125" in PREREG
    assert design["tag"] == "prereg-v3" and design["platform"] == "b41eb9b" and "`b41eb9b`" in PREREG
    for code, (agent, brief, safelab) in ((c, run_v3.CELLS[c]) for c, _ in design["grid"]):
        assert agent.endswith("_labels.json"), code
    assert run_v3.CELLS["Llab"][1:] == ("cards", "B") and run_v3.CELLS["Blab"][1:] == ("neutral", "B")
    assert run_v3.CELLS["Applab"][1:] == ("cards", None) and run_v3.CELLS["Clab"][1:] == ("neutral", "C")


def test_the_tests_are_the_preregistered_three():
    analyze_v3 = load("analyze_v3")
    assert analyze_v3.PREREGISTERED["confirm_v3"] is True
    assert analyze_v3.TESTS["confirm_v3"] == (
        ("H-L1", ("Applab", "ws"), ("Clab", "ws")),
        ("H-L2", ("Applab", "ws"), ("Llab", "ws")),
        ("H-L3", ("Blab", "ws"), ("Llab", "ws")))
    assert re.search(r"确认性检验共 3 个", PREREG)


def test_safelab_cells_archive_the_reflection_library():
    run_v3 = load("run_v3")
    for code in ("Blab", "Llab", "Clab", "L", "C", "C4"):
        assert run_v3.is_safelab({"condition": code}), code
    for code in ("Applab", "Alab", "App", "A", "App4"):
        assert not run_v3.is_safelab({"condition": code}), code
