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


def test_update_list_of_ints():
    import cbor2

    encoded = encoder.encode_update(0x0, 0x4F, [1, 2, 3])
    expected = bytes([0x07]) + cbor2.dumps(0x0) + cbor2.dumps({0x4F: [1, 2, 3]}, canonical=True)
    assert encoded == expected


def test_update_list_of_floats_uses_f32():
    # Each element should be coerced to float32, matching the scalar
    # behaviour. 3.14 → 0xfa40 48f5c3.
    import cbor2

    encoded = encoder.encode_update(0x0, 0x4F, [3.14, 1.0])
    coerced = [encoder.to_f32(3.14), encoder.to_f32(1.0)]
    expected = bytes([0x07]) + cbor2.dumps(0x0) + cbor2.dumps({0x4F: coerced}, canonical=True)
    assert encoded == expected


def test_update_empty_list():
    import cbor2

    encoded = encoder.encode_update(0x0, 0x4F, [])
    expected = bytes([0x07]) + cbor2.dumps(0x0) + cbor2.dumps({0x4F: []}, canonical=True)
    assert encoded == expected


def test_update_list_of_strings():
    import cbor2

    encoded = encoder.encode_update(0x0, 0x4F, ["a", "b"])
    expected = bytes([0x07]) + cbor2.dumps(0x0) + cbor2.dumps({0x4F: ["a", "b"]}, canonical=True)
    assert encoded == expected
