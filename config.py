"""Environment-driven settings. Values come from the process env or a local .env.

Settings are loaded on demand, not at import, so the UI can start without
credentials and only the code that calls the model needs them.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

REQUIRED_AMD_VARS = ("AMD_API_BASE", "AMD_API_KEY", "AMD_MODEL")


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class AMDSettings:
    api_base: str
    api_key: str
    model: str

    def __repr__(self) -> str:
        return f"AMDSettings(api_base={self.api_base!r}, api_key='***', model={self.model!r})"


def load_amd_settings() -> AMDSettings:
    missing = [name for name in REQUIRED_AMD_VARS if not os.getenv(name)]
    if missing:
        raise ConfigError(
            f"Missing environment variable(s): {', '.join(missing)}. "
            "Set them in your shell or in .env (see .env.example)."
        )
    return AMDSettings(
        api_base=os.environ["AMD_API_BASE"],
        api_key=os.environ["AMD_API_KEY"],
        model=os.environ["AMD_MODEL"],
    )
