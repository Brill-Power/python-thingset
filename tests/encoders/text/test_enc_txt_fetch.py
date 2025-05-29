from python_thingset.encoders import ThingSetTextEncoder


encoder = ThingSetTextEncoder()


def test_fetch_root():
    encoded = encoder.encode_fetch("", [])
    assert encoded == "thingset ? null\n".encode()


def test_fetch_root_one_child():
    encoded = encoder.encode_fetch("", ["One"])
    assert encoded == """thingset ? [\\"One\\",]\n""".encode()


def test_fetch_root_two_children():
    encoded = encoder.encode_fetch("", ["One", "Two"])
    assert encoded == """thingset ? [\\"One\\",\\"Two\\",]\n""".encode()


def test_fetch_not_root_one_child():
    encoded = encoder.encode_fetch("NotRoot", ["One"])
    assert encoded == """thingset ?NotRoot [\\"One\\",]\n""".encode()
