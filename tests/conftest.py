import os

# The suite runs offline whatever the local .env holds: environment variables
# outrank .env in pydantic-settings, and settings objects are built at import.
for _name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET"):
    os.environ[_name] = ""
