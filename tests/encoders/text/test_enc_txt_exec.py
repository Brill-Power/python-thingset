from python_thingset.encoders import ThingSetTextEncoder


encoder = ThingSetTextEncoder()


def test_exec_no_args():
    encoded = encoder.encode_exec("Func", [])
    assert encoded == "thingset !Func []\n".encode()


def test_exec_int_arg():
    encoded = encoder.encode_exec("Func", [7])
    assert encoded == "thingset !Func [7,]\n".encode()


def test_exec_float_arg():
    encoded = encoder.encode_exec("Func", [3.14])
    assert encoded == "thingset !Func [3.14,]\n".encode()


def test_exec_str_arg():
    encoded = encoder.encode_exec("Func", ["a_text-arg"])
    assert encoded == """thingset !Func [\\"a_text-arg\\",]\n""".encode()


def test_exec_one_of_each_arg():
    encoded = encoder.encode_exec("Func", [1, 2.34, "moretext"])
    assert encoded == """thingset !Func [1,2.34,\\"moretext\\",]\n""".encode()
