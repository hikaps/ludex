from __future__ import annotations


class LudexError(Exception):
    """Error that crosses the core boundary with a stable ``code`` and a printable ``message``.

    ``code`` is lowercase snake_case and part of the ``--json`` contract.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
