"""Typed errors used across the provisioning layers."""


class ProvisionerError(Exception):
    """Base class for errors that are safe to present to the user."""


class ConfigurationError(ProvisionerError):
    """The add-on options are incomplete or invalid."""


class SafetyCheckError(ProvisionerError):
    """A precondition for safely changing the network was not met."""


class SupervisorError(ProvisionerError):
    """The Home Assistant Supervisor API failed or returned invalid data."""


class NetworkManagerError(ProvisionerError):
    """The host NetworkManager could not safely manage the Wi-Fi interface."""


class DeviceProtocolError(ProvisionerError):
    """The setup-mode device response was invalid or unexpected."""


class UnsupportedDeviceError(ProvisionerError):
    """The device model or observed protocol is not supported."""


class SessionError(ProvisionerError):
    """A provisioning session is missing, expired, or in the wrong state."""


class RecoveryError(ProvisionerError):
    """One or more steps to restore the AP/network did not succeed."""
