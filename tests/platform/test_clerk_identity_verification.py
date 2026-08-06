"""Clerk adapter fail-closed boundary for user-editable identity metadata.

The Clerk primary email address is the only join key from a Clerk subject to a
preprovisioned MedawarCRE user, so an address the account holder has not proven
ownership of must never reach `HumanIdentityStore.resolve_or_bind`. These pins
also cover the two adjacent omissions in the same user-record handling:
`deprovisioned`, and a fetched record whose id is not the authenticated subject.

Every rejection is the adapter's single `None` failure signal. A test that
asserted a distinguishing message would pin an oracle the contract forbids.
"""

from __future__ import annotations

import enum
import sqlite3
import unicodedata
from types import SimpleNamespace

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.platform.admin import AdminControlStore
from cre_mcp.platform.connection import (
    ClerkHumanIdentityVerifier,
    HumanIdentityStore,
    VerifiedHumanIdentity,
)
from cre_mcp.platform.repository import PlatformRepository

CLERK_ISSUER = "https://clerk.example.test"
SUBJECT = "user_clerk_attacker"
VICTIM_EMAIL = "buyer@example.test"


def _config(tmp_path):
    return CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "platform.db",
        human_identity_provider="clerk",
        clerk_secret_key="clerk-test-key",
        clerk_authorized_parties=("https://connect.example.test",),
        clerk_issuer=CLERK_ISSUER,
    )


def _email(address=VICTIM_EMAIL, *, status="verified", identifier="email_primary"):
    """A Clerk email address record shaped like the installed SDK model.

    `verification` is `Nullable[Verification]` upstream, and each verification
    variant carries a `status`. `status=None` models the null field itself.
    """
    verification = None if status is None else SimpleNamespace(status=status)
    return SimpleNamespace(
        id=identifier,
        email_address=address,
        verification=verification,
    )


def _user(
    *,
    emails=None,
    primary="email_primary",
    banned=False,
    locked=False,
    deprovisioned=False,
    user_id=SUBJECT,
):
    return SimpleNamespace(
        id=user_id,
        banned=banned,
        locked=locked,
        deprovisioned=deprovisioned,
        primary_email_address_id=primary,
        email_addresses=[] if emails is None else list(emails),
        first_name="Ada",
        last_name="Buyer",
        username=None,
    )


class AlwaysEqual:
    """Answers true to every comparison.

    Every `isinstance` guard in `_identity_from_user` exists to stop an object
    like this from passing a comparison it has no right to pass, so each one is
    pinned with it.
    """

    def __eq__(self, _other: object) -> bool:
        return True

    __hash__ = None  # type: ignore[assignment]


def _install(monkeypatch, user, *, subject=SUBJECT, issuer=CLERK_ISSUER):
    """Substitute the official Clerk client with one returning `user`."""

    class SubstituteClerk:
        def __init__(self, **_kwargs):
            self.users = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def authenticate_request_async(self, _request, _options):
            return SimpleNamespace(
                is_signed_in=True,
                payload={"sub": subject, "iss": issuer},
            )

        async def get_async(self, *, user_id):
            return user

    import clerk_backend_api

    monkeypatch.setattr(clerk_backend_api, "Clerk", SubstituteClerk)


@pytest.mark.parametrize(
    "status",
    ["unverified", "failed", "expired", "transferable", "", "VERIFIED", None],
)
async def test_unverified_primary_email_is_never_an_identity_claim(
    tmp_path, monkeypatch, status
):
    """An address the Clerk account holder has not proven cannot bind a user.

    `VERIFIED` is included deliberately: the comparison must be exact, not
    case-insensitive, so an unexpected casing fails closed rather than passing.
    """
    _install(monkeypatch, _user(emails=[_email(status=status)]))

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified is None


async def test_verified_primary_email_still_binds(tmp_path, monkeypatch):
    """The positive control: hardening must not break ordinary first sign-in."""
    _install(monkeypatch, _user(emails=[_email(status="verified")]))

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified == VerifiedHumanIdentity("clerk", SUBJECT, VICTIM_EMAIL, "Ada Buyer")


async def test_verified_status_str_enum_member_is_accepted(tmp_path, monkeypatch):
    """The installed SDK types status as a `str` enum. This is the real shape.

    Note it does NOT exercise the `.value` normalization: a `str`-subclass enum
    already satisfies `isinstance(x, str)` and `x == "verified"` on its own.
    The next test is the one that pins `.value`.
    """

    class Status(str, enum.Enum):
        VERIFIED = "verified"

    _install(monkeypatch, _user(emails=[_email(status=Status.VERIFIED)]))

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified == VerifiedHumanIdentity("clerk", SUBJECT, VICTIM_EMAIL, "Ada Buyer")


async def test_verified_status_plain_enum_member_is_normalized_through_value(
    tmp_path, monkeypatch
):
    """A status enum that is not a `str` subclass must still be read.

    Without the `.value` step this denies every call, because a plain
    `enum.Enum` member fails `isinstance(x, str)`. The SDK's enums are `str`
    subclasses today, so nothing else in this module can tell whether that step
    is present — it survived mutation until this pin existed.
    """

    class Status(enum.Enum):
        VERIFIED = "verified"

    _install(monkeypatch, _user(emails=[_email(status=Status.VERIFIED)]))

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified == VerifiedHumanIdentity("clerk", SUBJECT, VICTIM_EMAIL, "Ada Buyer")


async def test_unverified_primary_email_cannot_take_over_a_preprovisioned_user(
    tmp_path, monkeypatch
):
    """The end-to-end consequence, not only the adapter's return value.

    A preprovisioned MedawarCRE user who has never signed in must not become
    bound to a Clerk subject that merely claimed their address.
    """
    config = _config(tmp_path)
    repository = PlatformRepository(config)
    victim = await repository.create_user(VICTIM_EMAIL, "Buyer")
    assert victim is not None
    _install(monkeypatch, _user(emails=[_email(status="unverified")]))

    verified = await ClerkHumanIdentityVerifier(config).verify_bearer("jwt")

    assert verified is None
    HumanIdentityStore(config.cache_db_path)
    with sqlite3.connect(config.cache_db_path) as connection:
        bindings = connection.execute(
            "SELECT COUNT(*) FROM platform_human_identities"
        ).fetchone()[0]
    assert bindings == 0


async def test_deprovisioned_user_is_terminal_like_banned_and_locked(
    tmp_path, monkeypatch
):
    """A disabled account is terminal for protected MCP access.

    `banned` and `locked` were already refused; `deprovisioned` is the same
    class of disabled account and was not.
    """
    _install(
        monkeypatch,
        _user(emails=[_email()], deprovisioned=True),
    )

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified is None


@pytest.mark.parametrize("flag", ["banned", "locked"])
async def test_banned_and_locked_remain_refused(tmp_path, monkeypatch, flag):
    """Re-pinned so the deprovisioned repair cannot regress either sibling."""
    _install(monkeypatch, _user(emails=[_email()], **{flag: True}))

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified is None


async def test_fetched_record_for_a_different_subject_is_refused(
    tmp_path, monkeypatch
):
    """The bound subject and the record supplying the email must be one account."""
    _install(
        monkeypatch,
        _user(emails=[_email()], user_id="user_clerk_someone_else"),
    )

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified is None


async def test_non_primary_verified_address_does_not_substitute_for_the_primary(
    tmp_path, monkeypatch
):
    """A verified secondary must not rescue an unverified primary.

    Without this, a repair that scanned for any verified address would restore
    the same takeover through a second slot.
    """
    _install(
        monkeypatch,
        _user(
            emails=[
                _email(status="unverified"),
                _email(
                    address="attacker@example.test",
                    status="verified",
                    identifier="email_secondary",
                ),
            ]
        ),
    )

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified is None


async def test_verification_without_a_readable_status_fails_closed(
    tmp_path, monkeypatch
):
    """An unexpected verification shape is a refusal, never a default-allow."""
    email = _email()
    email.verification = object()
    _install(monkeypatch, _user(emails=[email]))

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified is None


async def test_a_status_that_merely_claims_equality_is_not_verified(
    tmp_path, monkeypatch
):
    """The status must be a real string, not something answering `== "verified"`.

    Without the `isinstance` guard an address Clerk never marked verified
    becomes a binding key — the same class the sibling guards on `user.id` and
    `email.id` are each pinned against.
    """
    _install(monkeypatch, _user(emails=[_email(status=AlwaysEqual())]))

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified is None


async def test_a_primary_id_that_merely_claims_equality_selects_nothing(
    tmp_path, monkeypatch
):
    """`primary_email_address_id` must be a real string too.

    A truthy object that compares equal to anything would otherwise select a
    non-primary address — exactly the defect this phase closes. The
    blank-on-both-sides pin only covers the emptiness half of this guard.
    """
    _install(
        monkeypatch,
        _user(
            emails=[
                _email(address="attacker@evil.test", identifier="email_secondary")
            ],
            primary=AlwaysEqual(),
        ),
    )

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified is None


async def test_a_non_string_address_is_refused_rather_than_raising():
    """Reached through the direct call, where the dataclass cannot catch it."""
    user = _user(emails=[_email(address=object())])

    assert ClerkHumanIdentityVerifier._identity_from_user(user, SUBJECT) is None


async def test_a_record_that_raises_on_access_is_a_denial_not_an_error(
    tmp_path, monkeypatch
):
    """The user-record examination must sit inside the provider `try`.

    Outside it, an unexpected record shape becomes an unhandled error at the
    call site instead of this module's single `None`.
    """

    class ExplodingUser:
        @property
        def id(self):
            raise RuntimeError("provider record cannot be read")

    _install(monkeypatch, ExplodingUser())

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified is None


# --- repair round: findings from the two independent reviews -----------------


async def test_null_primary_id_does_not_promote_a_non_primary_address(
    tmp_path, monkeypatch
):
    """`None == None` must not designate an address Clerk never made primary.

    In the SDK `EmailAddress.id` is `Optional[str]` and
    `User.primary_email_address_id` is `Nullable[str]`, so a record with both
    unset would otherwise match on the null and bind a stale verified
    secondary. Verified-on-my-account is not the same as is-my-identity.
    """
    _install(
        monkeypatch,
        _user(
            emails=[
                _email(status="unverified", identifier="idn_1"),
                _email(
                    address="attacker@evil.test",
                    status="verified",
                    identifier=None,
                ),
            ],
            primary=None,
        ),
    )

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified is None


async def test_non_ascii_subject_compares_without_raising(tmp_path, monkeypatch):
    """The subject check must be total, in both directions.

    `hmac.compare_digest` raises `TypeError` on non-ASCII strings, so a
    matching pair would have been turned into a refusal (or, before the guard
    moved inside the provider try, into a 500 at the call site) instead of a
    clean comparison. Plain equality is total; these are non-secret ids.
    """
    _install(monkeypatch, _user(emails=[_email()], user_id="user_é"), subject="user_é")
    matched = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert matched == VerifiedHumanIdentity(
        "clerk", "user_é", VICTIM_EMAIL, "Ada Buyer"
    )

    _install(monkeypatch, _user(emails=[_email()], user_id="user_ø"), subject="user_é")
    mismatched = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer(
        "jwt"
    )

    assert mismatched is None


async def test_an_id_that_merely_claims_equality_is_not_a_primary_id(
    tmp_path, monkeypatch
):
    """The primary slot is matched on a real string, not on `__eq__`.

    Without this, an object that answers True to every comparison — a proxy or
    a leaked test double — would select itself as the primary address. This is
    the only shape that distinguishes the `isinstance` guard on `email.id`
    from the guard on `primary_email_address_id`; against ordinary inputs the
    two are redundant.
    """

    _install(
        monkeypatch,
        _user(emails=[_email(address="attacker@evil.test", identifier=AlwaysEqual())]),
    )

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified is None


async def test_blank_primary_id_on_both_sides_does_not_match(tmp_path, monkeypatch):
    """An empty-string id must not designate a primary address.

    Separated from the null case above because the two guards would otherwise
    mask each other: requiring `email.id` to be a string already covers the
    null pair, and only a blank-on-both-sides record proves the
    `primary_email_address_id` guard is carrying its own weight.
    """
    _install(
        monkeypatch,
        _user(emails=[_email(identifier="")], primary=""),
    )

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified is None


async def test_whitespace_only_primary_address_is_refused_rather_than_raising(
    tmp_path, monkeypatch
):
    """A blank-after-strip address must fail closed, not reach the dataclass.

    Asserted against `_identity_from_user` directly as well as through
    `verify_bearer`. Through the public method alone the two outcomes are
    indistinguishable — the provider try/except converts the dataclass's
    `ValueError` into the same `None` — so only the direct call proves the
    guard refuses rather than relying on an exception for control flow.
    """
    user = _user(emails=[_email(address="   ")])
    _install(monkeypatch, user)

    assert (
        await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")
    ) is None
    assert ClerkHumanIdentityVerifier._identity_from_user(user, SUBJECT) is None


async def test_the_helper_accepts_and_refuses_real_sdk_models():
    """Pin the predicate against the installed SDK, not only against fakes.

    Every other case in this module builds a `SimpleNamespace`, so a pydantic
    or enum change upstream would pass unnoticed. This one round-trips through
    `clerk_backend_api.models.User`.
    """
    from clerk_backend_api.models import User

    from cre_mcp.platform.connection import _clerk_email_is_verified

    def address(status):
        return {
            "object": "email_address",
            "email_address": VICTIM_EMAIL,
            "reserved": False,
            "linked_to": [],
            "created_at": 0,
            "updated_at": 0,
            "id": "email_primary",
            "verification": {
                "object": "verification_otp",
                "status": status,
                "strategy": "email_code",
                "attempts": 1,
                "expire_at": 0,
            },
        }

    def build(status):
        return User.model_validate(
            {
                "id": SUBJECT,
                "object": "user",
                "external_id": None,
                "primary_email_address_id": "email_primary",
                "primary_phone_number_id": None,
                "primary_web3_wallet_id": None,
                "username": None,
                "first_name": "Ada",
                "last_name": "Buyer",
                "has_image": False,
                "public_metadata": {},
                "private_metadata": {},
                "unsafe_metadata": {},
                "email_addresses": [address(status)],
                "phone_numbers": [],
                "web3_wallets": [],
                "passkeys": [],
                "password_enabled": True,
                "two_factor_enabled": False,
                "totp_enabled": False,
                "backup_code_enabled": False,
                "mfa_enabled_at": None,
                "mfa_disabled_at": None,
                "external_accounts": [],
                "saml_accounts": [],
                "enterprise_accounts": [],
                "last_sign_in_at": None,
                "banned": False,
                "locked": False,
                "lockout_expires_in_seconds": None,
                "verification_attempts_remaining": 100,
                "updated_at": 0,
                "created_at": 0,
                "delete_self_enabled": True,
                "create_organization_enabled": True,
                "last_active_at": None,
                "legal_accepted_at": None,
                "deprovisioned": False,
            }
        )

    assert _clerk_email_is_verified(build("verified").email_addresses[0]) is True
    assert _clerk_email_is_verified(build("unverified").email_addresses[0]) is False


async def test_unicode_folding_cannot_collapse_onto_another_provisioned_user(
    tmp_path,
):
    """The Python-side fold and the SQL-side fold must be the same function.

    `str.casefold()` maps `ß` to `ss`, while SQLite's `lower()` is ASCII-only.
    A Clerk-verified address could therefore collapse onto a different
    preprovisioned row and bind to that person's user.
    """
    config = _config(tmp_path)
    repository = PlatformRepository(config)
    victim = await repository.create_user("strasse@corp.test", "Victim")
    assert victim is not None
    store = HumanIdentityStore(config.cache_db_path)

    with pytest.raises(ValueError):
        store.resolve_or_bind(
            VerifiedHumanIdentity("clerk", SUBJECT, "straße@corp.test", "Attacker")
        )

    with sqlite3.connect(config.cache_db_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM platform_human_identities"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("straße@corp.test", "strasse@corp.test"),
        ("ﬁnance@corp.test", "finance@corp.test"),
        ("ſam@corp.test", "sam@corp.test"),
        ("µicro@corp.test", "μicro@corp.test"),
    ],
)
async def test_compatibility_equivalent_addresses_are_different_people(
    tmp_path, first, second
):
    """NFC, not NFKC, and not `casefold()`.

    Each pair is one string away from the other under compatibility
    normalization or case folding, and each is a separately deliverable
    mailbox. They must be two rows, and each Clerk address must reach its own.

    Only the `ß` pair was pinned before; switching the canonical form to NFKC
    passed the entire repository, which would have restored the cross-account
    bind for ligature, long-s, and micro-sign addresses.
    """
    config = _config(tmp_path)
    repository = PlatformRepository(config)
    one = await repository.create_user(first, "First")
    two = await repository.create_user(second, "Second")
    assert one is not None and two is not None and one.id != two.id

    identities = HumanIdentityStore(config.cache_db_path)
    assert (
        identities.resolve_or_bind(
            VerifiedHumanIdentity("clerk", "user_first", first, "First")
        )
        == one.id
    )
    assert (
        identities.resolve_or_bind(
            VerifiedHumanIdentity("clerk", "user_second", second, "Second")
        )
        == two.id
    )


@pytest.mark.parametrize(
    ("stored", "reported"),
    [
        ("Straße@corp.test", "straße@corp.test"),
        (unicodedata.normalize("NFD", "josé@corp.test"), "josé@corp.test"),
        ("ΓΙΩΡΓΟΣ@corp.test", "γιωργος@corp.test"),
    ],
)
async def test_create_user_applies_the_canonical_form_not_merely_some_fold(
    tmp_path, stored, reported
):
    """`create_user` was pinned only for "some normalization happens".

    Substituting `.casefold()` or a bare `.lower()` there passed the whole
    repository, so the round-two cross-account bind could return through this
    writer. These addresses distinguish the canonical form from both.
    """
    config = _config(tmp_path)
    user = await PlatformRepository(config).create_user(stored, "Owner")
    assert user is not None

    resolved = HumanIdentityStore(config.cache_db_path).resolve_or_bind(
        VerifiedHumanIdentity("clerk", SUBJECT, reported, "Owner")
    )
    assert resolved == user.id


@pytest.mark.parametrize(
    ("stored", "reported"),
    [
        ("Straße@corp.test", "straße@corp.test"),
        (unicodedata.normalize("NFD", "josé@corp.test"), "josé@corp.test"),
        ("ΓΙΩΡΓΟΣ@corp.test", "γιωργος@corp.test"),
    ],
)
async def test_update_user_applies_the_canonical_form_not_merely_some_fold(
    tmp_path, stored, reported
):
    """The same distinction on the third write site."""
    config = _config(tmp_path)
    repository = PlatformRepository(config)
    user = await repository.create_user("before@corp.test", "Owner")
    assert user is not None
    assert await repository.update_user(user.id, email=stored) is not None

    resolved = HumanIdentityStore(config.cache_db_path).resolve_or_bind(
        VerifiedHumanIdentity("clerk", SUBJECT, reported, "Owner")
    )
    assert resolved == user.id


async def test_identifiers_are_compared_by_value_not_by_object(
    tmp_path, monkeypatch
):
    """Built at runtime so the two sides cannot be the same interned object.

    Every other fixture writes the same literal on both sides, so `==` and `is`
    were indistinguishable and swapping either comparison to `is` passed the
    whole repository — while in production, where the two strings are parsed
    separately, it would refuse every sign-in.
    """
    subject = "".join("user_clerk_attacker")
    primary_id = "".join("email_primary")
    # The premise of this pin: equal in value, distinct as objects.
    assert subject == SUBJECT and id(subject) != id(SUBJECT)
    assert primary_id == "email_primary" and id(primary_id) != id("email_primary")

    _install(
        monkeypatch,
        _user(emails=[_email(identifier=primary_id)], user_id=subject),
        subject=SUBJECT,
    )

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified == VerifiedHumanIdentity("clerk", SUBJECT, VICTIM_EMAIL, "Ada Buyer")


async def test_a_record_without_deprovisioned_is_still_accepted(tmp_path, monkeypatch):
    """The `getattr` default, not the `bool()` wrapper, carries the claim.

    An SDK that predates the field must behave as it did before the field
    existed. Dropping the default denies every such record; the ledger listed
    only the no-op `bool()` half of this expression.
    """
    user = _user(emails=[_email()])
    del user.deprovisioned
    _install(monkeypatch, user)

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified == VerifiedHumanIdentity("clerk", SUBJECT, VICTIM_EMAIL, "Ada Buyer")


@pytest.mark.parametrize("missing", ["verification", "id", "email_address"])
async def test_an_email_record_missing_a_field_is_refused_not_an_error(missing):
    """Requirements 1 and 5 name the *absent* case, so it is exercised.

    Through the direct call, where the provider `try` cannot convert an
    `AttributeError` into the same `None` and hide the difference.
    """
    email = _email()
    delattr(email, missing)
    user = _user(emails=[email])

    assert ClerkHumanIdentityVerifier._identity_from_user(user, SUBJECT) is None


@pytest.mark.parametrize("missing", ["id", "primary_email_address_id"])
async def test_a_user_record_missing_a_field_is_refused_not_an_error(missing):
    """The same for the user record's own optional fields."""
    user = _user(emails=[_email()])
    delattr(user, missing)

    assert ClerkHumanIdentityVerifier._identity_from_user(user, SUBJECT) is None


@pytest.mark.parametrize("base", ["Ϊ", "Ϋ", "ᾼ", "ῌ", "ῼ"])
@pytest.mark.parametrize("mark", ["̀", "́", "͂"])
async def test_the_canonical_form_composes_after_folding_not_before(base, mark):
    """NFC must run last, and this is the only input class that can tell.

    Normalizing before lowering leaves these outputs un-composed, so the
    function would no longer be NFC-stable — the property the contract asserts.
    Both orders are self-consistent across the write and the read, so there is
    no cross-account bind either way; this pins the stated property rather than
    a security boundary.
    """
    from cre_mcp.platform.models import normalize_platform_email

    folded = normalize_platform_email(f"a{base}{mark}@corp.test")

    assert folded == unicodedata.normalize("NFC", folded)


async def test_the_stored_form_is_composed_not_decomposed(tmp_path):
    """NFC, and specifically not NFD.

    Both normalizations are self-consistent across the write and the read, so
    only inspecting the stored bytes can tell them apart — and the canonical
    form is asserted to be NFC-stable.
    """
    config = _config(tmp_path)
    user = await PlatformRepository(config).create_user(
        unicodedata.normalize("NFD", "José@corp.test"), "José"
    )
    assert user is not None

    with sqlite3.connect(config.cache_db_path) as connection:
        stored = connection.execute(
            "SELECT email FROM platform_users WHERE id=?", (user.id,)
        ).fetchone()[0]

    assert stored == unicodedata.normalize("NFC", "josé@corp.test")
    assert stored == unicodedata.normalize("NFC", stored)


@pytest.mark.parametrize("pad", [" ", "\t", "\n", "\r\n", " \t\n "])
async def test_every_kind_of_padding_is_trimmed(tmp_path, pad):
    """`.strip()` with no argument, not `.strip(" ")`.

    The earlier padding pin used spaces only, so narrowing the strip to spaces
    passed the whole repository.
    """
    config = _config(tmp_path)
    user = await PlatformRepository(config).create_user(
        f"{pad}Padded{pad}@corp.test".replace(f"{pad}@", "@"), "P"
    )
    assert user is not None

    resolved = HumanIdentityStore(config.cache_db_path).resolve_or_bind(
        VerifiedHumanIdentity("clerk", SUBJECT, f"{pad}padded@corp.test{pad}", "P")
    )
    assert resolved == user.id


async def test_a_padded_address_is_trimmed_on_both_sides(tmp_path):
    """`.strip()` in the canonical form and in the adapter masked each other.

    `VerifiedHumanIdentity` rejects a blank address but does not trim one, so a
    padded value from any verifier reaches the lookup. Removing both strips
    left the whole repository green.
    """
    config = _config(tmp_path)
    user = await PlatformRepository(config).create_user("  Padded@corp.test  ", "P")
    assert user is not None

    resolved = HumanIdentityStore(config.cache_db_path).resolve_or_bind(
        VerifiedHumanIdentity("clerk", SUBJECT, "  padded@corp.test  ", "P")
    )
    assert resolved == user.id


async def test_the_primary_address_is_found_wherever_it_sits(tmp_path, monkeypatch):
    """The scan must search the collection, not assume the first entry.

    Truncating it to the first element passed every other pin.
    """
    _install(
        monkeypatch,
        _user(
            emails=[
                _email(
                    address="secondary@corp.test",
                    identifier="email_secondary",
                    status="unverified",
                ),
                _email(),
            ]
        ),
    )

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified == VerifiedHumanIdentity("clerk", SUBJECT, VICTIM_EMAIL, "Ada Buyer")


async def test_non_ascii_uppercase_address_stays_reachable(tmp_path):
    """The same defect denied legitimate users; that direction is pinned too.

    SQLite's `lower()` leaves `Ü` alone, so a row stored with it was
    unreachable through a `casefold()`-normalized lookup — a permanent 403 for
    that customer.
    """
    config = _config(tmp_path)
    repository = PlatformRepository(config)
    user = await repository.create_user("Ünter@corp.test", "Ünter")
    assert user is not None
    store = HumanIdentityStore(config.cache_db_path)

    resolved = store.resolve_or_bind(
        VerifiedHumanIdentity("clerk", SUBJECT, "ÜNTER@corp.test", "Ünter")
    )

    assert resolved == user.id


async def test_case_variant_rows_cannot_be_created_at_all(tmp_path):
    """The ambiguity is prevented at the write, not resolved at the read.

    `email` is UNIQUE under BINARY collation, so two case variants used to
    coexist and an unordered read picked one by rowid. Now both normalize to
    the same stored value and the second write simply loses to the constraint.
    """
    config = _config(tmp_path)
    repository = PlatformRepository(config)

    assert await repository.create_user("buyer@corp.test", "Lower") is not None
    assert await repository.create_user("BUYER@corp.test", "Upper") is None


async def _provisioning_operator(config) -> tuple[AdminControlStore, int]:
    """Seed one internal platform admin so provisioning can be exercised.

    Production bootstrap of internal authority is deliberately out of band, so
    the row is written directly, the same way the existing admin tests do it.
    """
    staff = await PlatformRepository(config).create_user("staff@medawarcre.test", "Staff")
    assert staff is not None
    now = "2026-08-06T12:00:00+00:00"
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_internal_admins (
                user_id INTEGER PRIMARY KEY,
                role TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES platform_users(id) ON DELETE CASCADE,
                CHECK(role IN ('platform_admin','support')),
                CHECK(active IN (0,1))
            )
            """
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO platform_internal_admins
                (user_id,role,active,created_at,updated_at)
            VALUES (?,?,?,?,?)
            """,
            (staff.id, "platform_admin", 1, now, now),
        )
    return AdminControlStore(config.cache_db_path), staff.id


async def test_admin_provisioning_and_the_identity_lookup_share_one_fold(
    tmp_path,
):
    """The write side and the read side must be the same function.

    This is the defect both round-two reviews found: the reader was hardened to
    an ASCII-only fold while `provision_workspace` still stored
    `.casefold()`. An operator provisioning `Straße@corp.test` wrote a row only
    the holder of `strasse@corp.test` could bind to, and the rightful owner was
    locked out permanently.
    """
    config = _config(tmp_path)
    store, actor = await _provisioning_operator(config)
    result = store.provision_workspace(
        actor_user_id=actor,
        name="Strasse Holdings",
        owner_email="Straße@corp.test",
        owner_name="Owner",
        reason_code="initial_provisioning",
        reason="provisioning the launch customer",
    )
    assert result is not None

    identities = HumanIdentityStore(config.cache_db_path)

    # The address the operator actually typed resolves.
    assert identities.resolve_or_bind(
        VerifiedHumanIdentity("clerk", SUBJECT, "Straße@corp.test", "Owner")
    )

    # The ASCII address `casefold()` would have collapsed it onto does not.
    with pytest.raises(ValueError):
        identities.resolve_or_bind(
            VerifiedHumanIdentity(
                "clerk", "user_attacker", "strasse@corp.test", "Attacker"
            )
        )


@pytest.mark.parametrize(
    ("typed", "reported"),
    [
        # Collapsed by `casefold()` on the write side. Every row differs
        # between the typed and the reported spelling — two rows here once did
        # not, which is how the ligature and long-s cases went unexercised.
        ("Straße@corp.test", "straße@corp.test"),
        ("ﬁNANCE@corp.test", "ﬁnance@corp.test"),
        ("ſAM@corp.test", "ſam@corp.test"),
        # Left half-folded by an ASCII-only fold, so the owner could not bind.
        ("MÜLLER@corp.test", "müller@corp.test"),
        ("JOSÉ@corp.test", "josé@corp.test"),
        ("ИВАН@corp.test", "иван@corp.test"),
        ("ΑΝΝΑ@corp.test", "αννα@corp.test"),
        # Mis-keyed onto a different live mailbox by whole-string `lower()`,
        # whose Final_Sigma context rule turns a trailing `Σ` into `ς`. The
        # Greek name above has no sigma, which is why it did not catch this.
        ("ΓΙΩΡΓΟΣ@corp.test", "γιωργοσ@corp.test"),
        ("ΟΔΥΣΣΕΥΣ@corp.test", "οδυσσευσ@corp.test"),
        # The same name in its natural Greek spelling, ending in final sigma.
        # These two rows do NOT discriminate the unification: without it both
        # sides fold to the `ς` form and meet anyway. The rows above, which
        # report the `σ` spelling, are what the unification is pinned by. Kept
        # as positive controls that the natural spelling also works.
        ("ΓΙΩΡΓΟΣ@corp.test", "γιωργος@corp.test"),
        ("ΟΔΥΣΣΕΥΣ@corp.test", "οδυσσευς@corp.test"),
    ],
)
async def test_the_operator_typed_case_and_the_provider_case_reach_one_row(
    tmp_path, typed, reported
):
    """The address as typed and as the provider reports it are one person.

    `typed` and `reported` differ deliberately. An earlier version of this pin
    used the same string on both sides, which is why it passed while the
    ASCII-only fold was silently locking out every owner whose address carried
    a non-ASCII capital.
    """
    config = _config(tmp_path)
    store, actor = await _provisioning_operator(config)
    assert store.provision_workspace(
        actor_user_id=actor,
        name="Launch Customer",
        owner_email=typed,
        owner_name="Owner",
        reason_code="initial_provisioning",
        reason="provisioning the launch customer",
    ) is not None

    assert HumanIdentityStore(config.cache_db_path).resolve_or_bind(
        VerifiedHumanIdentity("clerk", SUBJECT, reported, "Owner")
    )


async def test_update_user_stores_the_canonical_form_too(tmp_path):
    """The third write site, pinned like the other two.

    It has no caller in `src/` today, but the contract states the canonical
    form as a property of the column, and an unpinned write site is how that
    property quietly stops being true.
    """
    config = _config(tmp_path)
    repository = PlatformRepository(config)
    user = await repository.create_user("before@corp.test", "Owner")
    assert user is not None

    assert await repository.update_user(user.id, email="MÜLLER@corp.test") is not None

    resolved = HumanIdentityStore(config.cache_db_path).resolve_or_bind(
        VerifiedHumanIdentity("clerk", SUBJECT, "müller@corp.test", "Owner")
    )
    assert resolved == user.id


async def test_the_connection_route_does_not_forward_the_store_message(tmp_path):
    """The browser must not receive the store's refusal text.

    It is uniform today, so forwarding it leaks nothing right now — but the
    route returning a fixed literal is what keeps that true independently of
    the store, and reverting it to `str(exc)` was previously invisible to every
    test in the repository.
    """
    import httpx

    from cre_mcp.platform.connection import (
        _IDENTITY_NOT_BINDABLE,
        FakeHumanIdentityVerifier,
    )
    from tests.hosted_helpers import create_testing_starlette_app

    config = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "platform.db",
        transport="http",
        human_identity_provider="clerk",
        oauth_issuer="https://mcp.example.test",
        oauth_resource="https://mcp.example.test/mcp",
        connection_url="https://connect.example.test/connect",
        browser_cookie_secure=True,
    )
    # A verified identity for an address no platform user holds, so the bind
    # refuses and the route has a message to either forward or replace.
    app = create_testing_starlette_app(
        config,
        human_identity_verifier=FakeHumanIdentityVerifier(
            {
                "token": VerifiedHumanIdentity(
                    "clerk", SUBJECT, "nobody@corp.test", "Nobody"
                )
            }
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://mcp.example.test",
    ) as client:
        response = await client.post(
            "/v1/browser/session",
            headers={
                "origin": "https://connect.example.test",
                "host": "mcp.example.test",
                "authorization": "Bearer token",
            },
        )

    assert response.status_code == 403
    body = response.json()["error"]
    assert body["code"] == "identity_not_provisioned"
    assert body["message"] != _IDENTITY_NOT_BINDABLE


async def test_the_operations_route_does_not_forward_the_store_message(tmp_path):
    """The same property on the second route that calls `resolve_or_bind`.

    Pinned separately because the connection-route pin cannot see this one:
    reverting only this body to `str(exc)` left the entire repository green.
    """
    import httpx

    from cre_mcp.platform.connection import (
        _IDENTITY_NOT_BINDABLE,
        FakeHumanIdentityVerifier,
    )
    from tests.hosted_helpers import create_testing_starlette_app

    origin = "https://operations.example.test"
    config = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "platform.db",
        oauth_issuer="https://mcp.example.test",
        operations_console_origin=origin,
        browser_cookie_secure=True,
    )
    app = create_testing_starlette_app(
        config,
        human_identity_verifier=FakeHumanIdentityVerifier(
            {
                "token": VerifiedHumanIdentity(
                    "clerk", SUBJECT, "nobody@corp.test", "Nobody"
                )
            }
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://mcp.example.test",
    ) as client:
        response = await client.post(
            "/v1/operations/session",
            headers={
                "origin": origin,
                "host": "mcp.example.test",
                "authorization": "Bearer token",
            },
        )

    assert response.status_code == 403
    body = response.json()["error"]
    assert body["code"] == "identity_not_provisioned"
    assert body["message"] != _IDENTITY_NOT_BINDABLE


async def test_a_row_not_in_canonical_form_is_unreachable_not_approximated(
    tmp_path,
):
    """The lookup is exact equality, not a case-insensitive SQL comparison.

    Written directly, bypassing the writers, to model a row left behind by an
    earlier code path. Matching it approximately is what let the SQL engine's
    own case rules decide who binds — and SQLite's `lower()` is ASCII-only
    while PostgreSQL's is Unicode-aware, so the hosted cutover would silently
    change the answer. An unrecognized row denies instead.
    """
    config = _config(tmp_path)
    repository = PlatformRepository(config)
    assert await repository.create_user("seed@corp.test", "Seed") is not None
    now = "2026-08-06T12:00:00+00:00"
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute(
            "INSERT INTO platform_users(email,name,created_at,updated_at)"
            " VALUES (?,?,?,?)",
            ("Legacy@corp.test", "Legacy", now, now),
        )

    with pytest.raises(ValueError):
        HumanIdentityStore(config.cache_db_path).resolve_or_bind(
            VerifiedHumanIdentity("clerk", SUBJECT, "legacy@corp.test", "Legacy")
        )


async def test_a_trailing_capital_sigma_does_not_key_a_different_mailbox(
    tmp_path,
):
    """The sharpest form of the fold defect, pinned end to end.

    `Σ` is the uppercase of both `σ` and `ς`. Under whole-string `lower()` the
    operator's `ΓΙΩΡΓΟΣ@…` became the canonical form of the `ς` mailbox — a
    different live address — so the real owner was refused and the other holder
    bound. Both must now reach the same row.
    """
    config = _config(tmp_path)
    store, actor = await _provisioning_operator(config)
    assert store.provision_workspace(
        actor_user_id=actor,
        name="Giorgos Holdings",
        owner_email="ΓΙΩΡΓΟΣ@CORP.TEST",
        owner_name="Owner",
        reason_code="initial_provisioning",
        reason="provisioning the launch customer",
    ) is not None

    identities = HumanIdentityStore(config.cache_db_path)
    owner = identities.resolve_or_bind(
        VerifiedHumanIdentity("clerk", SUBJECT, "γιωργοσ@corp.test", "Owner")
    )
    assert owner

    with sqlite3.connect(config.cache_db_path) as connection:
        stored = connection.execute(
            "SELECT email FROM platform_users WHERE id=?", (owner,)
        ).fetchone()[0]
    assert stored == "γιωργοσ@corp.test"


async def test_decomposed_and_composed_spellings_are_one_person(tmp_path):
    """NFD from the provider must reach an NFC row rather than being denied.

    Neither `lower()` on either backend normalizes, so without this the same
    address written two legal ways is two different people.
    """
    config = _config(tmp_path)
    repository = PlatformRepository(config)
    user = await repository.create_user(
        unicodedata.normalize("NFC", "josé@corp.test"), "José"
    )
    assert user is not None

    resolved = HumanIdentityStore(config.cache_db_path).resolve_or_bind(
        VerifiedHumanIdentity(
            "clerk", SUBJECT, unicodedata.normalize("NFD", "josé@corp.test"), "José"
        )
    )

    assert resolved == user.id


async def test_a_user_id_that_merely_claims_equality_is_refused(
    tmp_path, monkeypatch
):
    """The subject guard is `isinstance`-checked like the primary-id guard."""

    _install(monkeypatch, _user(emails=[_email()], user_id=AlwaysEqual()))

    verified = await ClerkHumanIdentityVerifier(_config(tmp_path)).verify_bearer("jwt")

    assert verified is None


async def test_binding_refusals_do_not_distinguish_their_reason(tmp_path):
    """Both refusals carry the same text, so neither can enumerate.

    `api.py` used to echo `str(exc)` as `identity_not_provisioned`, which made
    distinct texts an oracle for whether an address exists but is taken versus
    does not exist at all. That layer now returns a fixed literal; this pin
    keeps the store's own message uniform so the property does not depend on
    the caller continuing to be careful.
    """
    config = _config(tmp_path)
    repository = PlatformRepository(config)
    user = await repository.create_user(VICTIM_EMAIL, "Buyer")
    assert user is not None
    store = HumanIdentityStore(config.cache_db_path)
    store.resolve_or_bind(
        VerifiedHumanIdentity("clerk", "user_first", VICTIM_EMAIL, "Buyer")
    )

    with pytest.raises(ValueError) as absent:
        store.resolve_or_bind(
            VerifiedHumanIdentity("clerk", SUBJECT, "nobody@corp.test", "Nobody")
        )
    with pytest.raises(ValueError) as taken:
        store.resolve_or_bind(
            VerifiedHumanIdentity("clerk", "user_second", VICTIM_EMAIL, "Buyer")
        )

    assert str(absent.value) == str(taken.value)
