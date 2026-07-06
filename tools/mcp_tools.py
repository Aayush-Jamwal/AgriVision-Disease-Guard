import os
import json
import logging
from typing import Dict, Any, Optional

# Configure logger
logger = logging.getLogger("MCPTools")

# Resolve absolute path to the disease database file
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "disease_database.json")

def query_disease_db(disease_name: str) -> Dict[str, Any]:
    """
    MCP Server Tool Definition: Queries the local database of verified plant disease
    mitigation strategies based on identified disease keywords.
    
    Args:
        disease_name (str): Name or keyword of the diagnosed plant disease.
        
    Returns:
        Dict[str, Any]: A dictionary containing the disease name, symptoms, organic treatments, 
                       cultural practices, and UDA compliance safety status.
    """
    logger.info(f"MCP Tool Triggered: query_disease_db for '{disease_name}'")
    
    # Check if database exists
    if not os.path.exists(DB_PATH):
        logger.error(f"Database not found at {DB_PATH}")
        return {
            "error": "Disease mitigation database is currently offline or unreachable.",
            "status": "Database Error"
        }
        
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            db_data = json.load(f)
    except Exception as e:
        logger.error(f"Error loading disease database: {str(e)}")
        return {
            "error": "Failed to read database records.",
            "status": "Read Error"
        }
        
    # Standardize input for lookup
    search_term = disease_name.lower().strip()
    
    # Try direct key lookup (e.g. late_blight, wheat_rust)
    db_key = search_term.replace(" ", "_")
    if db_key in db_data:
        logger.info(f"Direct match found for key: {db_key}")
        result = db_data[db_key]
        result["key_found"] = db_key
        return result
        
    # Try fuzzy mapping / substring matching
    for key, value in db_data.items():
        # Check if the search term matches key, disease name, or affected crops
        name_match = search_term in value.get("disease_name", "").lower()
        key_match = search_term in key.lower()
        crop_match = any(search_term in crop.lower() for crop in value.get("affected_crops", []))
        
        if name_match or key_match or crop_match:
            logger.info(f"Fuzzy match found: {key} for term: {search_term}")
            result = value.copy()
            result["key_found"] = key
            return result
            
    # Fallback if no verified strategy exists in database
    logger.warning(f"No database match for: {disease_name}. Generating standard UDA fallback protocol.")
    return {
        "disease_name": disease_name,
        "affected_crops": ["Generic Agricultural Crops"],
        "symptoms": "A agricultural plant disease not pre-indexed in our eco-compliance database.",
        "organic_treatments": [
            "Use standard OMRI-certified multi-purpose botanical oil sprays (neem/pyrethrin).",
            "Apply general beneficial microbial inoculants (Bacillus subtilis)."
        ],
        "cultural_practices": [
            "Quarantine infected plants immediately.",
            "Improve field sanitation by removing weeds and dead leaves.",
            "Increase plant spacing to maximize air circulation."
        ],
        "eco_status": "Self-Declared Organic Practice. Manual Verification Required.",
        "warnings": ["Warning: Specific UDA protocol not indexed. Proceed with caution."]
    }
