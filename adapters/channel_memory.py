from __future__ import annotations


class MemoryChannel:
    """Canal en memoria: guarda lo enviado, util para pruebas y la demo."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, case_id: str, text: str) -> str:
        self.sent.append((case_id, text))
        return f"msg-mem-{len(self.sent):04d}"
