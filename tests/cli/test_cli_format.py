"""Pure-function tests for the CLI's output formatter.

The rule encoded in ``_fmt``: dict keys that are ints are rendered as
uppercase hex (they're ThingSet IDs by convention); everything else —
values, list elements, string keys — goes through the plain Python
repr.
"""

from python_thingset.cli import _fmt


def test_scalar_int_renders_decimal():
    # Value-position ints are data, not IDs
    assert _fmt(42) == "42"


def test_scalar_float_rendered_via_repr():
    assert _fmt(3.14) == "3.14"


def test_scalar_string_quoted():
    assert _fmt("native_sim") == "'native_sim'"


def test_scalar_bool_preserved():
    assert _fmt(True) == "True"
    assert _fmt(False) == "False"


def test_list_of_ints_is_decimal():
    # Firmware version tuple — should stay decimal, not become hex
    assert _fmt([0, 48, 0, 1]) == "[0, 48, 0, 1]"


def test_list_of_strings():
    assert _fmt(["a", "b", "c"]) == "['a', 'b', 'c']"


def test_empty_list():
    assert _fmt([]) == "[]"


def test_empty_dict():
    assert _fmt({}) == "{}"


def test_dict_int_keys_are_hex():
    assert _fmt({0x0F01: "commit", 0x0F03: "native_sim"}) == (
        "{0xF01: 'commit', 0xF03: 'native_sim'}"
    )


def test_dict_string_keys_unchanged():
    assert _fmt({"name": "value"}) == "{'name': 'value'}"


def test_dict_mixed_key_types():
    assert _fmt({0x10: "hex", "s": "str"}) == "{0x10: 'hex', 's': 'str'}"


def test_dict_bool_key_not_hexified():
    # bool is a subclass of int in Python, but False/True aren't IDs
    assert "False" in _fmt({False: "x"})
    assert "0x0" not in _fmt({False: "x"})


def test_dict_value_list_stays_decimal():
    # The firmware-version case: dict value is a list of data ints
    assert _fmt({0x0F05: [0, 48, 0, 1]}) == "{0xF05: [0, 48, 0, 1]}"


def test_nested_dict_inner_keys_also_hex():
    # Record entries: inner dict keys are still field IDs
    result = _fmt({0x0009: [{0x6E: 123, 0x6F: 456}]})
    assert result == "{0x9: [{0x6E: 123, 0x6F: 456}]}"


def test_large_id_uses_full_uppercase():
    assert _fmt({0xBADB1B0000000001: 1}) == "{0xBADB1B0000000001: 1}"


def test_negative_int_value_stays_decimal():
    assert _fmt({0x100: -5}) == "{0x100: -5}"


def test_names_map_decorates_dict_keys():
    names = {0x509: ("sDFUOverride", "bool"), 0x502: ("sNetworkMaxLogLevel", "u32")}
    assert _fmt({0x509: False, 0x502: 3}, names) == (
        "{0x509 sDFUOverride: False, 0x502 sNetworkMaxLogLevel: 3}"
    )


def test_names_map_partial_coverage():
    # Unknown id falls back to bare hex
    names = {0x509: ("sDFUOverride", "bool")}
    assert _fmt({0x509: True, 0x999: "x"}, names) == (
        "{0x509 sDFUOverride: True, 0x999: 'x'}"
    )


def test_names_map_empty_name_not_appended():
    names = {0x123: ("", "u32")}
    assert _fmt({0x123: 1}, names) == "{0x123: 1}"


def test_names_map_propagates_through_nested_containers():
    # Inner dicts inside list values should also pick up the names map
    names = {0x6E: ("cEUI", "u64")}
    assert _fmt({0x9: [{0x6E: 1}]}, names) == "{0x9: [{0x6E cEUI: 1}]}"
