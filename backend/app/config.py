"""Configuration — reads all settings from environment variables."""

import os


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str) -> list[str]:
    raw = os.getenv(name, "")
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


REQUEST_TIMEOUT_SECONDS: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "4"))
CHECK_TIMEOUT_SECONDS: float = float(os.getenv("CHECK_TIMEOUT_SECONDS", str(REQUEST_TIMEOUT_SECONDS)))
REFRESH_INTERVAL_SECONDS: float = float(os.getenv("REFRESH_INTERVAL_SECONDS", "30"))
MAX_CONCURRENCY: int = int(os.getenv("MAX_CONCURRENCY", "10"))
SERVICES_CONFIG_PATH: str = os.getenv("SERVICES_CONFIG_PATH", "/data/services.json")
OBSERVATIONS_PATH: str = os.getenv("OBSERVATIONS_PATH", "/data/observations.json")
OBSERVATIONS_HISTORY_LIMIT: int = int(os.getenv("OBSERVATIONS_HISTORY_LIMIT", "200"))
EXPOSE_SERVICE_URLS: bool = _env_bool("EXPOSE_SERVICE_URLS", False)
CORS_ORIGINS: list[str] = _env_csv("CORS_ORIGINS")
FLAP_WINDOW_SECONDS: int = int(os.getenv("FLAP_WINDOW_SECONDS", "600"))
FLAP_THRESHOLD: int = int(os.getenv("FLAP_THRESHOLD", "3"))
ADMIN_TOKEN: str = os.getenv("ADMIN_TOKEN", "")

# Proxmox
PROXMOX_URL: str = os.getenv("PROXMOX_URL", "")
PROXMOX_API_TOKEN: str = os.getenv("PROXMOX_API_TOKEN", "")

# UniFi
UNIFI_URL: str = os.getenv("UNIFI_URL", "")
UNIFI_PROTECT_URL: str = os.getenv("UNIFI_PROTECT_URL", "")
UNIFI_API_KEY: str = os.getenv("UNIFI_API_KEY", "")

# Home Assistant
HOMEASSISTANT_URL: str = os.getenv("HOMEASSISTANT_URL", "")
HOMEASSISTANT_TOKEN: str = os.getenv("HOMEASSISTANT_TOKEN", "")

# Plex
PLEX_URL: str = os.getenv("PLEX_URL", "")
PLEX_TOKEN: str = os.getenv("PLEX_TOKEN", "")

# Overseerr
OVERSEERR_URL: str = os.getenv("OVERSEERR_URL", "")
OVERSEERR_API_KEY: str = os.getenv("OVERSEERR_API_KEY", "")

# Tautulli
TAUTULLI_URL: str = os.getenv("TAUTULLI_URL", "")
TAUTULLI_API_KEY: str = os.getenv("TAUTULLI_API_KEY", "")

# Arr Stack
RADARR_URL: str = os.getenv("RADARR_URL", "")
RADARR_API_KEY: str = os.getenv("RADARR_API_KEY", "")
SONARR_URL: str = os.getenv("SONARR_URL", "")
SONARR_API_KEY: str = os.getenv("SONARR_API_KEY", "")

# Ollama
OLLAMA_URL: str = os.getenv("OLLAMA_URL", "")

# n8n
N8N_URL: str = os.getenv("N8N_URL", "")
