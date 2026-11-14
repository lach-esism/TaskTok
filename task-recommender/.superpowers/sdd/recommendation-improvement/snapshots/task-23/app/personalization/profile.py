"""User profile construction and completeness."""

from __future__ import annotations

from app.domain import UserProfile


def experience_bucket(years: float) -> str:
    if years < 3:
        return "junior"
    if years <= 7:
        return "mid"
    return "senior"


def build_profile(
    user,
    entity_type: str,
    declared: dict | None = None,
) -> UserProfile:
    declared = declared or {}
    role = str(declared.get("role", getattr(user, "role", "unknown")))
    industry = str(
        declared.get("industry", getattr(user, "industry", "unknown"))
    )
    experience = float(
        declared.get(
            "experience_years",
            getattr(user, "experience_years", 0.0),
        )
    )
    profile = UserProfile(
        user_id=str(getattr(user, "worker_id", getattr(user, "customer_id", ""))),
        entity_type=entity_type,
        role=role,
        industry=industry,
        experience_years=experience,
        skills=dict(getattr(user, "skills", {}) or {}),
        specialties=dict(getattr(user, "specialties", {}) or {}),
        region=str(getattr(user, "region", "")),
        preferred_categories=dict(
            getattr(user, "preferred_categories", {}) or {}
        ),
        profile_completeness=0.0,
        segment_id=f"{role}:{experience_bucket(experience)}",
        declared_preferences=dict(
            declared.get("preferences", {}) or {}
        ),
    )
    profile.profile_completeness = profile_completeness(profile)
    return profile


def profile_completeness(profile: UserProfile) -> float:
    fields = [
        profile.role not in {"", "unknown"},
        profile.industry not in {"", "unknown"},
        profile.experience_years > 0,
        bool(profile.region),
        bool(profile.skills),
        bool(profile.preferred_categories),
    ]
    return sum(fields) / len(fields)
