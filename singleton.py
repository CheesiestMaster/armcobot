from functools import wraps

def Singleton(_cls: type):
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
    class SingletonClass(_cls):
        _is_singleton = True
        @wraps(_cls.__init__)
        def __init__(self, *args, **kwargs):
            """
            Initializes the singleton instance if it hasn't been initialized yet.
            """
            nonlocal _init
            if _init:
                return
            _init = True
            super().__init__(*args, **kwargs)
        
        def __new__(cls, *args, **kwargs):
            """
            Creates a new instance of the singleton class if it doesn't exist yet.
            """
            nonlocal _instance
            if not _instance:
                _instance = super(SingletonClass, cls).__new__(cls)
            return _instance

    SingletonClass.__name__ = _cls.__name__
    SingletonClass.__doc__ = _cls.__doc__
    return SingletonClass
