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


def test_update_value_scalar_int_unwrapped():
    # New API: scalar value passed directly (no list wrapper)
    encoded = encoder.encode_update(None, "Value", 1)
    assert encoded == """thingset = {\\"Value\\":1}\n""".encode()


def test_update_value_list_of_ints():
    encoded = encoder.encode_update(None, "Value", [1, 2, 3])
    assert encoded == """thingset = {\\"Value\\":[1,2,3]}\n""".encode()


def test_update_value_list_of_floats():
    encoded = encoder.encode_update(None, "Value", [1.0, 2.5, 3.14])
    assert encoded == """thingset = {\\"Value\\":[1.0,2.5,3.14]}\n""".encode()


def test_update_value_list_of_strings():
    encoded = encoder.encode_update(None, "Value", ["a", "b"])
    assert encoded == """thingset = {\\"Value\\":[\\"a\\",\\"b\\"]}\n""".encode()


def test_update_value_empty_list():
    encoded = encoder.encode_update(None, "Value", [])
    assert encoded == """thingset = {\\"Value\\":[]}\n""".encode()


def test_update_value_bool_true():
    encoded = encoder.encode_update(None, "Value", True)
    assert encoded == """thingset = {\\"Value\\":true}\n""".encode()


def test_update_value_list_at_depth_one():
    encoded = encoder.encode_update(None, "One/Value", [1, 2, 3])
    assert encoded == """thingset =One {\\"Value\\":[1,2,3]}\n""".encode()
