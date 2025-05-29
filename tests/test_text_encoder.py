from python_thingset.encoders import ThingSetTextEncoder


encoder = ThingSetTextEncoder()


def test_root():
    encoded = encoder.encode_get("")
    assert encoded == "thingset ?\n".encode()
