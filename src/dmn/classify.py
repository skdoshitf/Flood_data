
# src/dmn/classify.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Literal, Tuple, List

from src.models import Address

# -------------------------
# Types
# -------------------------

AddressType = Literal["Standard", "Incomplete", "Non-standard"]

IncompleteVariant = Literal[
    "MissingStreetNumber",
    "MissingDirection",
    "Subdivision",
    "LotBlock",
    "STR",
    "DrivingDirections",
    "Unknown"
]

@dataclass(frozen=True)
class ClassificationResult:
    """Explainable classification outcome."""
    addressType: AddressType
    variant: Optional[IncompleteVariant]   # None for Standard/Non-standard
    rationale: List[str]


# -------------------------
# Helpers (non-mutating)
# -------------------------

def _is_empty(value: Optional[str]) -> bool:
    return (value is None) or (value.strip() == "")

def _present(value: Optional[str]) -> bool:
    return not _is_empty(value)


# -------------------------
# Core classification
# -------------------------

def classify(address: Address) -> ClassificationResult:
    """
    Implements the Address Type Classification DMN as Python.
    Returns an explainable ClassificationResult containing:
      - addressType: Standard | Incomplete | Non-standard
      - variant: specific incomplete path (or None)
      - rationale: list of reasons that led to the classification
    """
    reasons: List[str] = []

    # --- Non-standard cases ---
    if _present(address.poBox):
        reasons.append("PO Box provided → Non-standard")
        return ClassificationResult("Non-standard", None, reasons)

    if address.tbdStreet:
        reasons.append("TBD street flag set → Non-standard")
        return ClassificationResult("Non-standard", None, reasons)

    # --- Standard case ---
    num_present = _present(address.streetNumber)
    name_present = _present(address.streetName)
    dir_present = _present(address.direction)

    if num_present and name_present:
        reasons.append("Street number and street name present → Standard")
        return ClassificationResult("Standard", None, reasons)

    # --- Incomplete variants (determine research path) ---
    # 1) Missing Street Number with street name present
    if (not num_present) and name_present:
        reasons.append("Street name present, street number missing → Incomplete (MissingStreetNumber)")
        return ClassificationResult("Incomplete", "MissingStreetNumber", reasons)

    # 2) Missing Direction when both number and name exist
    if num_present and name_present and (not dir_present):
        reasons.append("Direction missing with street number & name → Incomplete (MissingDirection)")
        return ClassificationResult("Incomplete", "MissingDirection", reasons)

    # 3) Subdivision only (no street number/name)
    if (not num_present) and (not name_present) and _present(address.subdivision):
        reasons.append("Subdivision specified without street number/name → Incomplete (Subdivision)")
        return ClassificationResult("Incomplete", "Subdivision", reasons)

    # 4) Lot & Block present (no street number)
    if (not num_present) and (_present(address.lot) and _present(address.block)):
        reasons.append("Lot & Block present without street number → Incomplete (LotBlock)")
        return ClassificationResult("Incomplete", "LotBlock", reasons)

    # 5) STR provided (Section–Township–Range)
    if _present(address.str):
        reasons.append("STR provided → Incomplete (STR)")
        return ClassificationResult("Incomplete", "STR", reasons)

    # 6) Driving directions present (no reliable street fields)
    if _present(address.drivingDirections) and (not name_present or not num_present):
        reasons.append("Driving directions present with incomplete street fields → Incomplete (DrivingDirections)")
        return ClassificationResult("Incomplete", "DrivingDirections", reasons)

    # --- Fallback ---
    reasons.append("Insufficient/atypical address details → Incomplete (Unknown)")
    return ClassificationResult("Incomplete", "Unknown", reasons)


# -------------------------
# Optional: variant-only helper
# -------------------------

def detect_incomplete_variant(address: Address) -> IncompleteVariant:
    """Convenience: returns only the variant label; 'Unknown' if none match."""
    res = classify(address)
    return res.variant or "Unknown"
