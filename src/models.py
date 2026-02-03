
# src/models.py
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Address:
    streetNumber: Optional[str] = None
    streetName: Optional[str] = None
    direction: Optional[str] = None  # N/S/E/W
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None

    subdivision: Optional[str] = None
    lot: Optional[str] = None
    block: Optional[str] = None
    str: Optional[str] = None                # Section–Township–Range
    drivingDirections: Optional[str] = None
    poBox: Optional[str] = None
    tbdStreet: bool = False

    def __repr__(self) -> str:
        return (
            f"Address(streetNumber={self.streetNumber!r}, streetName={self.streetName!r}, "
            f"direction={self.direction!r}, city={self.city!r}, state={self.state!r}, zip={self.zip!r}, "
            f"subdivision={self.subdivision!r}, lot={self.lot!r}, block={self.block!r}, str={self.str!r}, "
            f"drivingDirections={self.drivingDirections!r}, poBox={self.poBox!r}, tbdStreet={self.tbdStreet})"
        )

@dataclass
class Evidence:
    ownerMatch: bool = False
    parcelMatch: bool = False
    subdivisionPlatConfirmed: bool = False
    strLocated: bool = False
    countyConfirmed: bool = False
    directionPresent: bool = False
    streetNumberPresent: bool = False
    streetNamePresent: bool = False

    dataCompleteness: float = 0.0
    docCompleteness: float = 0.0
    historicalConsistency: float = 0.0

    multipleMatches: int = 0
    isHighwayOrNumericStreet: bool = False
    externalSitesAvailable: bool = True
    guardrailsPass: bool = True

    def clamp(self):
        """Clamp numeric metrics to [0..1] to avoid out-of-range values in scoring."""
        self.dataCompleteness = max(0.0, min(1.0, self.dataCompleteness))
        self.docCompleteness = max(0.0, min(1.0, self.docCompleteness))
