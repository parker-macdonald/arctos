"""Standardized logging"""

import logging
import sys


ANSI_BOLDFACE_COLORS = {
    # See https://notes.burke.libbey.me/ansi-escape-codes/ for an explanation of the codes
    # In short, 'm' tells the terminal to change the rendering of the text,
    # 30-37 controls the foreground colors of the text, 1 makes the text bold
    "black": "\x1b[30;1m",
    "red": "\x1b[31;1m",
    "green": "\x1b[32;1m",
    "yellow": "\x1b[33;1m",
    "blue": "\x1b[34;1m",
    "magenta": "\x1b[35;1m",
    "cyan": "\x1b[36;1m",
    "white": "\x1b[37;1m",
}

ANSI_RESET = "\x1b[0m"


def colorize(text: str, color: str) -> str:
    """Adds ANSI colors to text so that it displays with color in the console/terminal.

    Args
        text: text to be colored
        color: name of the color (case-insensitive)

    Returns:
        Text with added escape sequences for color

    Example:

    .. code-block:: python

        from app.utils.logging import colorize

        print(colorize("This is a message", "green"))
    """
    try:
        color_escape_sequence = ANSI_BOLDFACE_COLORS[color.lower()]
    except KeyError:
        raise ValueError(
            f"Color {color} is not defined yet. The following colors are available: {list(ANSI_BOLDFACE_COLORS.keys())}"
        ) from None
    return f"{color_escape_sequence}{text}{ANSI_RESET}"


class CustomFormatter(logging.Formatter):
    _LEVEL_PREFIX = "[%(levelname)s]"
    _MESSAGE_FORMAT = "[%(asctime)s] (%(filename)s:%(funcName)s:%(lineno)d) %(message)s"

    _FORMATTERS = {
        logging.DEBUG: logging.Formatter(ANSI_BOLDFACE_COLORS["cyan"] + _LEVEL_PREFIX + ANSI_RESET + _MESSAGE_FORMAT),
        logging.INFO: logging.Formatter(ANSI_BOLDFACE_COLORS["green"] + _LEVEL_PREFIX + ANSI_RESET + _MESSAGE_FORMAT),
        logging.WARNING: logging.Formatter(
            ANSI_BOLDFACE_COLORS["yellow"] + _LEVEL_PREFIX + ANSI_RESET + _MESSAGE_FORMAT
        ),
        logging.ERROR: logging.Formatter(ANSI_BOLDFACE_COLORS["red"] + _LEVEL_PREFIX + ANSI_RESET + _MESSAGE_FORMAT),
        logging.CRITICAL: logging.Formatter(
            ANSI_BOLDFACE_COLORS["magenta"] + _LEVEL_PREFIX + ANSI_RESET + _MESSAGE_FORMAT
        ),
    }

    def format(self, record):
        formatter = self._FORMATTERS.get(record.levelno, self._FORMATTERS[logging.INFO])
        return formatter.format(record)


def get_or_configure_logger(
    name: str,
    logger: logging.Logger | None = None,
    log_level: int | str = "NOTSET",
    replace_handler: bool = False,
    propagate: bool = True,
) -> logging.Logger:
    """Initializes a logger object with a custom formatter and a console stream handler at a specific level

    Example:
        >>> logger = get_or_configure_logger(__name__)

    Arguments:
        name: Reference name to the logger
        logger: Logger object to be initialized
        log_level: The logging level to set for the logger. Defaults to 'NOTSET'.
        replace_handler: Whether to clear existing handlers before adding a new one.
        propagate: propagate the logger to the parent logger. Defaults to True.

    Returns:
        A new logger object, or the existing logger if one was provided
    """
    logger = logger or logging.getLogger(name)

    if replace_handler:
        logger.handlers.clear()

    if isinstance(log_level, str):
        log_level = logging.getLevelNamesMapping()[log_level.upper()]

    if not logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(CustomFormatter())
        console_handler.setLevel(logging.DEBUG)
        logger.addHandler(console_handler)

    logger.propagate = propagate
    logger.setLevel(log_level)

    return logger
