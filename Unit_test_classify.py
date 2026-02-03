
from src.dmn.classify import classify
from src.models import Address

def test_standard():
    addr = Address(streetNumber="120", streetName="Main St", direction="E")
    res = classify(addr)
    assert res.addressType == "Standard"
    assert res.variant is None

def test_nonstandard_pobox():
    addr = Address(poBox="PO BOX 451", city="X", state="Y", zip="12345")
    res = classify(addr)
    assert res.addressType == "Non-standard"

def test_incomplete_missing_number():
    addr = Address(streetName="Oak Ridge", city="X", state="Y", zip="12345")
    res = classify(addr)
    assert res.addressType == "Incomplete"
    assert res.variant == "MissingStreetNumber"
