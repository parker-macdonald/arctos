import pytest

from app.error_values import Err, Null, Ok, Some, option


def test_option_ok_or_some():
    res = Some(123).ok_or("nope")
    match res:
        case Ok(v):
            assert v == 123
        case Err(_):
            raise AssertionError("Expected Ok")


def test_option_ok_or_null():
    res = Null().ok_or("nope")
    match res:
        case Err(e):
            assert e == "nope"
        case Ok(_):
            raise AssertionError("Expected Err")


def test_option_ok_or_else_is_lazy():
    called = False

    def mk():
        nonlocal called
        called = True
        return "err"

    res = Some("x").ok_or_else(mk)
    assert called is False
    assert res.unwrap() == "x"

    res2 = Null().ok_or_else(mk)
    assert called is True
    assert res2.unwrap_err() == "err"


def test_option_helper():
    assert option(None).is_null()
    assert option(5).unwrap() == 5
