"""Slixmpp connection signature compatibility helpers."""
from __future__ import annotations
import inspect
from collections.abc import Mapping
from typing import Any
from .jid import boundjid_domain, configured_jid_domain


def connect_signature_parameters(connect_method: Any) -> Mapping[str, inspect.Parameter]:
    try:
        return inspect.signature(connect_method).parameters
    except (TypeError, ValueError):
        return {}


def connect_kwargs(xmpp: Any, *, host: object | None, port: object | None, direct_tls: bool, jid_domain: str | None = None) -> dict[str, Any]:
    target_host = host or jid_domain or boundjid_domain(xmpp)
    parameters = connect_signature_parameters(xmpp.connect)
    kwargs: dict[str, Any] = {}
    if "address" in parameters and target_host and port is not None:
        kwargs["address"] = (target_host, int(port))
    else:
        if "host" in parameters and target_host:
            kwargs["host"] = target_host
        if "port" in parameters and port is not None:
            kwargs["port"] = int(port)
    if "use_ssl" in parameters:
        kwargs["use_ssl"] = bool(direct_tls)
    if direct_tls and "force_starttls" in parameters:
        kwargs["force_starttls"] = False
    return kwargs


def connect_kwargs_from_mapping(xmpp: Any, config: Mapping[str, Any]) -> dict[str, Any]:
    return connect_kwargs(
        xmpp,
        host=config.get("host"),
        port=config.get("port"),
        direct_tls=bool(config.get("direct_tls", False)),
        jid_domain=configured_jid_domain(config),
    )


def connection_target(kwargs: Mapping[str, Any], *, fallback_host: object = "auto", fallback_port: object = "auto", direct_tls: bool = False) -> tuple[object, object, str]:
    address = kwargs.get("address") or (None, None)
    host = kwargs.get("host") or address[0] or fallback_host
    port = kwargs.get("port") or address[1] or fallback_port
    return host, port, "direct TLS" if direct_tls else "STARTTLS"


async def maybe_await(result: Any) -> Any:
    if inspect.isawaitable(result):
        return await result
    return result
