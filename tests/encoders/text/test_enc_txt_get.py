from python_thingset.encoders import ThingSetTextEncoder


encoder = ThingSetTextEncoder()


def test_get_root():
    encoded = encoder.encode_get("")
    assert encoded == "thingset ?\n".encode()


def test_get_depth_one():
    encoded = encoder.encode_get("One")
    assert encoded == "thingset ?One\n".encode()


def test_get_depth_two():
    encoded = encoder.encode_get("One/Two")
    assert encoded == "thingset ?One/Two\n".encode()
