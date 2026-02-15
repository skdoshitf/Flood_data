#!/usr/bin/env python3
"""
Orchestrator entry point for flood zone determination workflow.
Supports both structured parameters and natural language queries.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from src.orchestrator import FloodZoneOrchestrator
from src.models.orchestrator_models import OrchestratorRequest


def parse_args(argv=None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Flood Zone Determination Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Natural language query
  python orchestrator_main.py --query "Check flood zone for 1137 Barnett street, johnstown, pa"
  
  # Structured address
  python orchestrator_main.py --address "1137 Barnett street, johnstown, pa"
  
  # Parcel ID
  python orchestrator_main.py --parcel-id "766620-1420" --region "King County, Washington"
  
  # With options
  python orchestrator_main.py --address "100 Main St, Seattle, WA" --no-loma --output-dir ./results
        """
    )
    
    # Input options (mutually exclusive group)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--query", "-q",
        type=str,
        help="Natural language query (e.g., 'Check flood zone for 1137 Barnett street, johnstown, pa')"
    )
    input_group.add_argument(
        "--address", "-a",
        type=str,
        help="Street address"
    )
    input_group.add_argument(
        "--parcel-id", "-p",
        type=str,
        help="Parcel ID (requires --region)"
    )
    
    # Additional parameters
    parser.add_argument(
        "--region", "-r",
        type=str,
        help="Region/County (required for parcel-id, optional for address)"
    )
    
    # Configuration options
    parser.add_argument(
        "--reportall-key", "-k",
        type=str,
        default="Wtn9iKgWVx",
        help="ReportAll API client key (default: Wtn9iKgWVx)"
    )
    parser.add_argument(
        "--use-wfs",
        action="store_true",
        help="Use WFS endpoint for FEMA (default: REST)"
    )
    parser.add_argument(
        "--no-loma",
        action="store_true",
        help="Skip LOMA detection"
    )
    parser.add_argument(
        "--no-buildings",
        action="store_true",
        help="Skip building analysis"
    )
    parser.add_argument(
        "--loma-radius",
        type=float,
        default=0.05,
        help="LOMA search radius in miles (default: 0.05)"
    )
    
    # Output options
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default=".",
        help="Output directory for generated files (default: current directory)"
    )
    parser.add_argument(
        "--output-json",
        action="store_true",
        help="Print result as JSON"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    
    return parser.parse_args(argv)


def build_request(args: argparse.Namespace) -> OrchestratorRequest:
    """Build OrchestratorRequest from command line arguments."""
    if args.query:
        return OrchestratorRequest(
            natural_language_query=args.query,
            include_loma=not args.no_loma,
            include_buildings=not args.no_buildings,
            use_wfs=args.use_wfs,
            reportall_client_key=args.reportall_key,
            loma_radius_miles=args.loma_radius
        )
    elif args.parcel_id:
        if not args.region:
            raise ValueError("--region is required when using --parcel-id")
        return OrchestratorRequest(
            parcel_id=args.parcel_id,
            region=args.region,
            include_loma=not args.no_loma,
            include_buildings=not args.no_buildings,
            use_wfs=args.use_wfs,
            reportall_client_key=args.reportall_key,
            loma_radius_miles=args.loma_radius
        )
    else:  # args.address
        return OrchestratorRequest(
            address=args.address,
            region=args.region,
            include_loma=not args.no_loma,
            include_buildings=not args.no_buildings,
            use_wfs=args.use_wfs,
            reportall_client_key=args.reportall_key,
            loma_radius_miles=args.loma_radius
        )


def print_result(result, output_json: bool = False, verbose: bool = False):
    """Print orchestrator result."""
    if output_json:
        from dataclasses import asdict
        print(json.dumps(asdict(result), indent=2, default=str))
        return
    
    # Human-readable output
    print("\n" + "=" * 70)
    print("FLOOD ZONE DETERMINATION RESULTS")
    print("=" * 70)
    
    print(f"\nStatus: {result.status.upper()}")
    print(f"Execution Time: {result.execution_time_seconds:.2f} seconds")
    
    if result.error:
        print(f"\nError: {result.error}")
    
    # Address Verification Results
    print("\n" + "-" * 70)
    print("ADDRESS VERIFICATION")
    print("-" * 70)
    av = result.address_verification
    print(f"Address Type: {av.address_type}")
    print(f"Confidence: {av.confidence:.2%}")
    print(f"Routing: {av.routing}")
    print(f"Verification Status: {av.verification_status}")
    
    if av.parcel_centroid:
        print(f"Location: ({av.parcel_centroid[1]:.6f}, {av.parcel_centroid[0]:.6f})")
    
    if av.buildings:
        print(f"Buildings Found: {len(av.buildings)}")
    
    # Flood Zone Results
    print("\n" + "-" * 70)
    print("FLOOD ZONE ANALYSIS")
    print("-" * 70)
    fz = result.flood_zone
    print(f"In Flood Zone: {'YES' if fz.in_flood_zone else 'NO'}")
    
    if fz.primary_zone:
        print(f"Primary Zone: {fz.primary_zone}")
        if fz.zone_subtype:
            print(f"Zone Subtype: {fz.zone_subtype}")
    
    print(f"Flood Zone Features Found: {fz.nfhl_features_count}")
    print(f"Overlapping Zones: {len(fz.flood_zones)}")
    
    if fz.loma_features:
        print(f"\nLOMA Features Found: {len(fz.loma_features)}")
        if fz.nearest_loma_distance_m:
            print(f"Nearest LOMA Distance: {fz.nearest_loma_distance_m:.2f} meters")
    
    if fz.building_overlaps:
        print(f"\nBuilding Overlaps: {len(fz.building_overlaps)}")
    
    # Output Files
    if result.output_files:
        print("\n" + "-" * 70)
        print("OUTPUT FILES")
        print("-" * 70)
        for filename, filepath in result.output_files.items():
            print(f"  {filename}: {filepath}")
    
    # Verbose output
    if verbose:
        print("\n" + "-" * 70)
        print("LOGS")
        print("-" * 70)
        for log in result.address_verification.logs[-20:]:  # Last 20 logs
            print(f"  {log}")
    
    print("\n" + "=" * 70)


def main(argv=None) -> int:
    """Main entry point."""
    try:
        args = parse_args(argv)
        
        # Build request
        request = build_request(args)
        
        # Create orchestrator
        orchestrator = FloodZoneOrchestrator(
            reportall_key=args.reportall_key,
            use_wfs=args.use_wfs,
            output_dir=args.output_dir
        )
        
        # Execute
        result = orchestrator.execute(request)
        
        # Print results
        print_result(result, output_json=args.output_json, verbose=args.verbose)
        
        # Return exit code based on status
        if result.status == "success":
            return 0
        elif result.status == "partial":
            return 1
        else:
            return 2
            
    except KeyboardInterrupt:
        print("\n\nInterrupted by user", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        if args and args.verbose:
            import traceback
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

