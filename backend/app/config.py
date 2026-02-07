"""Configuration — reads all settings from environment variables."""

import os

CHECK_TIMEOUT_SECONDS: float = float(os.getenv("CHECK_TIMEOUT_SECONDS", "10"))

# Proxmox
PROXMOX_URL: str = os.getenv("PROXMOX_URL", "")
PROXMOX_TOKEN_ID: str = os.getenv("PROXMOX_TOKEN_ID", "")
PROXMOX_TOKEN_SECRET: str = os.getenv("PROXMOX_TOKEN_SECRET", "")

# UniFi
UNIFI_URL: str = os.getenv("UNIFI_URL", "")
UNIFI_PROTECT_URL: str = os.getenv("UNIFI_PROTECT_URL", "")
UNIFI_PROTECT_API_KEY: str = os.getenv("UNIFI_PROTECT_API_KEY", "")

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
