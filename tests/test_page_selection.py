from __future__ import annotations

import pytest

from disclosure_pdf_scaler.batch import PageSelectionError, resolve_pages


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1-5,8,10-12", (1, 2, 3, 4, 5, 8, 10, 11, 12)),
        ("10—12， 1 - 3", (1, 2, 3, 10, 11, 12)),
        ("3,1-3,2", (1, 2, 3)),
    ],
)
def test_custom_page_expression_is_normalized(
    expression: str, expected: tuple[int, ...]
) -> None:
    assert resolve_pages(expression, page_count=12, remove_last=True) == expected


@pytest.mark.parametrize("expression", ["0", "5-2", "13", "1-a", "1-"])
def test_invalid_page_expression_is_rejected(expression: str) -> None:
    with pytest.raises(PageSelectionError):
        resolve_pages(expression, page_count=12, remove_last=True)


def test_empty_expression_follows_remove_last_default() -> None:
    assert resolve_pages("", page_count=4, remove_last=True) == (1, 2, 3)
    assert resolve_pages("", page_count=4, remove_last=False) == (1, 2, 3, 4)
    assert resolve_pages("", page_count=1, remove_last=True) == (1,)
