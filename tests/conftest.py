"""Register zigbee_manager pure modules without loading the integration __init__.py
(which imports homeassistant, not installed in CI)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _ensure_zigbee_manager_pkg() -> None:
    if "zigbee_manager.const" in sys.modules:
        return
    root = Path(__file__).resolve().parents[1]
    zm_root = root / "custom_components" / "zigbee_manager"

    def load_file(qualname: str, path: Path) -> ModuleType:
        spec = importlib.util.spec_from_file_location(qualname, path)
        if spec is None or spec.loader is None:
            raise ImportError(path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[qualname] = mod
        spec.loader.exec_module(mod)
        return mod

    pkg = ModuleType("zigbee_manager")
    pkg.__path__ = [str(zm_root)]
    sys.modules["zigbee_manager"] = pkg

    load_file("zigbee_manager.const", zm_root / "const.py")
    load_file("zigbee_manager.device_registry", zm_root / "device_registry.py")
    load_file("zigbee_manager.integration_log", zm_root / "integration_log.py")
    load_file("zigbee_manager.alert_format", zm_root / "alert_format.py")
    load_file("zigbee_manager.ha_status", zm_root / "ha_status.py")


_ensure_zigbee_manager_pkg()
