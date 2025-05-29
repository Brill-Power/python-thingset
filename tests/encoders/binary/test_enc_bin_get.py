from python_thingset.encoders import ThingSetBinaryEncoder


encoder = ThingSetBinaryEncoder()


def test_get():
    encoded = encoder.encode_get(0xF01)
    assert encoded == b"\x01\x19\x0f\x01"
