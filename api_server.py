#!/usr/bin/env python3
"""
Flask web API server for flood zone determination.
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import traceback
from typing import Dict, Any

from src.orchestrator import FloodZoneOrchestrator
from src.models.orchestrator_models import OrchestratorRequest
from src.config import get_config
from src.utils.logger import setup_logger

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for frontend integration

# Setup logger
logger = setup_logger("api_server")

# Global orchestrator instance
orchestrator: FloodZoneOrchestrator = None


def init_orchestrator():
    """Initialize orchestrator with configuration."""
    global orchestrator
    config = get_config()
    
    orchestrator = FloodZoneOrchestrator(
        reportall_key=config.reportall_client_key,
        use_wfs=config.use_wfs,
        output_dir=config.output_dir
    )
    
    logger.info("Orchestrator initialized")


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "flood-zone-determination"
    }), 200


@app.route("/api/v1/flood-zone", methods=["POST"])
def flood_zone_determination():
    """
    Main endpoint for flood zone determination.
    
    Request body (JSON):
    {
        "query": str (optional, natural language query),
        "address": str (optional, street address),
        "parcel_id": str (optional, parcel ID),
        "region": str (optional, region/county),
        "include_loma": bool (optional, default: true),
        "include_buildings": bool (optional, default: true)
    }
    
    Returns:
        JSON response with flood zone determination results
    """
    try:
        if orchestrator is None:
            init_orchestrator()
        
        data = request.get_json() or {}
        
        # Build request
        req = OrchestratorRequest(
            natural_language_query=data.get("query"),
            address=data.get("address"),
            parcel_id=data.get("parcel_id"),
            region=data.get("region"),
            include_loma=data.get("include_loma", True),
            include_buildings=data.get("include_buildings", True),
            reportall_client_key=orchestrator.reportall_key
        )
        
        # Execute
        result = orchestrator.execute(req)
        
        # Convert to JSON-serializable format
        response = {
            "status": result.status,
            "execution_time_seconds": result.execution_time_seconds,
            "address_verification": {
                "address_type": result.address_verification.address_type,
                "confidence": result.address_verification.confidence,
                "routing": result.address_verification.routing,
                "verification_status": result.address_verification.verification_status,
                "parcel_centroid": result.address_verification.parcel_centroid,
                "buildings_count": len(result.address_verification.buildings)
            },
            "flood_zone": {
                "in_flood_zone": result.flood_zone.in_flood_zone,
                "primary_zone": result.flood_zone.primary_zone,
                "zone_subtype": result.flood_zone.zone_subtype,
                "flood_zones_count": len(result.flood_zone.flood_zones),
                "loma_features_count": len(result.flood_zone.loma_features),
                "nearest_loma_distance_m": result.flood_zone.nearest_loma_distance_m,
                "building_overlaps_count": len(result.flood_zone.building_overlaps)
            },
            "output_files": result.output_files,
            "error": result.error
        }
        
        status_code = 200 if result.status == "success" else 400 if result.status == "partial" else 500
        
        return jsonify(response), status_code
        
    except Exception as e:
        logger.error(f"Error in flood-zone endpoint: {e}\n{traceback.format_exc()}")
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc() if app.debug else None
        }), 500


@app.route("/api/v1/address-verify", methods=["POST"])
def address_verification():
    """
    Endpoint for address verification only (Agent 1).
    
    Request body (JSON):
    {
        "query": str (optional, natural language query),
        "address": str (optional, street address),
        "parcel_id": str (optional, parcel ID),
        "region": str (optional, region/county)
    }
    
    Returns:
        JSON response with address verification results
    """
    try:
        if orchestrator is None:
            init_orchestrator()
        
        data = request.get_json() or {}
        
        # Build request (only Agent 1 will run)
        req = OrchestratorRequest(
            natural_language_query=data.get("query"),
            address=data.get("address"),
            parcel_id=data.get("parcel_id"),
            region=data.get("region"),
            include_loma=False,  # Skip Agent 2
            include_buildings=data.get("include_buildings", True),
            reportall_client_key=orchestrator.reportall_key
        )
        
        # Execute only Agent 1
        # For now, we'll use the full orchestrator but could optimize later
        result = orchestrator.execute(req)
        
        response = {
            "status": result.status,
            "address_verification": {
                "address": {
                    "streetNumber": result.address_verification.address.streetNumber,
                    "streetName": result.address_verification.address.streetName,
                    "city": result.address_verification.address.city,
                    "state": result.address_verification.address.state,
                    "zip": result.address_verification.address.zip
                },
                "address_type": result.address_verification.address_type,
                "confidence": result.address_verification.confidence,
                "routing": result.address_verification.routing,
                "verification_status": result.address_verification.verification_status,
                "parcel_centroid": result.address_verification.parcel_centroid,
                "parcel_wkt": result.address_verification.parcel_wkt,
                "buildings": result.address_verification.buildings
            }
        }
        
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"Error in address-verify endpoint: {e}\n{traceback.format_exc()}")
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc() if app.debug else None
        }), 500


@app.route("/api/v1/stats", methods=["GET"])
def get_stats():
    """Get orchestrator statistics."""
    try:
        if orchestrator is None:
            return jsonify({"error": "Orchestrator not initialized"}), 503
        
        # Get cache stats if available
        cache_stats = {}
        if hasattr(orchestrator.agent1, 'cache') and orchestrator.agent1.cache:
            cache_stats = orchestrator.agent1.cache.get_stats()
        
        return jsonify({
            "cache": cache_stats,
            "logs_count": len(orchestrator.logs)
        }), 200
        
    except Exception as e:
        logger.error(f"Error in stats endpoint: {e}")
        return jsonify({"error": str(e)}), 500


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    # Initialize orchestrator on startup
    init_orchestrator()
    
    # Get config for server settings
    config = get_config()
    
    # Run server
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=config.log_level == "DEBUG"
    )

