
# src/dmn/confidence.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Literal

from src.models import Evidence

# -------------------------
# Types & constants
# -------------------------

Routing = Literal[
    "Auto",
    "HITL",
    "HITL (disambiguation)",
    "HITL (guardrail fail)",
    "Enrich / Request More Info",
]

@dataclass(frozen=True)
class ScoringConfig:
    """
    Tunable configuration for evidence → confidence scoring & routing.
    Weights mirror the flow diagram and DMN.
    """
    # Positive contributions
    w_owner_match: float = 0.35
    w_parcel_match: float = 0.35
    w_subdivision_plat: float = 0.25
    w_str_located: float = 0.20
    w_county_confirmed: float = 0.05
    w_direction_present: float = 0.05
    w_street_number_present: float = 0.05
    w_street_name_present: float = 0.05
    w_data_completeness: float = 0.20     # multiplied by value (0..1)
    w_doc_completeness: float = 0.15      # multiplied by value (0..1)
    w_historical_consistency: float = 0.15 # multiplied by value (0..1)

    # Penalties
    p_multiple_matches_ge2: float = -0.30
    p_highway_numeric_street: float = -0.10
    p_external_sites_down: float = -0.20

    # Routing thresholds
    t_auto: float = 0.85
    t_hitl: float = 0.60

@dataclass
class ScoreComponent:
    """Explainable contribution (positive or negative) to the score."""
    name: str
    value: float
    reason: str

@dataclass
class ScoreResult:
    """Full scoring + routing outcome for auditability."""
    raw_score: float
    normalized_score: float
    routing: Routing
    components: List[ScoreComponent] = field(default_factory=list)
    guardrail_triggered: bool = False
    ambiguity_detected: bool = False
    notes: List[str] = field(default_factory=list)


# -------------------------
# Core scoring flow
# -------------------------

def compute_score(e: Evidence, cfg: ScoringConfig) -> Tuple[float, List[ScoreComponent]]:
    """
    Step 1: Sum all contributions (collect/SUM), then clamp to [0..1].
    Returns raw score and component breakdown.
    """
    e.clamp()  # keep continuous metrics in bounds

    comps: List[ScoreComponent] = []
    total = 0.0

    # --- Positive signals ---
    if e.ownerMatch:
        comps.append(ScoreComponent("ownerMatch", cfg.w_owner_match, "Owner name confirmed"))
        total += cfg.w_owner_match
    if e.parcelMatch:
        comps.append(ScoreComponent("parcelMatch", cfg.w_parcel_match, "Parcel ID/location confirmed"))
        total += cfg.w_parcel_match
    if e.subdivisionPlatConfirmed:
        comps.append(ScoreComponent("subdivisionPlatConfirmed", cfg.w_subdivision_plat, "Subdivision plat verified"))
        total += cfg.w_subdivision_plat
    if e.strLocated:
        comps.append(ScoreComponent("strLocated", cfg.w_str_located, "STR-based location confirmed"))
        total += cfg.w_str_located
    if e.countyConfirmed:
        comps.append(ScoreComponent("countyConfirmed", cfg.w_county_confirmed, "County confirmed via city+ZIP"))
        total += cfg.w_county_confirmed
    if e.directionPresent:
        comps.append(ScoreComponent("directionPresent", cfg.w_direction_present, "Directional suffix present"))
        total += cfg.w_direction_present
    if e.streetNumberPresent:
        comps.append(ScoreComponent("streetNumberPresent", cfg.w_street_number_present, "Street number present"))
        total += cfg.w_street_number_present
    if e.streetNamePresent:
        comps.append(ScoreComponent("streetNamePresent", cfg.w_street_name_present, "Street name present"))
        total += cfg.w_street_name_present

    # Continuous metrics (scaled)
    if e.dataCompleteness > 0:
        val = cfg.w_data_completeness * e.dataCompleteness
        comps.append(ScoreComponent("dataCompleteness", val, f"Data completeness={e.dataCompleteness:.2f}"))
        total += val
    if e.docCompleteness > 0:
        val = cfg.w_doc_completeness * e.docCompleteness
        comps.append(ScoreComponent("docCompleteness", val, f"Doc completeness={e.docCompleteness:.2f}"))
        total += val
    if e.historicalConsistency > 0:
        val = cfg.w_historical_consistency * e.historicalConsistency
        comps.append(ScoreComponent("historicalConsistency", val, f"Historical consistency={e.historicalConsistency:.2f}"))
        total += val

    # --- Penalties ---
    if e.multipleMatches >= 2:
        comps.append(ScoreComponent("multipleMatches≥2", cfg.p_multiple_matches_ge2, "Ambiguity: multiple candidates"))
        total += cfg.p_multiple_matches_ge2
    if e.isHighwayOrNumericStreet:
        comps.append(ScoreComponent("highwayOrNumericStreet", cfg.p_highway_numeric_street, "Highway/numeric street reduces reliability"))
        total += cfg.p_highway_numeric_street
    if not e.externalSitesAvailable:
        comps.append(ScoreComponent("externalSitesDown", cfg.p_external_sites_down, "External sites unavailable"))
        total += cfg.p_external_sites_down

    # Clamp to [0..1]
    raw = total
    normalized = max(0.0, min(1.0, raw))
    # If we clamped downward, note it.
    if normalized != raw:
        comps.append(ScoreComponent("normalization", normalized - raw, "Score clamped to [0..1]"))

    return normalized, comps


def apply_guardrails_and_ambiguity(e: Evidence) -> Tuple[bool, bool, List[str]]:
    """
    Step 2: Guardrails & ambiguity checks (override routing when needed).
    Returns (guardrail_triggered, ambiguity_detected, notes).
    """
    notes: List[str] = []
    guardrail = False
    ambiguity = False

    if not e.guardrailsPass:
        guardrail = True
        notes.append("Guardrail failed: compliance/policy gate")

    if e.multipleMatches >= 2:
        ambiguity = True
        notes.append(f"Ambiguity: {e.multipleMatches} matches found (needs disambiguation)")

    return guardrail, ambiguity, notes


def route_case(score: float, e: Evidence, cfg: ScoringConfig,
               guardrail: bool, ambiguity: bool) -> Routing:
    """
    Step 3: Routing decision, respecting guardrails/ambiguity overrides.
    """
    if guardrail:
        return "HITL (guardrail fail)"
    if ambiguity:
        return "HITL (disambiguation)"

    if score >= cfg.t_auto:
        return "Auto"
    if score >= cfg.t_hitl:
        return "HITL"
    return "Enrich / Request More Info"


def evaluate(e: Evidence, cfg: ScoringConfig | None = None) -> ScoreResult:
    """
    One-stop function that runs the full flow:
    1) compute_score
    2) apply_guardrails_and_ambiguity
    3) route_case
    Returns ScoreResult with full explainability.
    """
    cfg = cfg or ScoringConfig()

    score, components = compute_score(e, cfg)
    guardrail, ambiguity, notes = apply_guardrails_and_ambiguity(e)
    routing = route_case(score, e, cfg, guardrail, ambiguity)

    return ScoreResult(
        raw_score=score,
        normalized_score=score,  # compute_score already returns normalized
        routing=routing,
        components=components,
        guardrail_triggered=guardrail,
        ambiguity_detected=ambiguity,
        notes=notes,
    )
