from uuid import UUID

import pytest

from scripts.change_canonical_product_category import approval_phrase, main, parse_args

TENANT_ID = UUID("78000000-0000-4000-8000-000000000001")
PRODUCT_ID = UUID("78000000-0000-4000-8000-000000000002")


def test_category_cli_is_preview_by_default() -> None:
    arguments = parse_args(
        [
            "--tenant-id",
            str(TENANT_ID),
            "--product-id",
            str(PRODUCT_ID),
            "--expected-version",
            "1",
            "--expected-category",
            "keys",
            "--category",
            "subscriptions",
        ]
    )
    assert arguments.apply is False
    assert arguments.tenant_id == TENANT_ID
    assert arguments.product_id == PRODUCT_ID


@pytest.mark.parametrize("database_url", ["", "invalid-secret-url"])
def test_category_cli_rejects_bad_configuration_safely(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("EPIC23_CATALOG_REVIEW_DATABASE_URL", database_url)
    assert (
        main(
            [
                "--tenant-id",
                str(TENANT_ID),
                "--product-id",
                str(PRODUCT_ID),
                "--expected-version",
                "1",
                "--expected-category",
                "keys",
                "--category",
                "subscriptions",
            ]
        )
        == 2
    )
    assert capsys.readouterr().out == (
        "FAILED: invalid isolated review database configuration.\n"
    )


def test_category_approval_binds_expected_state() -> None:
    phrase = approval_phrase(TENANT_ID, PRODUCT_ID, 1, "keys", "subscriptions")
    assert str(TENANT_ID) in phrase
    assert str(PRODUCT_ID) in phrase
    assert phrase != approval_phrase(TENANT_ID, PRODUCT_ID, 2, "keys", "subscriptions")
    assert phrase != approval_phrase(TENANT_ID, PRODUCT_ID, 1, "keys", "accounts")


def test_category_cli_rejects_unknown_category() -> None:
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--tenant-id",
                str(TENANT_ID),
                "--product-id",
                str(PRODUCT_ID),
                "--expected-version",
                "1",
                "--expected-category",
                "keys",
                "--category",
                "unknown",
            ]
        )
