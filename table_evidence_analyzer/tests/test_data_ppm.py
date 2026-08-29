from __future__ import annotations

from table_evidence_analyzer.data import _ppm_tokens


def test_ppm_parser_preserves_a_whitespace_valued_first_pixel_channel() -> None:
    raw = b"P6\n1 1\n255\n" + bytes((32, 64, 96))

    width, height, maximum, offset = _ppm_tokens(raw)

    assert (width, height, maximum) == (1, 1, 255)
    assert raw[offset:] == bytes((32, 64, 96))
