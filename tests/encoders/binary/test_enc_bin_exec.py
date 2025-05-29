from python_thingset.encoders import ThingSetBinaryEncoder


encoder = ThingSetBinaryEncoder()


def test_exec_no_args():
    encoded = encoder.encode_exec(0xF09, [])
    assert encoded == b"\x02\x19\x0f\t\x80"


def test_exec_one_int():
    encoded = encoder.encode_exec(0xF09, [2])
    assert encoded == b"\x02\x19\x0f\t\x81\x02"


def test_exec_one_float():
    encoded = encoder.encode_exec(0xF09, [3.14])
    assert encoded == b"\x02\x19\x0f\t\x81\xfa@H\xf5\xc3"


def test_exec_one_str():
    encoded = encoder.encode_exec(0xF09, ["hello"])
    assert encoded == b"\x02\x19\x0f\t\x81ehello"


def test_exec_one_bool_true():
    encoded = encoder.encode_exec(0xF09, ["true"])
    assert encoded == b"\x02\x19\x0f\t\x81\xf5"


def test_exec_one_bool_false():
    encoded = encoder.encode_exec(0xF09, ["false"])
    assert encoded == b"\x02\x19\x0f\t\x81\xf4"


def test_exec_multiple_args():
    encoded = encoder.encode_exec(0xF09, ["false", 5, "age", 7.89, "true"])
    assert encoded == b"\x02\x19\x0f\t\x85\xf4\x05cage\xfa@\xfcz\xe1\xf5"
