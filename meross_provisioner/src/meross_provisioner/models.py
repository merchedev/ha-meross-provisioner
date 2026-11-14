"""Platform-independent protocol and workflow data models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AccessPoint:
    """A Wi-Fi access point discovered by the host."""

    ssid: str
    mac: str
    frequency: int
    signal: int
    mode: str = "infrastructure"

    @property
    def looks_like_meross_setup_ap(self) -> bool:
        """Return a UI hint; it is not used as an authorization check."""
        candidate = self.ssid.casefold()
        return any(token in candidate for token in ("meross", "mss", "msl", "msh"))


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Non-secret identity and firmware information from a Meross device."""

    model: str
    subtype: str
    firmware: str
    uuid: str
    mac_address: str


@dataclass(frozen=True, slots=True)
class ProvisioningResult:
    """Public result shown after the device accepts its Wi-Fi configuration."""

    model: str
    subtype: str
    firmware: str
    mac_address: str
    target_ssid: str
    message: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-compatible result without device secrets."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ScanSession:
    """Short-lived state while the configured AP app is paused."""

    session_id: str
    interface: str
    access_point_addon_slug: str
    access_points: tuple[AccessPoint, ...]
    created_at: datetime

    def access_point(self, ssid: str, mac: str) -> AccessPoint | None:
        """Find the exact AP selected by the UI, avoiding SSID-only ambiguity."""
        normalized_mac = mac.casefold()
        return next(
            (
                item
                for item in self.access_points
                if item.ssid == ssid and item.mac.casefold() == normalized_mac
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class DeviceWifiNetwork:
    """The target Wi-Fi network metadata required by Meross setup firmware."""

    ssid: str
    bssid: str
    channel: int
    signal: int
    cipher: int
    encryption: int
