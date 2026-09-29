"""Optional slixmpp-omemo plugin/storage adapter shared by envs.net bots."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, cast

from .storage import PRIVATE_FILE_MODE, prepare_storage_file

try:  # optional runtime dependency
    import slixmpp_omemo as XEP_0384_module
    from omemo.storage import Just, Maybe, Nothing, Storage
    from omemo.types import DeviceInformation, JSONType
    from slixmpp.plugins import register_plugin

    XEP_0384: Any = XEP_0384_module.XEP_0384
    OMEMO_AVAILABLE = True
except Exception:  # noqa: BLE001  # pragma: no cover - optional dependency probe
    Just = Maybe = Nothing = Storage = None
    DeviceInformation = JSONType = Any
    XEP_0384 = None
    XEP_0384_module = None
    OMEMO_AVAILABLE = False

XEP_0384Impl: Any = None

if OMEMO_AVAILABLE and XEP_0384 is not None:  # pragma: no cover - optional extra

    class JsonFileStorage(Storage):
        """Private JSON-backed OMEMO storage."""

        def __init__(self, json_file_path: Path) -> None:
            super().__init__()
            self._json_file_path = prepare_storage_file(Path(json_file_path))
            with self._json_file_path.open(encoding="utf8") as handle:
                content = handle.read().strip()
            self._data: dict[str, JSONType] = json.loads(content) if content else {}

        async def _load(self, key: str) -> Maybe[JSONType]:
            return Just(self._data[key]) if key in self._data else Nothing()

        async def _store(self, key: str, value: JSONType) -> None:
            self._data[key] = value
            self._write()

        async def _delete(self, key: str) -> None:
            self._data.pop(key, None)
            self._write()

        def _write(self) -> None:
            tmp_path = self._json_file_path.with_suffix(self._json_file_path.suffix + ".tmp")
            fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_FILE_MODE)
            with os.fdopen(fd, "w", encoding="utf8") as handle:
                json.dump(self._data, handle)
            os.chmod(tmp_path, PRIVATE_FILE_MODE)
            tmp_path.replace(self._json_file_path)
            os.chmod(self._json_file_path, PRIVATE_FILE_MODE)


    class _XEP_0384Impl(XEP_0384):
        default_config: ClassVar[dict[str, Any]] = {
            "fallback_message": "This message is OMEMO encrypted.",
            "json_file_path": None,
        }

        def plugin_init(self) -> None:
            if not self.json_file_path:
                raise RuntimeError("OMEMO JSON storage path not specified")
            storage_factory = cast(Callable[[Path], Storage], JsonFileStorage)
            self._storage = storage_factory(Path(self.json_file_path))
            super().plugin_init()

        @property
        def storage(self) -> Storage:
            return self._storage

        @property
        def _btbv_enabled(self) -> bool:
            return True

        async def _devices_blindly_trusted(
            self,
            blindly_trusted: frozenset[DeviceInformation],
            identifier: str | None,
        ) -> None:
            del blindly_trusted, identifier

        async def _prompt_manual_trust(
            self,
            manually_trusted: frozenset[DeviceInformation],
            identifier: str | None,
        ) -> None:
            del manually_trusted, identifier

    XEP_0384Impl = _XEP_0384Impl
    register_plugin(_XEP_0384Impl)


__all__ = [
    "OMEMO_AVAILABLE",
    "XEP_0384Impl",
    "XEP_0384_module",
]
