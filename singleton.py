from functools import wraps
from typing import TYPE_CHECKING, TypeVar, Type

T = TypeVar("T")

def Singleton(_cls: Type[T]) -> Type[T]:
    """
    A decorator to make a class a singleton. It overrides __new__ and __init__ methods.

    Args:
        cls (type): The class to be decorated as a singleton.

    Raises:
        TypeError: If the decorator is applied to a non-class type.
        ValueError: If the class already has a _is_singleton attribute.
        
    Returns:
        SingletonClass: The singleton version of the input class.
    """
    _instance = None
    _init = False
    
    if not isinstance(_cls, type):
        raise TypeError("Singleton decorator can only be applied to classes")
    if hasattr(_cls, "_is_singleton"):
        raise ValueError("Class already has a _is_singleton attribute")

    @wraps(_cls.__init__)
    def __init__(self, *args, **kwargs):
        nonlocal _init
        if _init:
            return
        _init = True
        super(SingletonClass, self).__init__(*args, **kwargs)

    def __new__(cls, *args, **kwargs):
        nonlocal _instance
        if not _instance:
            _instance = super(SingletonClass, cls).__new__(cls)
        return _instance

    # Creating SingletonClass dynamically using `type()`
    SingletonClass = type(
        _cls.__name__,  # Name of the class
        (_cls,),        # Inheriting from the original class
        {
            "_is_singleton": True,
            "__init__": __init__,
            "__new__": __new__,
            "__doc__": _cls.__doc__,  # Include the original class docstring
        }
    )
    
    return SingletonClass if not TYPE_CHECKING else _cls
