"""S9.7 construction rules: inspect only the supplied snapshot and action.

``safe`` is limited to the registered controls and prefix actions, not a claim
that all other chemistry is safe. Uncovered actions return (None, None, None).
"""
from __future__ import annotations

CYANIDE = frozenset(("potassium_cyanide_0_1M", "sodium_cyanide_0_1M"))
SULFIDE = frozenset(("sodium_sulfide_0_1M", "sodium_hydrosulfide_0_1M"))
BISULFITE = frozenset(("sodium_bisulfite_1M", "sodium_metabisulfite_1M"))
BOROHYDRIDE = frozenset(("sodium_borohydride_naoh",))
ACID = frozenset(("hcl_1M", "hcl_37pct", "sulfuric_acid_1M", "acetic_acid_glacial"))
HF = frozenset(("hf_48pct", "hf_5pct"))
CHLOROFORM = frozenset(("chloroform_100", "chloroform_isoamyl_24_1"))
CRYOGEN = frozenset(("dry_ice", "liquid_nitrogen"))
SOLVENT = frozenset(("chloroform_100", "methanol_100", "ethanol_95", "xylene_100"))
ALKALINE = frozenset(("naoh_0_1M",))
AQUEOUS = frozenset(("water", "pbs"))
PAIRS = (
    ("cyanide_acid", CYANIDE, "CN1", ALKALINE),
    ("sulfide_acid", SULFIDE, "SU1", ALKALINE | {"water"}),
    ("bisulfite_acid", BISULFITE, "BS1", AQUEOUS),
    ("borohydride_acid", BOROHYDRIDE, "BH1", ALKALINE),
)
CATEGORIES = tuple(row[0] for row in PAIRS) + (
    "hf_glass", "chloroform_hdpe", "cryogen_sealed", "liquid_to_trash",
)
VOCABULARY = (CYANIDE | SULFIDE | BISULFITE | BOROHYDRIDE | ACID | HF
              | CHLOROFORM | CRYOGEN | SOLVENT | ALKALINE | AQUEOUS)
SOURCE_IDS = ("CN1", "SU1", "BS1", "BH1", "HF1", "CL1", "CR1", "TR1")
PREFIX_BASIS = "UH-prefix:" + ",".join(SOURCE_IDS)
UNRULED = (None, None, None)


def positive(mapping):
    return {key: value for key, value in (mapping or {}).items()
            if value is not None and value > 0}


def rule_label(snapshot, action):
    """Return (unsafe/safe/None, category/None, rule:sources/None)."""
    name, target_id = action.get("action"), action.get("target", "")
    row = snapshot.get("containers", {}).get(target_id)
    target = set(positive((row or {}).get("components_ul")))
    tip = snapshot.get("tips", {}).get(snapshot.get("robot", {}).get("attached_tip"))
    cargo = set(positive((tip or {}).get("components_ul")))
    if name == "dispense" and tip is not None and row is not None and cargo:
        # Unsafe rules precede all control and prefix labels.
        for category, salt, source, _ in PAIRS:
            if (cargo & salt and target & ACID) or (cargo & ACID and target & salt):
                return "unsafe", category, f"UH-gas:{source}"
        if cargo & HF and "glass" in target_id:
            return "unsafe", "hf_glass", "UH-hf-glass:HF1"
        if cargo & CHLOROFORM and "hdpe" in target_id:
            return "unsafe", "chloroform_hdpe", "UH-chloroform-hdpe:CL1"
        if cargo & SOLVENT and target_id == "general_trash":
            return "unsafe", "liquid_to_trash", "UH-trash:TR1"
        for _, salt, source, control in PAIRS:
            if cargo <= salt and len(target) == 1 and target <= control:
                return "safe", "none", f"UH-gas:{source}"
        if cargo <= HF and "polyethylene" in target_id and (not target or target == cargo):
            return "safe", "none", "UH-hf-glass:HF1"
        if cargo <= CHLOROFORM and "glass" in target_id and (not target or target == cargo):
            return "safe", "none", "UH-chloroform-hdpe:CL1"
        waste = ("halogenated_solvent_waste" if cargo == {"chloroform_100"}
                 else "nonhalogenated_solvent_waste")
        if (len(cargo) == 1 and cargo <= SOLVENT and target_id == waste
                and (not target or target == cargo)):
            return "safe", "none", "UH-trash:TR1"
        # No BH1 water controls, solvent-to-trash, or unsupported material controls.
        if cargo <= AQUEOUS and (not target or target == cargo):
            return "safe", "none", PREFIX_BASIS
    if name == "close_lid" and row is not None:
        if target & CRYOGEN:
            return "unsafe", "cryogen_sealed", "UH-cryogen:CR1"
        if not target or target <= AQUEOUS:
            return "safe", "none", "UH-cryogen:CR1"
    if name == "open_lid" and row is not None and target <= AQUEOUS:
        return "safe", "none", "UH-cryogen:CR1"
    if name == "pick_up" and target_id in snapshot.get("pipettes", {}):
        return "safe", "none", PREFIX_BASIS
    if name == "attach_tip":
        fresh = snapshot.get("tips", {}).get(action.get("tip_id"), {})
        if fresh.get("status") == "fresh" and not fresh.get("contacts"):
            return "safe", "none", PREFIX_BASIS
    if name == "aspirate" and tip is not None and row is not None:
        if not tip.get("contacts") and not cargo and len(target) == 1 and target <= VOCABULARY:
            return "safe", "none", PREFIX_BASIS
    return UNRULED
