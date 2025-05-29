from python_thingset.encoders import ThingSetBinaryEncoder


encoder = ThingSetBinaryEncoder()


def test_fetch_no_children():
    encoded = encoder.encode_fetch(0xF01, [])
    assert encoded == b"\x05\x19\x0f\x01\xf6"


def test_fetch_one_child():
    encoded = encoder.encode_fetch(0xF, [0xF01])
    assert encoded == b"\x05\x0f\x81\x19\x0f\x01"


def test_fetch_two_children():
    encoded = encoder.encode_fetch(0xF, [0xF01, 0xF02])
    assert encoded == b"\x05\x0f\x82\x19\x0f\x01\x19\x0f\x02"
