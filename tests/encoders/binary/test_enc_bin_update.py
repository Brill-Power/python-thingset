from python_thingset.encoders import ThingSetBinaryEncoder


encoder = ThingSetBinaryEncoder()


def test_update_int():
    encoded = encoder.encode_update(0x0, 0x4F, 1)
    assert encoded == b"\x07\x00\xa1\x18O\x01"


def test_update_float():
    encoded = encoder.encode_update(0x0, 0x4F, 3.14)
    assert encoded == b"\x07\x00\xa1\x18O\xfa@H\xf5\xc3"


def test_update_str():
    encoded = encoder.encode_update(0x0, 0x4F, "hello")
    assert encoded == b"\x07\x00\xa1\x18Oehello"


def test_update_bool_true():
    encoded = encoder.encode_update(0x0, 0x4F, "true")
    assert encoded == b"\x07\x00\xa1\x18O\xf5"


def test_update_bool_false():
    encoded = encoder.encode_update(0x0, 0x4F, "false")
    assert encoded == b"\x07\x00\xa1\x18O\xf4"
