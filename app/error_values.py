'''
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
'''
from abc import ABC, abstractmethod
from typing import Callable, ParamSpec, TypeVar, Generic
from functools import wraps


def option[T](val: T | None) -> "Option[T]":
    """Convert a nullable value into an Option."""
    return Null() if val is None else Some(val)

class Result[T, E](ABC):   
    @abstractmethod
    def is_ok(self) -> bool: pass
    @abstractmethod
    def is_err(self) -> bool: pass

    @abstractmethod
    def expect(self, msg: str) -> T: pass
    @abstractmethod
    def expect_err(self, msg: str) -> E: pass

    @abstractmethod
    def unwrap(self) -> T: pass
    @abstractmethod
    def unwrap_err(self) -> E: pass

    @abstractmethod
    def unwrap_or[U](self, default: U) -> T | U: pass
    @abstractmethod
    def unwrap_err_or[U](self, default: U) -> E | U: pass
    @abstractmethod
    def Q(self) -> T: 
        """like rust's ? operator: if `self` is an Ok<T>, unwrap it. If `self` is an Err<E>, return `self` from the function calling .Q()

        Returns:
            T: value contained in this Result, if it is an Ok value.
        """
        pass

class Option[T](ABC):    
    @abstractmethod
    def unwrap(self) -> T: pass
    @abstractmethod
    def unwrap_or[U](self, default: U) -> T | U: pass
    @abstractmethod
    def expect(self, msg: str) -> T: pass
    @abstractmethod
    def is_some(self) -> bool: pass
    @abstractmethod
    def is_null(self) -> bool: pass
    @abstractmethod
    def Q(self) -> T: 
        """like rust's ? operator: if `self` is a Null, return Null from this function. Otherwise, unwrap self.

        Returns:
            T: the value contained inside (if Some<T>)
        """
        pass

    @abstractmethod
    def ok_or[E](self, err: E) -> Result[T, E]: pass
    @abstractmethod
    def ok_or_else[E](self, f: Callable[[], E]) -> Result[T, E]: pass

class Some[T](Option[T]):
    __match_args__ = ('val',)
    def __init__(self, val: T): self.val = val
    def unwrap(self) -> T: return self.val
    def unwrap_or[U](self, default: U) -> T | U: return self.val
    def expect(self, msg: str) -> T: return self.val
    def is_some(self) -> bool: return True
    def is_null(self) -> bool: return False
    def Q(self) -> T: return self.val
    def ok_or[E](self, err: E) -> "Result[T, E]": return Ok(self.val)
    def ok_or_else[E](self, f: Callable[[], E]) -> "Result[T, E]": return Ok(self.val)

class Null[T](Option[T]):
    def unwrap(self) -> T: raise ValueError(f'`.unwrap()` called on a `Null` value')
    def unwrap_or[U](self, default: U) -> T | U: return default
    def expect(self, msg: str) -> T: raise ValueError(msg)
    def is_some(self) -> bool: return False
    def is_null(self) -> bool: return True
    def Q(self) -> T: raise PropagationError(Null())
    def ok_or[E](self, err: E) -> "Result[T, E]": return Err(err)
    def ok_or_else[E](self, f: Callable[[], E]) -> "Result[T, E]": return Err(f())



class Ok[T, E](Result[T, E]):
    __match_args__ = ('val',)
    def __init__(self, val: T): self.val = val

    def is_ok(self) -> bool: return True
    def is_err(self) -> bool: return False

    def expect(self, msg: str) -> T: return self.val
    def expect_err(self, msg: str) -> E: 
        e = ValueError(msg)
        e.add_note(f'Caused by call `Ok({self.val}).expect_err(...)`')
        raise e

    def unwrap(self) -> T: return self.val
    def unwrap_err(self) -> E: 
        e = ValueError('`.unwrap_err()` called on `Ok` value')
        e.add_note(f'Caused by call `Ok({self.val}).unwrap_err()`')
        raise e

    def unwrap_or[U](self, default: U) -> T | U: return self.val
    def unwrap_err_or[U](self, default: U) -> E | U: return default

    def Q(self) -> T: return self.val
    

class Err[T, E](Result[T, E]):
    __match_args__ = ('val',)
    def __init__(self, err: E): self.val = err

    def is_ok(self) -> bool: return False
    def is_err(self) -> bool: return True

    def expect(self, msg: str) -> T: 
        if isinstance(self.val, Exception):
            self.val.add_note(f'Caused by .expect(...) call on `Err` value raised above')
            raise self.val
        else:
            e = ValueError(msg)
            e.add_note(f'Caused by call `Err({self.val}).expect(...)`')
            raise e
    def expect_err(self, msg: str) -> E: return self.val

    def unwrap(self) -> T: 
        if isinstance(self.val, Exception):
            self.val.add_note(f'Caused by `.unwrap()` call on `Err` value raised above')
            raise self.val
        else:
            e = ValueError('`.unwrap()` called on `Err` value')
            e.add_note(f'Caused by call `Err({self.val}).unwrap()`')
            raise e
    def unwrap_err(self) -> E: return self.val

    def unwrap_or[U](self, default: U) -> T | U: return default
    def unwrap_err_or[U](self, default: U) -> E | U: return self.val

    def Q(self): raise PropagationError(Err(self.val))

class PropagationError(Exception):
    def __init__(self, val):
        self.val = val
        super().__init__("if you're seeing this it means you forgot the @allow_Q decorator")

P = ParamSpec("P")
T = TypeVar("T")
E = TypeVar("E")
U = TypeVar("U")
R = TypeVar("R", bound=Option[T] | Result[T, E])


def allow_Q(f: Callable[P, R]) -> Callable[P, R]:
    @wraps(f)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return f(*args, **kwargs)
        except PropagationError as e:
            return e.val
    return wrapper