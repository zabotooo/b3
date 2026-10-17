class B3Error(Exception):
    """Error reported to clients as {code, message, port?}."""

    def __init__(self, code: str, message: str, port: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.port = port

    def to_dict(self) -> dict:
        d = {"code": self.code, "message": self.message}
        if self.port is not None:
            d["port"] = self.port
        return d
