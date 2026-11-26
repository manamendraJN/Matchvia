import pytest

from bookings.reference import ALPHABET, generate_reference, normalise_reference


def test_references_are_six_unambiguous_characters():
    for _ in range(200):
        code = generate_reference()
        assert len(code) == 6
        assert set(code) <= set(ALPHABET)
    assert not set("0O1I") & set(ALPHABET)


@pytest.mark.parametrize("typed", ["MV-7K3P9Q", "mv-7k3p9q", "MV7K3P9Q", " 7k3p9q ", "MV 7K3 P9Q"])
def test_normalise_reference(typed):
    assert normalise_reference(typed) == "7K3P9Q"
