import logging
from functools import wraps

TRACE_LEVEL = 5 # The trace level should be set just below debug
logging.addLevelName(TRACE_LEVEL, "TRACE")

def log_with_extra(func):
    """Provides a function wrapper and the format structure for any functions with the `@log_with_extra` annotation."""

    @wraps(func)
    def wrapper(self, msg, *args, **kwargs):
        extra_info = {}

        for key, val in kwargs.items():
            extra_info[key] = val
        return func(self, msg, *args, extra=extra_info)
    return wrapper

class Logger(logging.Logger):
    def __init__(self, name: str) -> None:
        """
        Instantiating the Logger class automatically adds the file and console handlers for use in logging.

        After providing the requisite import statements, the following is an example of setting the customer
        logger class as the default logger class.
        `Example - Setting the default logger: ``logging.setLogger(Logger)```

        :param name:
                The name is provided by instantiating the custom logger within a module using a built-in variable.
                Example - instantiating the custom logger: `logger = logging.getLogger(__name__)
        """
        super().__init__(name)
        self.setLevel(logging.DEBUG)
        self.propagate = False

        # Instantiates a console handler class object
        console_handler = ConsoleHandler()
        self.addHandler(console_handler)

        # Instantiates a file handler class object
        file_handler = CustomFileHandler()
        self.addHandler(file_handler)

    @log_with_extra
    def info(self, msg, *args, **kwargs):
        """
        Allows instantiated loggers to include a dictionary of information for the INFO level
        along with the console output.

        Syntax and usage: `logger.info("This is an info log", extra={'user_id': 'user_id_info', 'task': 'task_info'})`
        """
        if self.isEnabledFor(logging.INFO):
            self._log(logging.INFO, msg, args, **kwargs)

    @log_with_extra
    def debug(self, msg, *args, **kwargs):
        """
        Allows instantiated loggers to include a dictionary of information for the DEBUG level
        along with the console output.

        Syntax and usage: `logger.debug("This is a debug log", extra={'user_id': 'user_id_debug'})`
        """
        if self.isEnabledFor(logging.DEBUG):
            self._log(logging.DEBUG, msg, args, **kwargs)

    @log_with_extra
    def warning(self, msg, *args, **kwargs):
        """
        Allows instantiated loggers to include a dictionary of information for the WARNING level
        along with the console output.

        Syntax and usage: `logger.warning("This is a debug log", extra={
                                                                    'user_id': 'user_id_warning',
                                                                    'context': 'example_warning'})`
        """
        if self.isEnabledFor(logging.WARNING):
            self._log(logging.WARNING, msg, args, **kwargs)

    @log_with_extra
    def error(self, msg, *args, **kwargs):
        """
        Allows instantiated loggers to include a dictionary of information for the ERROR level
        along with the console output.

       Syntax and usage: `logger.error("This is an error log", extra={
                                                                  'error_code': 500,
                                                                  'details': 'Internal Server Error'})`
        """
        if self.isEnabledFor(logging.ERROR):
            self._log(logging.ERROR, msg, args, **kwargs)

    @log_with_extra
    def critical(self, msg, *args, **kwargs):
        """
        Allows instantiated loggers to include a dictionary of information for the CRITICAL level
        along with the console output.

        Syntax and usage: `logger.critical("This is a critical log", extra={
                                                                            'user_id': 'user_id_critical',
                                                                            'action': 'shutdown'})`
        """
        if self.isEnabledFor(logging.CRITICAL):
            self._log(logging.CRITICAL, msg, args, **kwargs)

    @log_with_extra
    def trace(self, msg, *args, **kwargs):
        """
        Allows instantiated loggers to include a dictionary of information for the TRACE level
        along with the console output.

        Syntax and usage: `logger.trace("This is a trace log", user_id='user_id_trace')`
        """
        if self.isEnabledFor(TRACE_LEVEL):
            self._log(logging.INFO, msg, args, **kwargs)

class ConsoleHandler(logging.StreamHandler):
    def __init__(self, level: int = logging.DEBUG) -> None:
        """The ConsoleHandler class provides formatting and a default logging level for the console
        output as part of the Logger class."""
        super().__init__()
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s",
            datefmt = "%m/%d/%Y %H:%M:%S",
        )
        self.setFormatter(formatter)
        self.setLevel(level)

class CustomFileHandler(logging.FileHandler):
    def __init__(self):
        """The CustomFileHandler class provides formatting, encoding type and a default logging level for logging file
        output as part of the Logger class."""
        log_file = "custom_logger/log_file.log"
        super().__init__(log_file, encoding="UTF-8")
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s",
            datefmt = "%m/%d/%Y %H:%M:%S",
        )
        self.setFormatter(formatter)
        self.setLevel(logging.INFO)
