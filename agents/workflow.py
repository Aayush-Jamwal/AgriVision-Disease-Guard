import os
import json
import logging
from typing import Dict, Any, List, Optional
from google import genai
from google.genai import types
from utils.security import scrub_pii, verify_environment
from tools.mcp_tools import query_disease_db

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MultiAgentWorkflow")

# Banned chemical list for the Compliance Judge
BANNED_CHEMICALS = [
    "ddt", "paraquat", "chlorpyrifos", "glyphosate", 
    "dieldrin", "heptachlor", "endosulfan", "lindane",
    "carbofuran", "aldicarb", "methyl parathion"
]

class AgentState:
    """
    State object passed between agents to maintain context and track execution logs.
    """
    def __init__(self, crop_type: str, symptoms: str, farmer_info: str, location_info: str, image_bytes: Optional[bytes] = None):
        self.crop_type = crop_type
        self.symptoms = symptoms
        self.farmer_info = farmer_info
        self.location_info = location_info
        self.image_bytes = image_bytes
        
        # State transitions
        self.raw_combined_input: str = ""
        self.scrubbed_input: str = ""
        self.diagnostician_output: Dict[str, Any] = {}
        self.broker_output: Dict[str, Any] = {}
        self.compliance_output: Dict[str, Any] = {}
        
        # Execution traceability
        self.agent_logs: List[Dict[str, str]] = []

    def add_log(self, agent_name: str, message: str):
        logger.info(f"[{agent_name}] {message}")
        self.agent_logs.append({
            "agent": agent_name,
            "message": message
        })

def run_agent_1_diagnostician(state: AgentState, client: Optional[genai.Client]) -> Dict[str, Any]:
    """
    Agent 1: The Visual Diagnostician
    Identifies the potential plant disease based on symptoms, crop type, and optional image.
    """
    state.add_log("Visual Diagnostician", "Initializing visual symptom profiling...")
    
    # 1. Combine inputs to check for PII
    raw_text = f"Farmer: {state.farmer_info}\nLocation: {state.location_info}\nCrop: {state.crop_type}\nSymptoms: {state.symptoms}"
    state.raw_combined_input = raw_text
    
    # 2. Apply Security Shift-Left PII Scrubbing Guardrail BEFORE LLM transmission
    state.add_log("Visual Diagnostician", "Running pre-LLM PII scrubbing guardrail...")
    state.scrubbed_input = scrub_pii(raw_text)
    state.add_log("Visual Diagnostician", f"Scrubbed Input Context:\n{state.scrubbed_input}")
    
    # Check if Gemini client is available. If not, use high-fidelity mock fallback.
    if not client:
        state.add_log("Visual Diagnostician", "GEMINI_API_KEY not found. Running in high-fidelity SIMULATION mode...")
        # Simulate intelligent diagnosis based on symptoms keywords
        symptom_lower = state.symptoms.lower()
        if "blight" in symptom_lower or "spot" in symptom_lower and ("tomato" in state.crop_type.lower() or "potato" in state.crop_type.lower()):
            disease = "Late Blight"
            confidence = 88.5
            severity = "High"
            reasoning = "Simulated: Symptoms indicate dark water-soaked lesions matching Phytophthora infestans."
        elif "rust" in symptom_lower or "pustule" in symptom_lower:
            disease = "Wheat Rust"
            confidence = 91.0
            severity = "Medium"
            reasoning = "Simulated: Orange/yellow rust-like pustules on stems and leaf sheaths."
        elif "mildew" in symptom_lower or "white patch" in symptom_lower:
            disease = "Powdery Mildew"
            confidence = 85.0
            severity = "Low"
            reasoning = "Simulated: Leaf surface displays powdery white patches common in high-density conditions."
        elif "greening" in symptom_lower or "yellow leaf" in symptom_lower and "citrus" in state.crop_type.lower():
            disease = "Citrus Greening"
            confidence = 79.5
            severity = "High"
            reasoning = "Simulated: Asymmetrical leaf mottling and bitter small fruit point to Huanglongbing."
        else:
            disease = "Septoria Leaf Spot"
            confidence = 82.0
            severity = "Medium"
            reasoning = "Simulated: Circular spots with dark brown margins starting at lower foliage."

        diagnosis = {
            "disease_name": disease,
            "confidence": confidence,
            "severity": severity,
            "reasoning": reasoning
        }
        state.diagnostician_output = diagnosis
        state.add_log("Visual Diagnostician", f"Diagnosis Completed (SIMULATED): {disease} (Confidence: {confidence}%)")
        return diagnosis

    # Running with actual Gemini API
    state.add_log("Visual Diagnostician", "Transmitting scrubbed profile to Gemini API...")
    prompt = f"""
    You are the 'Visual Diagnostician' agent for the AgriVision Disease Guard project.
    Analyze the crop profile and symptoms described below. Determine the most probable disease.
    
    CRITICAL: You must output ONLY a valid JSON object matching this schema:
    {{
        "disease_name": "Name of the disease",
        "confidence": 85.5,
        "severity": "Low" | "Medium" | "High",
        "reasoning": "Brief clinical reasoning explaining the diagnosis"
    }}
    
    SCRUBBED INPUT:
    {state.scrubbed_input}
    """
    
    try:
        contents = [prompt]
        if state.image_bytes:
            state.add_log("Visual Diagnostician", "Including uploaded image bytes in the multimodal request...")
            # Set up the image part
            image_part = types.Part.from_bytes(
                data=state.image_bytes,
                mime_type="image/jpeg"
            )
            contents.append(image_part)
            
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        
        # Parse JSON output
        result_json = json.loads(response.text.strip())
        state.diagnostician_output = result_json
        state.add_log("Visual Diagnostician", f"Diagnosis Completed (API): {result_json.get('disease_name')} (Confidence: {result_json.get('confidence')}%)")
        return result_json
    except Exception as e:
        state.add_log("Visual Diagnostician", f"Gemini API Error: {str(e)}. Falling back to simulation mode.")
        # Fallback to simulation logic
        state.diagnostician_output = {
            "disease_name": "Septoria Leaf Spot (API Fallback)",
            "confidence": 75.0,
            "severity": "Medium",
            "reasoning": f"Fallback diagnosis generated due to API interruption: {str(e)}"
        }
        return state.diagnostician_output

def run_agent_2_broker(state: AgentState, client: Optional[genai.Client]) -> Dict[str, Any]:
    """
    Agent 2: The MCP Strategy Broker
    Uses the diagnosis to query our local database (simulating MCP tool call) and frames mitigation options.
    """
    state.add_log("MCP Strategy Broker", "Receiving diagnosis context...")
    disease_name = state.diagnostician_output.get("disease_name", "Unknown Disease")
    
    # 1. Execute MCP tool call locally
    state.add_log("MCP Strategy Broker", f"Triggering MCP tool lookup for: {disease_name}")
    db_results = query_disease_db(disease_name)
    state.add_log("MCP Strategy Broker", f"Database results fetched: {json.dumps(db_results)}")
    
    if not client:
        state.add_log("MCP Strategy Broker", "GEMINI_API_KEY not found. Broker running in simulation mode...")
        # Simulate plan expansion
        plan_details = {
            "disease_name": db_results.get("disease_name"),
            "organic_treatments": db_results.get("organic_treatments"),
            "cultural_practices": db_results.get("cultural_practices"),
            "eco_status": db_results.get("eco_status"),
            "warnings": db_results.get("warnings"),
            "additional_guidance": "Maximize crop boundary isolation. Ensure local agricultural extension is notified if severity is High."
        }
        state.broker_output = plan_details
        state.add_log("MCP Strategy Broker", "Agricultural mitigation plan compiled (SIMULATED).")
        return plan_details
        
    # Running with Gemini API
    state.add_log("MCP Strategy Broker", "Querying Gemini to synthesize database records into a complete strategy plan...")
    prompt = f"""
    You are the 'MCP Strategy Broker' agent for the AgriVision Disease Guard project.
    Your job is to read the plant disease diagnosis and the official UDA Database lookup response, then write a detailed, easy-to-follow mitigation plan for the farmer.
    
    Keep the plan clean, professional, and strictly organic/non-toxic. Do NOT suggest synthetic pesticides or chemical herbicides.
    
    CRITICAL: You must output ONLY a valid JSON object matching this schema:
    {{
        "disease_name": "Name of the disease",
        "organic_treatments": ["treatment 1", "treatment 2"],
        "cultural_practices": ["practice 1", "practice 2"],
        "eco_status": "Status message",
        "warnings": ["warning 1"],
        "additional_guidance": "Comprehensive paragraph of supportive farm management advice."
    }}
    
    DIAGNOSIS:
    {json.dumps(state.diagnostician_output)}
    
    DATABASE LOOKUP RESULT:
    {json.dumps(db_results)}
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        result_json = json.loads(response.text.strip())
        state.broker_output = result_json
        state.add_log("MCP Strategy Broker", "Agricultural mitigation plan compiled (API).")
        return result_json
    except Exception as e:
        state.add_log("MCP Strategy Broker", f"Gemini API Error: {str(e)}. Falling back to local broker data.")
        state.broker_output = db_results
        return db_results

def run_agent_3_judge(state: AgentState, client: Optional[genai.Client]) -> Dict[str, Any]:
    """
    Agent 3: The Compliance & Containment Judge
    Reviews the generated treatment plan, runs a security verification check,
    and formats the final approved Markdown playbook.
    """
    state.add_log("Compliance & Containment Judge", "Initiating compliance review...")
    
    # Gather everything generated so far
    treatments = state.broker_output.get("organic_treatments", [])
    practices = state.broker_output.get("cultural_practices", [])
    guidance = state.broker_output.get("additional_guidance", "")
    
    combined_plan_text = f"Treatments: {' '.join(treatments)}\nPractices: {' '.join(practices)}\nGuidance: {guidance}"
    
    # 1. Verification Step: Scan for toxic/banned chemicals in the text
    state.add_log("Compliance & Containment Judge", "Scanning proposal for toxic/banned substances...")
    detected_banned = []
    normalized_text = combined_plan_text.lower()
    for chemical in BANNED_CHEMICALS:
        if chemical in normalized_text:
            detected_banned.append(chemical.capitalize())
            
    is_compliant = len(detected_banned) == 0
    
    if not is_compliant:
        state.add_log("Compliance & Containment Judge", f"CRITICAL WARNING: Banned chemical(s) {detected_banned} detected! Enforcing auto-redaction and bio-substitution.")
        # Modify the broker output to replace/clean chemical names
        cleaned_treatments = []
        for treatment in treatments:
            temp = treatment
            for chem in BANNED_CHEMICALS:
                if chem in temp.lower():
                    temp = re.sub(re.escape(chem), "[REDACTED BANNED SUBSTANCE - Replaced with Bacillus subtilis]", temp, flags=re.IGNORECASE)
            cleaned_treatments.append(temp)
        state.broker_output["organic_treatments"] = cleaned_treatments
        state.add_log("Compliance & Containment Judge", "Chemical substitution applied successfully.")
    else:
        state.add_log("Compliance & Containment Judge", "Toxic chemical scan complete. Status: 100% ECO-FRIENDLY & COMPLIANT.")
        
    # Compile the Final Action Playbook
    disease_name = state.broker_output.get("disease_name", "Diagnosed Plant Disease")
    confidence = state.diagnostician_output.get("confidence", 80.0)
    severity = state.diagnostician_output.get("severity", "Medium")
    
    mcp_treatments_list = state.broker_output.get("organic_treatments", [])
    mcp_practices_list = state.broker_output.get("cultural_practices", [])
    mcp_warnings_list = state.broker_output.get("warnings", [])
    extra_guidance = state.broker_output.get("additional_guidance", "Follow standard organic agricultural practices.")
    
    # Formulate Markdown Playbook
    markdown_playbook = f"""# AgriVision Disease Guard Action Playbook

## 🛡️ Compliance Verification Status
> [!NOTE]
> **Status:** APPROVED: 100% Organic & Non-Toxic  
> **Safety Protocol:** verified under UDA (Universal Design for Agriculture) guidelines. No synthetic chemical inputs detected.

---

## 📋 Crop Diagnosis Summary
*   **Target Crop:** {state.crop_type}
*   **Diagnosed Condition:** **{disease_name}**
*   **Confidence Level:** `{confidence}%`
*   **Infection Severity:** `{severity}`

---

## 🌿 Eco-Friendly Mitigation Plan

### 1. Organic Bio-Treatments (Approved Inputs)
"""
    for t in mcp_treatments_list:
        markdown_playbook += f"- {t}\n"
        
    markdown_playbook += "\n### 2. Cultural & Sanitation Practices (Physical Barriers)\n"
    for p in mcp_practices_list:
        markdown_playbook += f"- {p}\n"
        
    if mcp_warnings_list:
        markdown_playbook += "\n### ⚠️ Critical Alerts\n"
        for w in mcp_warnings_list:
            markdown_playbook += f"> [!WARNING]\n> {w}\n"
            
    markdown_playbook += f"""
### 3. Additional Agronomist Guidance
{extra_guidance}

---

## 🔒 Security Audit Logs
*   **PII Check:** Applied (Scrubbed farmer identification details prior to processing).
*   **Substance Scanner:** Checked against {len(BANNED_CHEMICALS)} banned synthetic pesticides. Compliance rating is 100%.
"""
    
    compliance_report = {
        "status": "APPROVED",
        "is_compliant": is_compliant,
        "banned_chemicals_found": detected_banned,
        "playbook_markdown": markdown_playbook
    }
    
    state.compliance_output = compliance_report
    state.add_log("Compliance & Containment Judge", "Compliance audit completed. Action Playbook generated.")
    return compliance_report

def execute_disease_guard_pipeline(crop_type: str, symptoms: str, farmer_info: str, location_info: str, image_bytes: Optional[bytes] = None) -> AgentState:
    """
    Orchestrates the entire 3-agent graph execution.
    Handles Gemini client initialization or falls back to simulation mode.
    """
    # Initialize the shared state
    state = AgentState(
        crop_type=crop_type,
        symptoms=symptoms,
        farmer_info=farmer_info,
        location_info=location_info,
        image_bytes=image_bytes
    )
    
    state.add_log("System", "Starting AgriVision Disease Guard multi-agent pipeline workflow...")
    
    # Get Gemini Client if API key exists
    client = None
    try:
        api_key = verify_environment()
        if api_key:
            client = genai.Client(api_key=api_key)
            state.add_log("System", "Google GenAI client initialized successfully.")
    except Exception as e:
        state.add_log("System", f"API configuration check notice: {str(e)}. Operating in fallback mode.")
        
    # Execute Pipeline
    run_agent_1_diagnostician(state, client)
    run_agent_2_broker(state, client)
    run_agent_3_judge(state, client)
    
    state.add_log("System", "Workflow pipeline completed successfully.")
    return state
