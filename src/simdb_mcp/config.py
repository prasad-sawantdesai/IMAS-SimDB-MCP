"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

AuthMode = Literal["f5", "basic", "none"]

DEFAULT_RETURN_KEYS = ["machine", "pulse", "code.name", "status", "description"]


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_bool(name: str, default: bool) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    return int(_env(name) or default)


def _env_list(name: str) -> list[str]:
    value = _env(name, "") or ""
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    # SimDB server
    simdb_url: str = "https://simdb.iter.org/scenarios/api"
    """Base API URL, without the version suffix (same value as `simdb remote config new`)."""
    api_version: str = "auto"
    """'auto' picks the highest version the server lists at its root (v1.3, else v1.2)."""
    auth_mode: AuthMode = "f5"
    """f5: ITER F5 firewall login (simdb.iter.org); basic: HTTP basic auth sent to
    SimDB directly; none: no authentication."""
    ca_bundle: str | None = None
    """Optional extra CA bundle; the system trust store is used by default."""
    verify_tls: bool = True
    timeout: float = 60.0
    dashboard_url: str | None = None
    """Optional template for dashboard links, e.g.
    https://simdb.iter.org/dashboard/uuid/{uuid}"""

    # Per-user SimDB session cache
    session_ttl: int = 1800
    max_sessions: int = 500

    # Metadata keys returned with every search result when the caller asks for none
    default_return_keys: list[str] = field(default_factory=lambda: list(DEFAULT_RETURN_KEYS))

    # IMAS Data Dictionary (via IMAS-Python) for describing summary-derived keys
    dd_enabled: bool = True
    dd_version: str | None = None
    """DD version to describe keys with. Default: the newest one bundled with IMAS-Python."""

    # Result sizing
    max_value_chars: int = 300
    """Text values longer than this are shortened in search results (0 = never)."""
    default_limit: int = 20
    max_limit: int = 200

    # MCP HTTP endpoint
    host: str = "127.0.0.1"
    port: int = 8000
    path: str = "/mcp"
    allowed_hosts: list[str] = field(default_factory=list)
    allowed_origins: list[str] = field(default_factory=list)

    @property
    def verify(self) -> bool | str:
        if not self.verify_tls:
            return False
        return self.ca_bundle or True

    @classmethod
    def from_env(cls) -> Settings:
        """Settings from SIMDB_* and MCP_* environment variables; unset ones keep the defaults above."""
        auth_mode = (_env("SIMDB_AUTH_MODE") or cls.auth_mode).lower()
        if auth_mode not in ("f5", "basic", "none"):
            raise ValueError(f"SIMDB_AUTH_MODE must be f5, basic or none, not {auth_mode!r}")
        return cls(
            simdb_url=(_env("SIMDB_URL") or cls.simdb_url).rstrip("/"),
            api_version=_env("SIMDB_API_VERSION") or cls.api_version,
            auth_mode=auth_mode,  # type: ignore[arg-type]
            ca_bundle=_env("SIMDB_CA_BUNDLE"),
            verify_tls=_env_bool("SIMDB_VERIFY_TLS", cls.verify_tls),
            timeout=float(_env("SIMDB_TIMEOUT") or cls.timeout),
            dashboard_url=_env("SIMDB_DASHBOARD_URL"),
            session_ttl=_env_int("SIMDB_SESSION_TTL", cls.session_ttl),
            max_sessions=_env_int("SIMDB_MAX_SESSIONS", cls.max_sessions),
            # Unset: the defaults. Set but empty: no default columns.
            default_return_keys=(
                _env_list("SIMDB_DEFAULT_RETURN_KEYS")
                if "SIMDB_DEFAULT_RETURN_KEYS" in os.environ
                else list(DEFAULT_RETURN_KEYS)
            ),
            dd_enabled=_env_bool("SIMDB_DD", cls.dd_enabled),
            dd_version=_env("SIMDB_DD_VERSION"),
            max_value_chars=_env_int("SIMDB_MAX_VALUE_CHARS", cls.max_value_chars),
            default_limit=_env_int("SIMDB_DEFAULT_LIMIT", cls.default_limit),
            max_limit=_env_int("SIMDB_MAX_LIMIT", cls.max_limit),
            host=_env("MCP_HOST") or cls.host,
            port=_env_int("MCP_PORT", cls.port),
            path=_env("MCP_PATH") or cls.path,
            allowed_hosts=_env_list("MCP_ALLOWED_HOSTS"),
            allowed_origins=_env_list("MCP_ALLOWED_ORIGINS"),
        )
