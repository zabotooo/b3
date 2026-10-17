"""Interface between hatd and the Build HAT hardware."""

from abc import ABC, abstractmethod


class HatBackend(ABC):
    """Hardware access. Speeds are -100..100 (positive = clockwise).

    Blocking motor methods return when the movement is finished and raise
    B3Error("interrupted") if motor_stop/stop_all stopped them first.
    """

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    def typeids(self) -> dict[str, int | None]: ...

    @abstractmethod
    async def read(self) -> dict[str, dict]: ...

    @abstractmethod
    async def vin(self) -> float: ...

    @abstractmethod
    async def motor_run_for_degrees(self, port: str, degrees: float, speed: int) -> None: ...

    @abstractmethod
    async def motor_run_for_seconds(self, port: str, seconds: float, speed: int) -> None: ...

    @abstractmethod
    async def motor_start(self, port: str, speed: int) -> None: ...

    @abstractmethod
    async def motor_stop(self, port: str) -> None: ...

    @abstractmethod
    async def motor_go_to(self, port: str, position: int, direction: str, speed: int) -> None: ...

    @abstractmethod
    async def light_set(self, port: str, brightness: int) -> None: ...

    @abstractmethod
    async def matrix_set(self, port: str, pixels: list[tuple[str, int]]) -> None: ...

    @abstractmethod
    async def sensor_lights(self, port: str, values: list[int]) -> None: ...

    @abstractmethod
    async def stop_all(self) -> None: ...
