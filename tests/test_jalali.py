from datetime import datetime, timezone
from pathlib import Path

import pytest

from hitl.jalali import to_jalali


def test_to_jalali_from_utc_datetime() -> None:
    dt = datetime(2026, 3, 16, 10, 25, tzinfo=timezone.utc)
    value = to_jalali(dt)
    assert len(value) == 16
    assert value[2] == "-"
    assert value[5] == "-"
    assert value[10] == " "


def test_to_jalali_from_iso_string() -> None:
    value = to_jalali("2026-06-20T05:49:39Z")
    assert " " in value
    assert "T" not in value


def test_to_jalali_default_now() -> None:
    value = to_jalali()
    parts = value.split(" ")
    assert len(parts) == 2
    assert len(parts[0].split("-")) == 3
