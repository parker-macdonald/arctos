"""
Errors as values.

for a function that may fail, return Result[type_if_ok, type_if_error].
Result objects must be one of two subtypes: Ok[type_if_ok], or Err[type_if_err].
All Result subclasses implement:
- .unwrap(), which throws an exception if this Result is an Err, or otherwise returns the ok value
- .expect(msg), which is .unwrap but with a custom error message
- .is_ok() and .is_err() which just check and return bools
- .unwrap_err() and .expect_err() which are .unwrap and .expect except the err/ok behavior is flipped

Then there's the .Q() method. This is a shorthand for the common pattern:
```
def my_fun_function() -> Result[T, E]:

    ... # code here

    res = function_that_may_fail()
    actual_result = None
    match res:
        case Ok(val):
            actual_result = val
        case Err(_):
            return res # return the error value

    ... # function continues

```
Where we simply propogate the error back up the call stack.


This file also implements Option, which is like C++ Optional.
Values of the type Option[T] can either be Some[T] or Null.
You can then .unwrap an Option[T], which will raise an exception if
the Option was Null, and return the raw value of type T otherwise.
.Q() operates the same way as with a Result: if Null().Q() is called,
return Null(). Otherwise unwrap.
"""

from abc import ABC, abstractmethod
from typing import Callable, ParamSpec, TypeVar, Generic
from functools import wraps


def option[T](val: T | None) -> "Option[T]":
    """Convert a nullable Python value into an :class:`Option`.

    Args:
        val: Any value, or ``None``.

    Returns:
        :class:`Some` wrapping *val* when *val* is not ``None``,
        otherwise :class:`Null`.
    """
    return Null() if val is None else Some(val)


class Result[T, E](ABC):
    """Abstract base for a two-state computation result.

    A ``Result[T, E]`` is either an :class:`Ok` carrying a success value of
    type *T*, or an :class:`Err` carrying an error value of type *E*.  Callers
    inspect the variant with :meth:`is_ok` / :meth:`is_err` or via
    ``match``-statement destructuring (``Ok(val)`` / ``Err(val)``).
    """

    @abstractmethod
    def is_ok(self) -> bool:
        """Return ``True`` if this result is an :class:`Ok` variant."""

    @abstractmethod
    def is_err(self) -> bool:
        """Return ``True`` if this result is an :class:`Err` variant."""

    @abstractmethod
    def expect(self, msg: str) -> T:
        """Unwrap the success value, raising with *msg* if this is an error.

        Args:
            msg: Message for the ``ValueError`` raised on an :class:`Err`.

        Returns:
            The contained success value.

        Raises:
            ValueError: If this is an :class:`Err` variant.
        """

    @abstractmethod
    def expect_err(self, msg: str) -> E:
        """Unwrap the error value, raising with *msg* if this is a success.

        Args:
            msg: Message for the ``ValueError`` raised on an :class:`Ok`.

        Returns:
            The contained error value.

        Raises:
            ValueError: If this is an :class:`Ok` variant.
        """

    @abstractmethod
    def unwrap(self) -> T:
        """Unwrap the success value, raising if this is an error.

        Returns:
            The contained success value.

        Raises:
            ValueError: If this is an :class:`Err` variant.
        """

    @abstractmethod
    def unwrap_err(self) -> E:
        """Unwrap the error value, raising if this is a success.

        Returns:
            The contained error value.

        Raises:
            ValueError: If this is an :class:`Ok` variant.
        """

    @abstractmethod
    def unwrap_or[U](self, default: U) -> T | U:
        """Return the success value, or *default* if this is an error.

        Args:
            default: Fallback value returned when this is an :class:`Err`.

        Returns:
            The contained success value, or *default*.
        """

    @abstractmethod
    def unwrap_err_or[U](self, default: U) -> E | U:
        """Return the error value, or *default* if this is a success.

        Args:
            default: Fallback value returned when this is an :class:`Ok`.

        Returns:
            The contained error value, or *default*.
        """

    @abstractmethod
    def Q(self) -> T:
        """Propagate errors like Rust's ``?`` operator.

        If this is an :class:`Ok`, unwrap and return the contained value.
        If this is an :class:`Err`, raise :class:`PropagationError` which is
        caught by the :func:`allow_Q` decorator and returned as-is to the
        caller — effectively propagating the error up the call stack.

        Must be used inside a function decorated with :func:`allow_Q`.

        Returns:
            The contained success value.

        Raises:
            PropagationError: Caught by :func:`allow_Q`; do not handle
                manually.
        """


class Option[T](ABC):
    """Abstract base for an optional value.

    An ``Option[T]`` is either :class:`Some` wrapping a value of type *T*,
    or :class:`Null` representing the absence of a value — similar to
    ``std::optional`` in C++ or ``Option`` in Rust/Haskell.
    """

    @abstractmethod
    def unwrap(self) -> T:
        """Return the contained value, raising if this is :class:`Null`.

        Returns:
            The contained value.

        Raises:
            ValueError: If this is a :class:`Null` variant.
        """

    @abstractmethod
    def unwrap_or[U](self, default: U) -> T | U:
        """Return the contained value, or *default* if this is :class:`Null`.

        Args:
            default: Fallback value returned for :class:`Null`.

        Returns:
            The contained value, or *default*.
        """

    @abstractmethod
    def expect(self, msg: str) -> T:
        """Return the contained value, raising with *msg* if this is :class:`Null`.

        Args:
            msg: Message for the ``ValueError`` raised on :class:`Null`.

        Returns:
            The contained value.

        Raises:
            ValueError: If this is a :class:`Null` variant.
        """

    @abstractmethod
    def is_some(self) -> bool:
        """Return ``True`` if this option holds a value."""

    @abstractmethod
    def is_null(self) -> bool:
        """Return ``True`` if this option is empty."""

    @abstractmethod
    def Q(self) -> T:
        """Propagate :class:`Null` like Rust's ``?`` operator.

        If this is :class:`Some`, unwrap and return the value.  If this is
        :class:`Null`, raise :class:`PropagationError` which is caught by the
        :func:`allow_Q` decorator and returned as :class:`Null` to the caller.

        Must be used inside a function decorated with :func:`allow_Q`.

        Returns:
            The contained value.

        Raises:
            PropagationError: Caught by :func:`allow_Q`; do not handle
                manually.
        """

    @abstractmethod
    def ok_or[E](self, err: E) -> Result[T, E]:
        """Convert this option into a ``Result``, using *err* for :class:`Null`.

        Args:
            err: The error value to use when this option is :class:`Null`.

        Returns:
            :class:`Ok` wrapping the value, or :class:`Err` wrapping *err*.
        """

    @abstractmethod
    def ok_or_else[E](self, f: Callable[[], E]) -> Result[T, E]:
        """Convert this option into a ``Result``, calling *f* for :class:`Null`.

        Args:
            f: Zero-argument callable that produces the error value when this
               option is :class:`Null`.

        Returns:
            :class:`Ok` wrapping the value, or :class:`Err` wrapping ``f()``.
        """


class Some[T](Option[T]):
    """An :class:`Option` variant that holds a value.

    Attributes:
        val: The wrapped value of type *T*.
    """

    __match_args__ = ("val",)

    def __init__(self, val: T) -> None:
        """Wrap *val* in a ``Some``.

        Args:
            val: The value to hold.
        """
        self.val = val

    def unwrap(self) -> T:
        """Return the contained value."""
        return self.val

    def unwrap_or[U](self, default: U) -> T | U:
        """Return the contained value (ignores *default*)."""
        return self.val

    def expect(self, msg: str) -> T:
        """Return the contained value (ignores *msg*)."""
        return self.val

    def is_some(self) -> bool:
        """Always returns ``True``."""
        return True

    def is_null(self) -> bool:
        """Always returns ``False``."""
        return False

    def Q(self) -> T:
        """Return the contained value unchanged."""
        return self.val

    def ok_or[E](self, err: E) -> "Result[T, E]":
        """Return ``Ok(val)`` (ignores *err*)."""
        return Ok(self.val)

    def ok_or_else[E](self, f: Callable[[], E]) -> "Result[T, E]":
        """Return ``Ok(val)`` (never calls *f*)."""
        return Ok(self.val)


class Null[T](Option[T]):
    """An :class:`Option` variant that represents the absence of a value."""

    def unwrap(self) -> T:
        """Raise ``ValueError`` — no value is present.

        Raises:
            ValueError: Always.
        """
        raise ValueError(f"`.unwrap()` called on a `Null` value")

    def unwrap_or[U](self, default: U) -> T | U:
        """Return *default* because no value is present."""
        return default

    def expect(self, msg: str) -> T:
        """Raise ``ValueError`` with *msg*.

        Args:
            msg: Message for the raised exception.

        Raises:
            ValueError: Always.
        """
        raise ValueError(msg)

    def is_some(self) -> bool:
        """Always returns ``False``."""
        return False

    def is_null(self) -> bool:
        """Always returns ``True``."""
        return True

    def Q(self) -> T:
        """Propagate this ``Null`` via :class:`PropagationError`.

        Raises:
            PropagationError: Always; caught by :func:`allow_Q`.
        """
        raise PropagationError(Null())

    def ok_or[E](self, err: E) -> "Result[T, E]":
        """Return ``Err(err)``."""
        return Err(err)

    def ok_or_else[E](self, f: Callable[[], E]) -> "Result[T, E]":
        """Return ``Err(f())``."""
        return Err(f())


class Ok[T, E](Result[T, E]):
    """A :class:`Result` variant representing a successful computation.

    Attributes:
        val: The success value of type *T*.
    """

    __match_args__ = ("val",)

    def __init__(self, val: T) -> None:
        """Wrap *val* in an ``Ok``.

        Args:
            val: The success value to hold.
        """
        self.val = val

    def is_ok(self) -> bool:
        """Always returns ``True``."""
        return True

    def is_err(self) -> bool:
        """Always returns ``False``."""
        return False

    def expect(self, msg: str) -> T:
        """Return the contained success value (ignores *msg*)."""
        return self.val

    def expect_err(self, msg: str) -> E:
        """Raise ``ValueError`` with *msg* — this is not an error.

        Args:
            msg: Message for the raised exception.

        Raises:
            ValueError: Always.
        """
        e = ValueError(msg)
        e.add_note(f"Caused by call `Ok({self.val}).expect_err(...)`")
        raise e

    def unwrap(self) -> T:
        """Return the contained success value."""
        return self.val

    def unwrap_err(self) -> E:
        """Raise ``ValueError`` — this is not an error.

        Raises:
            ValueError: Always.
        """
        e = ValueError("`.unwrap_err()` called on `Ok` value")
        e.add_note(f"Caused by call `Ok({self.val}).unwrap_err()`")
        raise e

    def unwrap_or[U](self, default: U) -> T | U:
        """Return the contained success value (ignores *default*)."""
        return self.val

    def unwrap_err_or[U](self, default: U) -> E | U:
        """Return *default* because this is not an error."""
        return default

    def Q(self) -> T:
        """Return the contained success value unchanged."""
        return self.val


class Err[T, E](Result[T, E]):
    """A :class:`Result` variant representing a failed computation.

    Attributes:
        val: The error value of type *E*.
    """

    __match_args__ = ("val",)

    def __init__(self, err: E) -> None:
        """Wrap *err* in an ``Err``.

        Args:
            err: The error value to hold.
        """
        self.val = err

    def is_ok(self) -> bool:
        """Always returns ``False``."""
        return False

    def is_err(self) -> bool:
        """Always returns ``True``."""
        return True

    def expect(self, msg: str) -> T:
        """Raise the underlying error — no success value exists.

        If the error value is an :class:`Exception` it is re-raised directly;
        otherwise a ``ValueError`` with *msg* is raised.

        Args:
            msg: Message for the ``ValueError`` when the error value is not
                an exception.

        Raises:
            Exception: The contained error when it is already an exception.
            ValueError: When the contained error is not an exception.
        """
        if isinstance(self.val, Exception):
            self.val.add_note(
                f"Caused by .expect(...) call on `Err` value raised above"
            )
            raise self.val
        else:
            e = ValueError(msg)
            e.add_note(f"Caused by call `Err({self.val}).expect(...)`")
            raise e

    def expect_err(self, msg: str) -> E:
        """Return the contained error value (ignores *msg*)."""
        return self.val

    def unwrap(self) -> T:
        """Raise the underlying error — no success value exists.

        Raises:
            Exception: The contained error when it is already an exception.
            ValueError: When the contained error is not an exception.
        """
        if isinstance(self.val, Exception):
            self.val.add_note(f"Caused by `.unwrap()` call on `Err` value raised above")
            raise self.val
        else:
            e = ValueError("`.unwrap()` called on `Err` value")
            e.add_note(f"Caused by call `Err({self.val}).unwrap()`")
            raise e

    def unwrap_err(self) -> E:
        """Return the contained error value."""
        return self.val

    def unwrap_or[U](self, default: U) -> T | U:
        """Return *default* because this is an error."""
        return default

    def unwrap_err_or[U](self, default: U) -> E | U:
        """Return the contained error value (ignores *default*)."""
        return self.val

    def Q(self):
        """Propagate this error via :class:`PropagationError`.

        Raises:
            PropagationError: Always; caught by :func:`allow_Q`.
        """
        raise PropagationError(Err(self.val))


class PropagationError(Exception):
    """Internal sentinel used by the ``.Q()`` short-circuit mechanism.

    Raised by :meth:`Err.Q` and :meth:`Null.Q`; caught by the
    :func:`allow_Q` decorator, which returns ``self.val`` from the decorated
    function.  Should never escape to user-visible code.

    Attributes:
        val: The :class:`Err` or :class:`Null` value being propagated.
    """

    def __init__(self, val: "Result | Option") -> None:
        """Initialise with the error/null value to propagate.

        Args:
            val: The :class:`Err` or :class:`Null` instance being propagated.
        """
        self.val = val
        super().__init__(
            "if you're seeing this it means you forgot the @allow_Q decorator"
        )


P = ParamSpec("P")
T = TypeVar("T")
E = TypeVar("E")
U = TypeVar("U")
R = TypeVar("R", bound=Option[T] | Result[T, E])


def allow_Q(f: Callable[P, R]) -> Callable[P, R]:
    """Decorator that enables the ``.Q()`` short-circuit operator inside *f*.

    Wraps *f* so that any :class:`PropagationError` raised by a ``.Q()``
    call is caught and the propagated :class:`Err` / :class:`Null` value is
    returned in place of the normal return value — mirroring Rust's ``?``
    operator semantics.

    Args:
        f: The function to wrap.  Its return type must be a :class:`Result` or
           :class:`Option` subtype so that propagated errors are type-safe.

    Returns:
        A wrapped callable with identical signature that transparently handles
        ``.Q()`` propagation.

    Example::

        @allow_Q
        def divide(a: int, b: int) -> Result[float, str]:
            result = safe_divide(a, b).Q()  # propagates Err if b == 0
            return Ok(result)
    """

    @wraps(f)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return f(*args, **kwargs)
        except PropagationError as e:
            return e.val

    return wrapper
