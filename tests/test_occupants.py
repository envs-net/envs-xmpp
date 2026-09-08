from envs_xmpp_core.xmpp.occupants import (
    MucOccupant,
    find_occupant_by_jid,
    find_occupant_by_nick,
    find_self_occupant,
    normalize_affiliation,
    normalize_role,
    occupant_is_admin_or_owner,
    occupant_snapshot,
)


def test_normalizes_affiliation_and_role() -> None:
    assert normalize_affiliation(" ADMIN ") == "admin"
    assert normalize_affiliation(None) == "unknown"
    assert normalize_role(" Moderator ") == "moderator"
    assert normalize_role("") == "unknown"


def test_find_occupant_by_nick_and_jid() -> None:
    occupants = {
        "Alice": {"jid": "Alice@Example.org/phone", "affiliation": "MEMBER", "role": "Participant"},
        "Mod": {"jid": "mod@example.org", "affiliation": "ADMIN", "role": "MODERATOR"},
    }
    alice = find_occupant_by_nick(occupants, "alice", room="room@example.org")
    assert alice == MucOccupant(
        room="room@example.org",
        nick="Alice",
        jid="alice@example.org",
        affiliation="member",
        role="participant",
        is_self=False,
    )
    assert find_occupant_by_jid(occupants, "MOD@example.org/resource", room="room@example.org").nick == "Mod"
    assert occupant_is_admin_or_owner(occupants["Mod"])


def test_find_self_occupant_prefers_learned_nick_then_real_jid() -> None:
    occupants = {
        "Configured": {"jid": "stale@example.org", "affiliation": "member", "role": "participant"},
        "Assigned": {"jid": "bot@example.org/new", "affiliation": "owner", "role": "moderator"},
    }
    by_jid = find_self_occupant(
        "room@example.org",
        occupants,
        self_bare_jid="bot@example.org",
        preferred_nick=None,
        fallback_nick="Configured",
    )
    assert by_jid is not None
    assert by_jid.nick == "Assigned"
    assert by_jid.is_self

    preferred = find_self_occupant(
        "room@example.org",
        occupants,
        self_bare_jid="bot@example.org",
        preferred_nick="Configured",
    )
    assert preferred is not None
    assert preferred.nick == "Configured"


def test_occupant_snapshot_marks_self() -> None:
    snapshot = occupant_snapshot(
        "room@example.org",
        {"Bot": {"jid": "bot@example.org/r", "affiliation": "admin", "role": "moderator"}},
        self_bare_jid="bot@example.org",
    )
    occupant = snapshot.self_occupant()
    assert occupant is not None
    assert occupant.nick == "Bot"
    assert occupant.is_admin_or_owner
