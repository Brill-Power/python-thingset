from python_thingset.encoders import ThingSetTextEncoder


encoder = ThingSetTextEncoder()


def test_update_value_at_root_int():
    encoded = encoder.encode_update(None, "Value", [1])
    assert encoded == """thingset = {\\"Value\\":1}\n""".encode()


def test_update_value_at_root_float():
    encoded = encoder.encode_update(None, "Value", [3.14])
    assert encoded == """thingset = {\\"Value\\":3.14}\n""".encode()


def test_update_value_at_root_str():
    encoded = encoder.encode_update(None, "Value", ["sometext"])
    assert encoded == """thingset = {\\"Value\\":\\"sometext\\"}\n""".encode()


def test_update_value_at_depth_one():
    encoded = encoder.encode_update(None, "One/Value", [1])
    assert encoded == """thingset =One {\\"Value\\":1}\n""".encode()


def test_update_value_at_depth_two():
    encoded = encoder.encode_update(None, "One/Two/Value", [1])
    assert encoded == """thingset =One/Two {\\"Value\\":1}\n""".encode()
