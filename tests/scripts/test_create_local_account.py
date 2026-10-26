"""Local provisioning cannot overwrite accounts, grant roles or partly commit."""

from io import StringIO

import pytest

from app.domain.auth import PasswordCredential
from app.domain.product_access import ProductRole
from app.repositories.provider import create_memory_provider
from app.services.passwords import PasswordHasher
from app.services.repository_scope import create_memory_repository_scope
from scripts.create_local_account import create_account, read_password_hash
from tests.repositories.contracts.factories import run_async


def test_local_account_creation_and_duplicate_refusal() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        scope = create_memory_repository_scope(provider)
        hasher = PasswordHasher(iterations=100_000)
        password_hash = hasher.hash_password("fixture-password-only")
        user_id = await create_account(
            scope, email="NEW@example.test", password_hash=password_hash
        )
        user = await provider.users.get_by_id(user_id)
        credential = await provider.password_credentials.get_by_user_id(user_id)
        assert user and user.email == "new@example.test"
        assert user.product_role is ProductRole.USER
        assert credential and hasher.verify(
            "fixture-password-only", credential.password_hash
        )
        assert await provider.memberships.list_for_user(user_id) == ()
        with pytest.raises(ValueError, match="already exists"):
            await create_account(scope, email=user.email, password_hash="different")
        assert await provider.password_credentials.get_by_user_id(user_id) == credential

    run_async(scenario())


def test_failed_credential_write_rolls_back_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        provider = create_memory_provider()

        async def fail(
            self: object, credential: PasswordCredential
        ) -> PasswordCredential:
            raise RuntimeError("Injected failure")

        monkeypatch.setattr(type(provider.password_credentials), "set_for_user", fail)
        with pytest.raises(RuntimeError, match="Injected"):
            await create_account(
                create_memory_repository_scope(provider),
                email="new@example.test",
                password_hash="fixture-hash",
            )
        assert await provider.users.get_by_email("new@example.test") is None

    run_async(scenario())


def test_password_cannot_be_read_from_redirected_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.stdin", StringIO("do-not-read"))
    with pytest.raises(ValueError, match="interactive"):
        read_password_hash()


def test_password_mismatch_retries_without_printing_secret(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class PrivateTerminal(StringIO):
        def isatty(self) -> bool:
            return True

    entries = iter(
        (
            "wrong-first-value",
            "mismatched-value",
            "fixture-secret-value",
            "fixture-secret-value",
        )
    )
    monkeypatch.setattr("sys.stdin", PrivateTerminal())
    monkeypatch.setattr("getpass.getpass", lambda prompt: next(entries))
    password_hash = read_password_hash()
    assert PasswordHasher(iterations=100_000).verify(
        "fixture-secret-value", password_hash
    )
    output = capsys.readouterr()
    assert "do not match" in output.out
    assert "fixture-secret-value" not in output.out + output.err
    assert "wrong-first-value" not in output.out + output.err
