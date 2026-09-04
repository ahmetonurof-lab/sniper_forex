"""Local test stub — models.py (server models.py'nin test icin yeterli kismi)."""


class Result:
    def __init__(self, ok: bool, value=None, error: str = ""):
        self._ok = ok
        self.value = value
        self.error = error

    @property
    def is_ok(self) -> bool:
        return self._ok

    @property
    def is_err(self) -> bool:
        return not self._ok

    @staticmethod
    def ok(value=None) -> "Result":
        return Result(True, value=value)

    @staticmethod
    def fail(error: str = "") -> "Result":
        return Result(False, error=error)
