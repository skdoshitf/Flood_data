
# src/state_machine.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Protocol, Dict, Any, List, Callable, Tuple

from src.models import Address, Evidence
from src.dmn.classify import classify, ClassificationResult  # outlined earlier
from src.dmn.confidence import evaluate, ScoreResult, ScoringConfig

# ---------------------------------------------------------------------------
# 1) Enums & Events (aligns to BPMN steps and message events)
# ---------------------------------------------------------------------------

class State(Enum):
    START = auto()
    CLASSIFY = auto()
    ADDRESS_TYPE_GATEWAY = auto()

    # Standard branch
    STANDARD_VERIFICATION = auto()
    END_STANDARD = auto()

    # Incomplete subprocess (expanded paths)
    INCOMPLETE_START = auto()
    VARIANT_SELECT = auto()
    VARIANT_GATEWAY = auto()

    # Variant paths (A..F)
    PATH_MISSING_STREET_NUMBER = auto()
    PATH_SUBDIVISION = auto()
    PATH_LOT_BLOCK = auto()
    PATH_MISSING_DIRECTION = auto()
    PATH_STR = auto()
    PATH_DRIVING_DIRECTIONS = auto()

    MERGE_VARIANTS = auto()
    CONFIDENCE_EVAL = auto()

    # Routing
    ROUTING_GATEWAY = auto()
    AUTO_COMPLETE = auto()
    END_AUTO = auto()
    HITL_REVIEW = auto()
    END_HITL = auto()
    REQUEST_MORE_INFO = auto()
    END_NONSTANDARD = auto()

    # Loop-back / events
    WAITING_FOR_CUSTOMER_INFO = auto()
    CUSTOMER_INFO_RECEIVED = auto()

    # Failure & recovery
    ERROR = auto()

class MessageEvent(Enum):
    CUSTOMER_INFO = "CustomerInfoReceived"
    # Extend with more events (e.g., ExternalSiteRecovered)

# ---------------------------------------------------------------------------
# 2) Adapter Interfaces (Protocol = contracts for integrations)
# ---------------------------------------------------------------------------

class CountyLookupAdapter(Protocol):
    def confirm_county(self, city: str, zip_code: str) -> bool: ...

class ParcelAdapter(Protocol):
    def search_street(self, city: str, street_name: str) -> Dict[str, Any]: ...
    def owner_match(self, street_name: str, owner_hint: Optional[str]) -> Tuple[bool, int]: ...
    def find_block_lot(self, block: str, lot: str) -> bool: ...
    def get_parcel_by_str(self, str_code: str) -> bool: ...

class PlatMapsAdapter(Protocol):
    def fetch_subdivision_plat(self, subdivision: str, county: Optional[str]) -> bool: ...
    def fetch_rod_plats(self, subdivision_or_blocklot: str) -> bool: ...

class GeoAdapter(Protocol):
    def map_driving_directions(self, directions: str) -> bool: ...

class WorkQueueAdapter(Protocol):
    def create_task(self, ctx_snapshot: Dict[str, Any]) -> str: ...
    def complete_task(self, task_id: str, resolution: str, notes: Optional[str] = None) -> None: ...

class CustomerCommAdapter(Protocol):
    def request_more_info(self, case_id: str, missing_fields: List[str]) -> None: ...

# ---------------------------------------------------------------------------
# 3) Context (process variables + logs + adapter instances)
# ---------------------------------------------------------------------------

@dataclass
class Context:
    address: Address
    evidence: Evidence = field(default_factory=Evidence)

    # Decisions
    classification: Optional[ClassificationResult] = None
    confidence_result: Optional[ScoreResult] = None

    # External state (ids, toggles)
    case_id: str = "CASE-LOCAL-DEMO"
    task_id: Optional[str] = None

    # Adapters (inject concrete implementations in app wiring)
    county: Optional[CountyLookupAdapter] = None
    parcel: Optional[ParcelAdapter] = None
    plats: Optional[PlatMapsAdapter] = None
    geo: Optional[GeoAdapter] = None
    workq: Optional[WorkQueueAdapter] = None
    customer_comm: Optional[CustomerCommAdapter] = None

    # Observability
    logs: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)

    # Control flags
    max_retries: int = 2

    def log(self, msg: str):
        self.logs.append(msg)
        print(msg)  # Replace with logging module in production

# ---------------------------------------------------------------------------
# 4) State Machine (methods mirror BPMN activities/gateways)
# ---------------------------------------------------------------------------

class AddressVerificationSM:
    def __init__(self, ctx: Context, scoring_config: Optional[ScoringConfig] = None):
        self.ctx = ctx
        self.state = State.START
        self.cfg = scoring_config or ScoringConfig()
        self.retry_count: Dict[str, int] = {}

    # ------------- public API -------------
    def run(self) -> Context:
        self._transition(State.CLASSIFY, self._classify)
        self._transition(State.ADDRESS_TYPE_GATEWAY, self._address_type_gateway)
        return self.ctx

    def handle_message(self, event: MessageEvent, payload: Optional[Dict[str, Any]] = None) -> None:
        """Loop-back: when customer info arrives, resume research."""
        if event == MessageEvent.CUSTOMER_INFO:
            self._transition(State.CUSTOMER_INFO_RECEIVED, self._on_customer_info, payload)

    # ------------- framework helpers -------------
    def _transition(self, next_state: State, handler: Callable[..., None], *args, **kwargs):
        self.state = next_state
        self.ctx.log(f"STATE: {self.state.name}")
        try:
            handler(*args, **kwargs)
        except Exception as ex:
            self.ctx.log(f"ERROR in {self.state.name}: {ex}")
            self._transition(State.ERROR, self._on_error, ex)

    def _on_error(self, ex: Exception):
        # Basic policy: fail-fast to HITL; you can add retries or compensations
        self.ctx.log("Policy: routing to HITL due to error")
        self._transition(State.HITL_REVIEW, self._hitl_review)
        self._transition(State.END_HITL, self._end_hitl)

    # -----------------------------------------------------------------------
    # 5) BPMN step handlers
    # -----------------------------------------------------------------------

    # --- Start → Classify ---
    def _classify(self):
        res = classify(self.ctx.address)
        self.ctx.classification = res
        self.ctx.log("Classification: "
                     f"type={res.addressType}, variant={res.variant}, "
                     f"rationale={' | '.join(res.rationale)}")

    # --- Address Type Gateway ---
    def _address_type_gateway(self):
        res = self.ctx.classification
        assert res is not None, "classification must be set"

        if res.addressType == "Standard":
            self._transition(State.STANDARD_VERIFICATION, self._standard_verification)
            self._transition(State.END_STANDARD, self._end_standard)
            return

        if res.addressType == "Non-standard":
            self._transition(State.REQUEST_MORE_INFO, self._request_more_info)
            self._transition(State.END_NONSTANDARD, self._end_nonstandard)
            return

        # Incomplete → expanded subprocess
        self._transition(State.INCOMPLETE_START, self._incomplete_start)
        self._transition(State.VARIANT_SELECT, self._variant_select)
        self._transition(State.VARIANT_GATEWAY, self._variant_gateway)

    # --- Standard branch ---
    def _standard_verification(self):
        self.ctx.log("Run STP verification for complete address")
        # TODO: call services (e.g., parcel->owner, county confirm, AML guardrails)
        self.ctx.metrics["standard_verifications"] = self.ctx.metrics.get("standard_verifications", 0) + 1

    def _end_standard(self):
        self.ctx.log("END: Standard")

    # --- Incomplete subprocess (start) ---
    def _incomplete_start(self):
        self.ctx.log("Entering Incomplete Research subprocess")
        # Reset ambiguity
        self.ctx.evidence.multipleMatches = 0

    def _variant_select(self):
        # Already selected by classify(); keep variant in context
        variant = self.ctx.classification.variant
        self.ctx.log(f"Selected variant: {variant}")

    def _variant_gateway(self):
        v = self.ctx.classification.variant
        if v == "MissingStreetNumber":
            self._transition(State.PATH_MISSING_STREET_NUMBER, self._path_missing_street_number)
        elif v == "Subdivision":
            self._transition(State.PATH_SUBDIVISION, self._path_subdivision)
        elif v == "LotBlock":
            self._transition(State.PATH_LOT_BLOCK, self._path_lot_block)
        elif v == "MissingDirection":
            self._transition(State.PATH_MISSING_DIRECTION, self._path_missing_direction)
        elif v == "STR":
            self._transition(State.PATH_STR, self._path_str)
        elif v == "DrivingDirections":
            self._transition(State.PATH_DRIVING_DIRECTIONS, self._path_driving_directions)
        else:
            # Unknown → fall back to enrichment
            self.ctx.log("Unknown variant → minimal enrichment and request info")
            self._transition(State.REQUEST_MORE_INFO, self._request_more_info)
            self._transition(State.END_NONSTANDARD, self._end_nonstandard)
            return

        self._transition(State.MERGE_VARIANTS, self._merge_variants)
        self._transition(State.CONFIDENCE_EVAL, self._confidence_eval)
        self._transition(State.ROUTING_GATEWAY, self._routing_gateway)

    # --- Variant paths (A..F) ---
    def _path_missing_street_number(self):
        a = self.ctx.address
        # Confirm county via city+ZIP
        self.ctx.evidence.countyConfirmed = bool(a.city and a.zip)
        # Search street name; try owner match
        if a.streetName and self.ctx.parcel:
            owner_found, matches = self.ctx.parcel.owner_match(a.streetName, owner_hint=None)
            self.ctx.evidence.ownerMatch = owner_found
            self.ctx.evidence.multipleMatches = matches if matches >= 2 else 0
        self._set_common_presence_flags()

    def _path_subdivision(self):
        a = self.ctx.address
        if a.subdivision and self.ctx.plats:
            confirmed = self.ctx.plats.fetch_subdivision_plat(a.subdivision, None)
            self.ctx.evidence.subdivisionPlatConfirmed = confirmed
        self._set_common_presence_flags()

    def _path_lot_block(self):
        a = self.ctx.address
        if a.block and a.lot and self.ctx.parcel:
            self.ctx.evidence.parcelMatch = self.ctx.parcel.find_block_lot(a.block, a.lot)
        self._set_common_presence_flags()

    def _path_missing_direction(self):
        a = self.ctx.address
        # Generate candidate directions and verify via parcel/owner/legal
        if a.streetName and a.streetNumber and self.ctx.parcel:
            # Simplified: treat as ambiguous unless we find a clear owner/parcel confirmation
            owner_found, matches = self.ctx.parcel.owner_match(a.streetName, owner_hint=None)
            self.ctx.evidence.directionPresent = owner_found  # proxy
            self.ctx.evidence.multipleMatches = matches if matches >= 2 else 0
        self._set_common_presence_flags()

    def _path_str(self):
        a = self.ctx.address
        if a.str and self.ctx.parcel:
            self.ctx.evidence.strLocated = self.ctx.parcel.get_parcel_by_str(a.str)
        self._set_common_presence_flags()

    def _path_driving_directions(self):
        a = self.ctx.address
        if a.drivingDirections and self.ctx.geo:
            located = self.ctx.geo.map_driving_directions(a.drivingDirections)
            # Treat a successful map as a parcel/owner hint
            self.ctx.evidence.parcelMatch = bool(located)
        self._set_common_presence_flags()

    def _set_common_presence_flags(self):
        a = self.ctx.address
        self.ctx.evidence.streetNamePresent = bool(a.streetName)
        self.ctx.evidence.streetNumberPresent = bool(a.streetNumber)
        self.ctx.evidence.directionPresent = bool(a.direction) or self.ctx.evidence.directionPresent
        # Completeness heuristics (tunable)
        base = 0.1
        base += 0.2 if self.ctx.evidence.countyConfirmed else 0.0
        base += 0.2 if self.ctx.evidence.subdivisionPlatConfirmed else 0.0
        self.ctx.evidence.dataCompleteness = min(1.0, base)
        self.ctx.evidence.docCompleteness = max(self.ctx.evidence.docCompleteness, 0.1)
        self.ctx.evidence.historicalConsistency = max(self.ctx.evidence.historicalConsistency, 0.5)

    # --- Merge & Confidence ---
    def _merge_variants(self):
        self.ctx.log("Merge: evidence prepared → evaluate confidence")

    def _confidence_eval(self):
        # Evaluate confidence & routing via DMN-equivalent
        score_res = evaluate(self.ctx.evidence, self.cfg)
        self.ctx.confidence_result = score_res
        self.ctx.log(f"Confidence score={score_res.normalized_score:.2f}, "
                     f"routing={score_res.routing}")
        # Notes & components for audit
        for c in score_res.components:
            self.ctx.log(f"  + {c.name}: {c.value:+.3f} ({c.reason})")
        for n in score_res.notes:
            self.ctx.log(f"NOTE: {n}")

    # --- Routing gateway ---
    def _routing_gateway(self):
        r = self.ctx.confidence_result.routing
        if r == "Auto":
            self._transition(State.AUTO_COMPLETE, self._auto_complete)
            self._transition(State.END_AUTO, self._end_auto)
        elif r == "Enrich / Request More Info":
            self._transition(State.REQUEST_MORE_INFO, self._request_more_info)
            self._transition(State.WAITING_FOR_CUSTOMER_INFO, self._waiting_for_customer_info)
        else:  # HITL or HITL variants
            self._transition(State.HITL_REVIEW, self._hitl_review)
            self._transition(State.END_HITL, self._end_hitl)

    # --- Actions ---
    def _auto_complete(self):
        self.ctx.log("Auto-completing order")
        # TODO: call posting service

    def _hitl_review(self):
        self.ctx.log("Creating HITL task")
        if self.ctx.workq:
            self.ctx.task_id = self.ctx.workq.create_task(self._snapshot())
            self.ctx.log(f"HITL task created: {self.ctx.task_id}")

    def _end_auto(self):
        self.ctx.log("END: Auto")

    def _end_hitl(self):
        self.ctx.log("END: HITL")

    def _request_more_info(self):
        self.ctx.log("Requesting more info from customer")
        missing = self._detect_missing_fields()
        if self.ctx.customer_comm:
            self.ctx.customer_comm.request_more_info(self.ctx.case_id, missing)

    def _waiting_for_customer_info(self):
        self.ctx.log("Waiting for customer info (message event)")

    def _on_customer_info(self, payload: Optional[Dict[str, Any]]):
        self.ctx.log(f"Customer info received: {payload}")
        # Incorporate new data → resume research
        self._apply_customer_payload(payload or {})
        # Re-run variant path quickly (or full subprocess if needed)
        self._transition(State.VARIANT_GATEWAY, self._variant_gateway)

    def _end_nonstandard(self):
        self.ctx.log("END: Awaiting Info / Close")

    # -----------------------------------------------------------------------
    # 6) Utilities
    # -----------------------------------------------------------------------

    def _detect_missing_fields(self) -> List[str]:
        missing = []
        if not self.ctx.address.streetName: missing.append("streetName")
        if not self.ctx.address.streetNumber: missing.append("streetNumber")
        if not self.ctx.address.direction and self.ctx.classification and self.ctx.classification.variant == "MissingDirection":
            missing.append("direction")
        return missing

    def _apply_customer_payload(self, payload: Dict[str, Any]):
        # Update address/evidence safely
        for k, v in payload.get("address", {}).items():
            if hasattr(self.ctx.address, k):
                setattr(self.ctx.address, k, v)
        for k, v in payload.get("evidence", {}).items():
            if hasattr(self.ctx.evidence, k):
                setattr(self.ctx.evidence, k, v)

    def _snapshot(self) -> Dict[str, Any]:
        return {
            "case_id": self.ctx.case_id,
            "address": vars(self.ctx.address),
            "evidence": vars(self.ctx.evidence),
            "classification": {
                "type": self.ctx.classification.addressType if self.ctx.classification else None,
                "variant": self.ctx.classification.variant if self.ctx.classification else None,
            },
            "confidence": self.ctx.confidence_result.normalized_score if self.ctx.confidence_result else None,
            "routing": self.ctx.confidence_result.routing if self.ctx.confidence_result else None,
            "logs": self.ctx.logs,
        }
