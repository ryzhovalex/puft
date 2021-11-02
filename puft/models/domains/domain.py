from abc import abstractmethod
from typing import Any, List, Dict, Tuple, Union, Callable, Literal

from ...errors.error import Error
from ...helpers.logger import logger
from ...helpers.singleton import Singleton
from ...tools.regular import format_error_message


class Domain(metaclass=Singleton):
    """Represents abstract model which chained to own certain controller and has start and stop actions and states."""
    def __init__(self) -> None:
        pass

    def get_bound_by_id(self, **kwargs) -> Any:
        """Abstract method. Get first bound instance matched given id from appropriate mapper.
        
        Should be reimplemented with appropriate logic for instance fetching.
        
        Raise:
            NotImplementedError: If called and not re-implemented in children."""
        raise NotImplementedError("Should have been re-implemented in this domain.")