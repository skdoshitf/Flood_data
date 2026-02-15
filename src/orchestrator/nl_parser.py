"""
Natural Language Query Parser for orchestrator.
Parses natural language queries into structured parameters.
"""

import re
from typing import Dict, Any, Optional, Tuple


class NLQueryParser:
    """Parse natural language queries into structured parameters."""
    
    def __init__(self):
        """Initialize parser with common patterns."""
        # Common address patterns
        self.address_patterns = [
            # "Check flood zone for 1137 Barnett street, johnstown, pa"
            r"(?:check|get|find|what.*?|determine).*?flood.*?(?:for|at|in|of)\s+(.+?)(?:\?|$)",
            # "What's the flood risk at 100 Main St, Seattle, WA"
            r"flood.*?risk.*?(?:at|for|in)\s+(.+?)(?:\?|$)",
            # "Verify address and get flood zone info for..."
            r"(?:verify|check).*?address.*?flood.*?(?:for|at|in)\s+(.+?)(?:\?|$)",
        ]
        
        # Parcel ID patterns
        self.parcel_patterns = [
            # "What's the flood risk at parcel 766620-1420 in King County?"
            r"parcel\s+([A-Z0-9\-]+).*?(?:in|at|for)\s+(.+?)(?:\?|$)",
            # "Check flood zone for parcel ID 766620-1420, King County, Washington"
            r"parcel\s+id\s+([A-Z0-9\-]+).*?(?:in|at|for|,)\s+(.+?)(?:\?|$)",
        ]
        
        # Flags/keywords
        self.include_loma_keywords = ["loma", "letter of map amendment", "map amendment"]
        self.include_buildings_keywords = ["building", "buildings", "footprint", "footprints"]
    
    def parse(self, query: str) -> Dict[str, Any]:
        """
        Parse natural language query into structured parameters.
        
        Args:
            query: Natural language query string
            
        Returns:
            Dictionary with structured parameters:
            {
                "mode": "address" | "parcel_id",
                "address": str (optional),
                "q": str (optional, full address),
                "parcel_id": str (optional),
                "region": str (optional),
                "include_loma": bool,
                "include_buildings": bool
            }
        """
        query_lower = query.lower().strip()
        result = {
            "mode": "address",
            "include_loma": self._detect_flag(query_lower, self.include_loma_keywords),
            "include_buildings": self._detect_flag(query_lower, self.include_buildings_keywords),
        }
        
        # Try parcel ID patterns first
        parcel_match = self._match_parcel(query)
        if parcel_match:
            result["mode"] = "parcel_id"
            result["parcel_id"], result["region"] = parcel_match
            return result
        
        # Try address patterns
        address_match = self._match_address(query)
        if address_match:
            result["q"] = address_match
            return result
        
        # If no pattern matches, try to extract address-like text
        # This is a fallback - might not be accurate
        cleaned = self._clean_query(query)
        if cleaned:
            result["q"] = cleaned
            return result
        
        # If we can't parse, return empty (orchestrator will handle error)
        return result
    
    def _match_address(self, query: str) -> Optional[str]:
        """Try to match address patterns in query."""
        for pattern in self.address_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                address = match.group(1).strip()
                # Clean up common trailing words
                address = re.sub(r'\s+(please|thanks|thank you|\.|\?)$', '', address, flags=re.IGNORECASE)
                return address
        return None
    
    def _match_parcel(self, query: str) -> Optional[Tuple[str, str]]:
        """Try to match parcel ID patterns in query."""
        for pattern in self.parcel_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                parcel_id = match.group(1).strip()
                region = match.group(2).strip()
                # Clean up trailing punctuation
                region = re.sub(r'[\.\?]+$', '', region)
                return (parcel_id, region)
        return None
    
    def _detect_flag(self, query: str, keywords: list[str]) -> bool:
        """Detect if any keywords are present in query."""
        return any(keyword in query for keyword in keywords)
    
    def _clean_query(self, query: str) -> Optional[str]:
        """
        Fallback: try to extract address-like text from query.
        This is a simple heuristic and may not be accurate.
        """
        # Remove common question words and commands
        cleaned = re.sub(
            r'^(?:what|where|when|how|check|get|find|determine|verify|show|tell).*?(?:flood|zone|risk|address).*?(?:for|at|in|of)\s+',
            '',
            query,
            flags=re.IGNORECASE
        )
        cleaned = cleaned.strip()
        
        # Remove trailing question marks and common phrases
        cleaned = re.sub(r'[\.\?]+$', '', cleaned)
        cleaned = re.sub(r'\s+(please|thanks|thank you)$', '', cleaned, flags=re.IGNORECASE)
        
        # Check if it looks like an address (has numbers and text)
        if re.search(r'\d+', cleaned) and len(cleaned) > 10:
            return cleaned
        
        return None
    
    def validate_parsed(self, parsed: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate parsed parameters.
        
        Args:
            parsed: Parsed parameters dictionary
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        mode = parsed.get("mode")
        
        if mode == "parcel_id":
            if not parsed.get("parcel_id"):
                return False, "Parcel ID is required for parcel_id mode"
            if not parsed.get("region"):
                return False, "Region is required for parcel_id mode"
        elif mode == "address":
            if not parsed.get("q") and not (parsed.get("address") and parsed.get("region")):
                return False, "Address (q or address+region) is required for address mode"
        else:
            return False, f"Unknown mode: {mode}"
        
        return True, None

