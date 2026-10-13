"""Environment-driven settings. Values come from the process env or a local .env."""

import os

from dotenv import load_dotenv

load_dotenv()

AMD_API_BASE: str | None = os.getenv("AMD_API_BASE")
AMD_API_KEY: str | None = os.getenv("AMD_API_KEY")
AMD_MODEL: str | None = os.getenv("AMD_MODEL")
