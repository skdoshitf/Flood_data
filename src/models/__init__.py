"""
Data models for agent communication and orchestrator.

Note: This package re-exports Address and Evidence from the parent models.py file
to maintain backward compatibility.
"""

# Import from parent models.py file
import importlib.util
from pathlib import Path

models_file = Path(__file__).parent.parent / "models.py"
spec = importlib.util.spec_from_file_location("_models_file", models_file)
_models_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_models_module)

# Re-export Address and Evidence
Address = _models_module.Address
Evidence = _models_module.Evidence

# Import agent-specific models
from src.models.agent_models import (
    AddressVerificationResult,
    FloodZoneResult,
)
from src.models.orchestrator_models import (
    OrchestratorRequest,
    OrchestratorResult,
)

__all__ = [
    "Address",
    "Evidence",
    "AddressVerificationResult",
    "FloodZoneResult",
    "OrchestratorRequest",
    "OrchestratorResult",
]

