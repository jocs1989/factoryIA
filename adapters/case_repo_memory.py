"""Repositorio de casos en memoria, para pruebas y el modo `mock`."""

from __future__ import annotations

import threading

from domain.case import Case, StaleVersion
from ports import CaseExists, CaseNotFound


class MemoryCaseRepository:
    """Implementacion en memoria de `CaseRepositoryPort`.

    Segura entre hilos.
    """

    def __init__(self) -> None:
        self._cases: dict[str, Case] = {}
        self._lock = threading.Lock()

    def add(self, case: Case) -> None:
        """Crea el caso; `CaseExists` si ya hay uno con ese id."""
        with self._lock:
            if case.case_id in self._cases:
                raise CaseExists(case.case_id)
            self._cases[case.case_id] = case.model_copy(deep=True)

    def get(self, case_id: str) -> Case | None:
        """Copia del caso, para que nadie mute lo guardado."""
        found = self._cases.get(case_id)
        return found.model_copy(deep=True) if found else None

    def save(self, case: Case, *, expected_version: int) -> None:
        """Guarda solo si la version guardada es `expected_version`.

        Si no, `StaleVersion`.
        """
        with self._lock:
            current = self._cases.get(case.case_id)
            if current is None:
                raise CaseNotFound(case.case_id)
            if current.version != expected_version:
                raise StaleVersion(
                    f"guardado v{current.version}, "
                    f"esperado v{expected_version}"
                )
            self._cases[case.case_id] = case.model_copy(deep=True)
