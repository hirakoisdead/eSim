"""Regression tests for Convert._star_encode.

The old inline encoder used ``path.index(c)`` which returns the FIRST
occurrence, so a path with a repeated uppercase letter got the wrong
insertion offset and was corrupted. The helper does a single linear pass.
"""
from kicadtoNgspice.Convert import _star_encode


def _decode(encoded):
    """Inverse of the ``*C**`` framing, for round-trip checks."""
    out = []
    i = 0
    while i < len(encoded):
        if encoded[i] == '*' and i + 3 < len(encoded) + 1 \
                and encoded[i + 2:i + 4] == '**':
            out.append(encoded[i + 1])
            i += 4
        else:
            out.append(encoded[i])
            i += 1
    return ''.join(out)


def test_no_uppercase_unchanged():
    assert _star_encode("/home/user/adc.hex") == "/home/user/adc.hex"


def test_single_uppercase_framed():
    assert _star_encode("Adc") == "*A**dc"


def test_repeated_uppercase_not_corrupted():
    # Each uppercase char is independently framed *C**; concatenation of two
    # frames yields three asterisks between them. The point is that a REPEATED
    # letter no longer mis-offsets (the old index()-based code corrupted here).
    assert _star_encode("ADC") == "*A***D***C**"
    assert _star_encode("AA") == "*A***A**"


def test_round_trip_repeated_uppercase():
    for path in ("/home/U/ADC/ADC.hex", "AAAA", "MixEDCase", "abcABCabc"):
        assert _decode(_star_encode(path)) == path
