
#!/usr/bin/env python3
"""
Address Verification — BPMN-aligned State Machine runner
Usage:
  python3 src/main.py --scenario standard
  python3 src/main.py --scenario incomplete --log DEBUG
  python3 src/main.py --scenario nonstandard --output-json
  python3 src/main.py --input ./examples/case1.json --output-json
"""

from __future__ import annotations
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from src.models import Address, Evidence
from src.state_machine import AddressVerificationSM, Context

# --- Scenario builders --------------------------------------------------------

def build_standard_scenario() -> Context:
    addr = Address(
        streetNumber="120",
        streetName="Main St",
        direction="E",
        city="Sample City",
        state="XY",
        zip="12345",
        tbdStreet=False,
    )
    return Context(address=addr)

def build_incomplete_scenario() -> Context:
    addr = Address(
        streetName="Oak Ridge",
        city="Sample City",
        state="XY",
        zip="12345",
        tbdStreet=False,
    )
    # Evidence will be populated by the research step; optionally seed here:
    ev = Evidence(
        externalSitesAvailable=True,
        guardrailsPass=True,
        isHighwayOrNumericStreet=False
    )
    return Context(address=addr, evidence=ev)

def build_nonstandard_scenario() -> Context:
    addr = Address(
        poBox="PO BOX 451",
        city="Sample City",
        state="XY",
        zip="12345",
        tbdStreet=False,
    )
    return Context(address=addr)

# --- JSON loader --------------------------------------------------------------

def _dict_to_address(d: Dict[str, Any]) -> Address:
    return Address(**{k: d.get(k) for k in asdict(Address()).keys() if k in d})

def _dict_to_evidence(d: Dict[str, Any]) -> Evidence:
    # Evidence is optional in input JSON; build default if empty.
    template = Evidence()
    return Evidence(**{k: d.get(k, getattr(template, k)) for k in asdict(template).keys()})

def load_context_from_json(path: Path) -> Context:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"Failed to read JSON from {path}: {e}")

    if "address" not in raw or not isinstance(raw["address"], dict):
        raise RuntimeError("JSON must contain an 'address' object.")

    address = _dict_to_address(raw["address"])
    evidence = _dict_to_evidence(raw.get("evidence", {}))
    return Context(address=address, evidence=evidence)

# --- Runner & printing --------------------------------------------------------

def run_scenario(ctx: Context, *, output_json: bool = False) -> Tuple[int, Optional[Dict[str, Any]]]:
    print("\n=== Address Verification Run ===")
    print(f"Address: {ctx.address}")
    sm = AddressVerificationSM(ctx)
    final_ctx = sm.run()

    summary = {
        "addressType": final_ctx.addressType,
        "confidence": round(final_ctx.confidence, 4),
        "routing": final_ctx.routing,
        "address": asdict(final_ctx.address),
        "evidence": asdict(final_ctx.evidence),
        "statesTrace": [log.split(" — ")[0].replace("STATE: ", "") for log in final_ctx.logs if log.startswith("STATE: ")],
    }

    if output_json:
        print(json.dumps(summary, indent=2))
    else:
        print("\n--- Result ---")
        print(f"Type      : {summary['addressType']}")
        print(f"Confidence: {summary['confidence']}")
        print(f"Routing   : {summary['routing']}")
        print("\n--- Trace ---")
        for s in summary["statesTrace"]:
            print(f" • {s}")

    return 0, summary

# --- CLI ----------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run BPMN-aligned Address Verification state machine")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--scenario", choices=["standard", "incomplete", "nonstandard"], help="Built-in scenario to run")
    g.add_argument("--input", type=Path, help="Path to JSON with 'address' and optional 'evidence'")

    p.add_argument("--output-json", action="store_true", help="Print machine-readable JSON result")
    p.add_argument("--log", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO", help="Verbosity for prints")
    # Quick evidence toggles to simulate environment
    p.add_argument("--external-sites-available", type=str, choices=["true", "false"], help="Override evidence.externalSitesAvailable")
    p.add_argument("--highway", type=str, choices=["true", "false"], help="Override evidence.isHighwayOrNumericStreet")
    p.add_argument("--guardrails-pass", type=str, choices=["true", "false"], help="Override evidence.guardrailsPass")
    return p.parse_args(argv)

def apply_overrides(ctx: Context, args: argparse.Namespace) -> None:
    if args.external_sites_available is not None:
        ctx.evidence.externalSitesAvailable = (args.external_sites_available == "true")
    if args.highway is not None:
        ctx.evidence.isHighwayOrNumericStreet = (args.highway == "true")
    if args.guardrails_pass is not None:
        ctx.evidence.guardrailsPass = (args.guardrails_pass == "true")

def build_context_from_args(args: argparse.Namespace) -> Context:
    if args.scenario == "standard":
        return build_standard_scenario()
    elif args.scenario == "incomplete":
        return build_incomplete_scenario()
    elif args.scenario == "nonstandard":
        return build_nonstandard_scenario()
    elif args.input:
        return load_context_from_json(args.input)
    else:
        # argparse guarantees one of them is present; fallback for type checkers
        raise RuntimeError("No scenario or input specified.")

def main(argv=None) -> int:
    args = parse_args(argv)
    # Basic log control: use prints; integrate logging module later if needed
    print(f"[Log:{args.log}] Starting run")

    try:
        ctx = build_context_from_args(args)
        apply_overrides(ctx, args)
        code, _ = run_scenario(ctx, output_json=args.output_json)
        return code
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
