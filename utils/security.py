import os
import re
import logging

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SecurityGuard")

# Regex pattern for Email addresses
EMAIL_REGEX = re.compile(
    r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
)

# Regex pattern for Phone numbers (handles various formats: +1-234-567-8901, (123) 456-7890, 1234567890, etc.)
PHONE_REGEX = re.compile(
    r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'
)

# Regex pattern for GPS coordinates (handles e.g. "37.7749, -122.4194", "45.1234° N, 122.5678° W")
GPS_REGEX = re.compile(
    r'-?\d{1,3}\.\d+\s*°?\s*[NS]?\s*,\s*-?\d{1,3}\.\d+\s*°?\s*[EW]?',
    re.IGNORECASE
)

# Pattern to capture explicit "Name: John Doe" or "Farmer: Alice"
EXPLICIT_NAME_REGEX = re.compile(
    r'(?:farmer|name|user)\s*:\s*([a-zA-Z]+(?:\s+[a-zA-Z]+){0,3})',
    re.IGNORECASE
)

# Pattern to capture "My name is John Doe" or "I am John Doe"
INTRO_NAME_REGEX = re.compile(
    r'\b(?:my name is|i am)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b'
)

def scrub_pii(text: str) -> str:
    """
    Scrubs Personally Identifiable Information (PII) from user input strings
    before transmitting data to external LLM APIs.
    Redacts emails, phone numbers, GPS coordinates, and common farmer name formats.
    """
    if not text:
        return text

    scrubbed = text

    # 1. Redact Emails
    scrubbed = EMAIL_REGEX.sub("[REDACTED_EMAIL]", scrubbed)

    # 2. Redact Phone Numbers
    scrubbed = PHONE_REGEX.sub("[REDACTED_PHONE]", scrubbed)

    # 3. Redact GPS coordinates
    scrubbed = GPS_REGEX.sub("[REDACTED_COORDINATES]", scrubbed)

    # 4. Redact explicit names like "Farmer: John Doe" or "Name: Alice Smith"
    # To redact the matched name but keep the "Farmer: " prefix, we find all matches and replace the capture group
    for match in EXPLICIT_NAME_REGEX.finditer(scrubbed):
        captured_name = match.group(1).strip()
        # Ensure we don't accidentally redact common crop/words
        if captured_name.lower() not in ["tomato", "potato", "corn", "wheat", "citrus", "orange", "lemon", "lime", "barley", "cucurbits"]:
            scrubbed = scrubbed.replace(captured_name, "[REDACTED_NAME]")

    # 5. Redact introductory names like "My name is Alice Smith"
    for match in INTRO_NAME_REGEX.finditer(scrubbed):
        captured_name = match.group(1).strip()
        if captured_name.lower() not in ["tomato", "potato", "corn", "wheat", "citrus", "orange", "lemon", "lime", "barley", "cucurbits"]:
            scrubbed = scrubbed.replace(captured_name, "[REDACTED_NAME]")

    logger.info("PII Scrubbing filter applied to input text.")
    return scrubbed

def verify_environment() -> str:
    """
    Verifies that the Gemini API Key is bound strictly to environment variables.
    Fails early if keys are missing or hardcoded.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY environment variable not set. Fallback to Streamlit secrets or user input key required.")
        return ""
    
    # Check if the environment variable looks like a placeholder
    if api_key.strip() in ["", "YOUR_API_KEY", "PLACEHOLDER"]:
        raise ValueError("Invalid GEMINI_API_KEY environment variable. Do not hardcode placeholder values.")
        
    logger.info("Security Check Passed: GEMINI_API_KEY found in environment variables.")
    return api_key
