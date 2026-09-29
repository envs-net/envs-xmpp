"""Task-local OMEMO reply-mode context."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token

_EncryptionValue = tuple[object | None, bool | None]


class TaskLocalEncryptionMode:
    """Keep reply encryption state scoped to exactly one asyncio task.

    ``ContextVar`` values are inherited by child tasks.  Binding the value to
    the task that created it prevents unrelated background tasks from silently
    inheriting the transport policy of an incoming encrypted command.
    """

    def __init__(self, name: str = "xmpp_reply_encrypted") -> None:
        self._context: ContextVar[_EncryptionValue | None] = ContextVar(name, default=None)

    def set(self, encrypted: bool | None) -> Token[_EncryptionValue | None]:
        return self._context.set((asyncio.current_task(), encrypted))

    def reset(self, token: Token[_EncryptionValue | None]) -> None:
        self._context.reset(token)

    def get(self) -> bool | None:
        value = self._context.get()
        if value is None:
            return None
        owner_task, encrypted = value
        if owner_task is not None and asyncio.current_task() is not owner_task:
            return None
        return encrypted


__all__ = ["TaskLocalEncryptionMode"]
