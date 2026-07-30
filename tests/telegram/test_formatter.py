from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from app.telegram.errors import (
    TelegramFormattingError,
    TelegramFormattingErrorCode,
)
from app.telegram.formatter import (
    TELEGRAM_MESSAGE_LIMIT,
    TelegramFormattingRequest,
    TelegramPlainTextFormatter,
)

PUBLICATION_ID = UUID("00000000-0000-0000-0000-000000001401")
DESTINATION_ID = "-1001234567890"


def make_request(
    generated_text: str,
    *,
    channel: str = "telegram",
    destination_id: str = DESTINATION_ID,
    correlation_id: str = "publication-1401",
    source_url: str | None = None,
    footer: str | None = None,
) -> TelegramFormattingRequest:
    """Create one deterministic formatter request."""
    return TelegramFormattingRequest(
        publication_id=PUBLICATION_ID,
        channel=channel,
        destination_id=destination_id,
        generated_text=generated_text,
        correlation_id=correlation_id,
        source_url=source_url,
        footer=footer,
    )


def test_formats_standard_price_drop_as_plain_text() -> None:
    request = make_request(
        "Minecraft Premium\r\nPlayerok\r\n990 RUB -> 790 RUB\r\n"
        "Скидка 20.20%\r\n\r\nЦена стала выгоднее.  ",
        source_url="https://example.com/product",
        footer="MediaEngine",
    )

    message = TelegramPlainTextFormatter().format(request)

    assert message.rendered_text == (
        "Minecraft Premium\nPlayerok\n990 RUB -> 790 RUB\n"
        "Скидка 20.20%\n\nЦена стала выгоднее.\n\n"
        "https://example.com/product\n\nMediaEngine"
    )
    assert message.parse_mode is None
    assert message.disable_web_page_preview is True


@pytest.mark.parametrize(
    "content",
    (
        "商品 Minecraft Премиум",
        "Кириллица и цена 790 ₽",
        "Цена снижена 🎮🔥",
        "Комментарий\nиз нескольких\nстрок",
        "Цена 790.0000000000000001 RUB",
        "Нулевая цена 0 RUB остаётся обычным текстом",
    ),
)
def test_preserves_unicode_currency_and_generated_plain_text(content: str) -> None:
    message = TelegramPlainTextFormatter().format(make_request(content))

    assert message.rendered_text == content


def test_source_url_is_optional() -> None:
    message = TelegramPlainTextFormatter().format(make_request("Ready"))

    assert message.rendered_text == "Ready"


@pytest.mark.parametrize(
    "source_url",
    (
        "",
        "example.com/item",
        "ftp://example.com/item",
        "https://user:password@example.com/item",
        " https://example.com/item",
        "https://example.com/item\nnext",
    ),
)
def test_rejects_invalid_source_url(source_url: str) -> None:
    with pytest.raises(TelegramFormattingError) as captured:
        TelegramPlainTextFormatter().format(
            make_request("Ready", source_url=source_url)
        )

    assert captured.value.code is TelegramFormattingErrorCode.INVALID_SOURCE_URL


def test_normalizes_line_endings_tabs_controls_and_outer_whitespace() -> None:
    request = make_request("\n\tTitle\x00  \r\nBody\tvalue\r\n\r\n")

    message = TelegramPlainTextFormatter().format(request)

    assert message.rendered_text == "    Title\nBody    value"


@pytest.mark.parametrize("content", ("", "   ", "\r\n\t\r\n", "\x00"))
def test_rejects_empty_normalized_content(content: str) -> None:
    with pytest.raises(TelegramFormattingError) as captured:
        TelegramPlainTextFormatter().format(make_request(content))

    assert captured.value.code is TelegramFormattingErrorCode.EMPTY_CONTENT


def test_accepts_exactly_4096_characters() -> None:
    content = "x" * TELEGRAM_MESSAGE_LIMIT

    message = TelegramPlainTextFormatter().format(make_request(content))

    assert message.rendered_text == content
    assert len(message.rendered_text) == TELEGRAM_MESSAGE_LIMIT


def test_rejects_4097_characters_without_truncation_or_splitting() -> None:
    content = "x" * (TELEGRAM_MESSAGE_LIMIT + 1)

    with pytest.raises(TelegramFormattingError) as captured:
        TelegramPlainTextFormatter().format(make_request(content))

    assert captured.value.code is TelegramFormattingErrorCode.MESSAGE_TOO_LONG
    assert content.endswith("x")


@pytest.mark.parametrize(
    "content",
    (
        "<b>Not HTML</b>",
        "*Not Markdown* _still plain_ [link](https://example.com)",
        "/start remains generated plain text",
    ),
)
def test_markup_and_commands_remain_unmodified_plain_text(content: str) -> None:
    message = TelegramPlainTextFormatter().format(make_request(content))

    assert message.rendered_text == content
    assert message.parse_mode is None


def test_output_is_deterministic_across_repeated_runs() -> None:
    formatter = TelegramPlainTextFormatter()
    request = make_request(
        "Title\r\n\r\nComment",
        source_url="https://example.com/item",
        footer="MediaEngine",
    )

    outputs = tuple(formatter.format(request) for _ in range(5))

    assert all(output == outputs[0] for output in outputs)


@pytest.mark.parametrize("channel", ("preview", "email", "", "telegram-post"))
def test_rejects_unsupported_channel(channel: str) -> None:
    with pytest.raises(TelegramFormattingError) as captured:
        TelegramPlainTextFormatter().format(make_request("Ready", channel=channel))

    assert captured.value.code is TelegramFormattingErrorCode.UNSUPPORTED_CHANNEL


@pytest.mark.parametrize(
    "destination",
    ("", "0", "+123", "@channel", "-0", "00123", "123 456"),
)
def test_rejects_non_numeric_or_zero_destination(destination: str) -> None:
    with pytest.raises(TelegramFormattingError) as captured:
        TelegramPlainTextFormatter().format(
            make_request("Ready", destination_id=destination)
        )

    assert captured.value.code is TelegramFormattingErrorCode.INVALID_DESTINATION


def test_rejects_missing_correlation_id() -> None:
    with pytest.raises(TelegramFormattingError) as captured:
        TelegramPlainTextFormatter().format(make_request("Ready", correlation_id="  "))

    assert captured.value.code is TelegramFormattingErrorCode.MISSING_CORRELATION_ID


def test_rejects_empty_explicit_footer() -> None:
    with pytest.raises(TelegramFormattingError) as captured:
        TelegramPlainTextFormatter().format(make_request("Ready", footer=" \n "))

    assert captured.value.code is TelegramFormattingErrorCode.EMPTY_FOOTER


def test_formatter_request_and_output_are_immutable() -> None:
    request = make_request("Ready")
    message = TelegramPlainTextFormatter().format(request)

    with pytest.raises(FrozenInstanceError):
        request.generated_text = "Changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        message.rendered_text = "Changed"  # type: ignore[misc]


def test_custom_limit_must_not_exceed_telegram_limit() -> None:
    with pytest.raises(ValueError, match="between 1 and 4096"):
        TelegramPlainTextFormatter(maximum_length=4097)
