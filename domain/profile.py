"""Score de buro a perfil de credito. Funcion pura; la tabla vive en YAML."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

SCORE_MIN, SCORE_MAX = 400, 850


class ProfileStatus(StrEnum):
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    ESCALATE = "ESCALATE"


class Band(BaseModel):
    model_config = ConfigDict(frozen=True)

    band: str
    min_score: int
    profile: str
    max_ltv: Decimal | None
    annual_rate: Decimal | None


class ProfilePolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str
    bands: tuple[Band, ...]
    terms_months: tuple[int, ...]


class BureauProfile(BaseModel):
    """Perfil normalizado; nunca el reporte crudo del buro."""

    model_config = ConfigDict(frozen=True)

    score: int | None
    active_delinquency: bool = False
    thin_file: bool = False


class ProfileDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ProfileStatus
    band: str | None = None
    profile: str | None = None
    max_ltv: Decimal | None = None
    annual_rate: Decimal | None = None
    reason_codes: tuple[str, ...] = ()
    rule_version: str


def load_profile_policy(path: Path) -> ProfilePolicy:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # Las bandas se evaluan de mayor a menor score minimo.
    data["bands"] = sorted(
        data["bands"], key=lambda b: b["min_score"], reverse=True
    )
    return ProfilePolicy.model_validate(data)


def evaluate_profile(
    policy: ProfilePolicy, bureau: BureauProfile
) -> ProfileDecision:
    def out(status: ProfileStatus, *codes: str) -> ProfileDecision:
        return ProfileDecision(
            status=status, reason_codes=codes, rule_version=policy.version
        )

    # Hard stop: morosidad activa no se compensa con score.
    if bureau.active_delinquency:
        return out(ProfileStatus.DECLINED, "ACTIVE_DELINQUENCY")
    # Dato ausente o dudoso: nunca se aprueba ni se rechaza solo.
    if bureau.thin_file:
        return out(ProfileStatus.ESCALATE, "THIN_FILE")
    score = bureau.score
    if score is None:
        return out(ProfileStatus.ESCALATE, "SCORE_MISSING")
    if not SCORE_MIN <= score <= SCORE_MAX:
        return out(ProfileStatus.ESCALATE, "SCORE_OUT_OF_RANGE")

    for band in policy.bands:
        if score >= band.min_score:
            if band.max_ltv is None or band.annual_rate is None:
                return ProfileDecision(
                    status=ProfileStatus.DECLINED,
                    band=band.band,
                    profile=band.profile,
                    reason_codes=("SCORE_BELOW_MINIMUM",),
                    rule_version=policy.version,
                )
            return ProfileDecision(
                status=ProfileStatus.APPROVED,
                band=band.band,
                profile=band.profile,
                max_ltv=band.max_ltv,
                annual_rate=band.annual_rate,
                rule_version=policy.version,
            )
    return out(ProfileStatus.ESCALATE, "NO_BAND_MATCHED")
