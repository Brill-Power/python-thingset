from python_thingset.encoders import ThingSetBinaryEncoder


encoder = ThingSetBinaryEncoder()


def test_enc_get_paths():
    encoded = encoder.encode_get_path(0xF)
    assert encoded == b"\x05\x17\x81\x0f"
