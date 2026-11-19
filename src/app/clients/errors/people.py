class PeopleUnavailableError(Exception):
    """Заглушка не предоставила пригодный ответ."""


class PeopleTimeoutError(Exception):
    def __init__(self, timeout_ms: int) -> None:
        self.timeout_ms = timeout_ms
        super().__init__(f"people-stub request exceeded {timeout_ms} ms")
