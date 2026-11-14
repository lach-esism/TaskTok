"""Deterministic machine checks for acceptance criteria."""

from __future__ import annotations

from datetime import datetime, timezone

from app.domain import (
    AcceptanceCriterion,
    AcceptanceSpec,
    CriterionResult,
    Submission,
    Task,
)


def _aware(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value
    )


def _section_present(
    criterion: AcceptanceCriterion, submission: Submission
) -> tuple[bool, str]:
    sections = submission.artifacts.get("sections") or {}
    section = criterion.check_config.get("section", "")
    text = sections.get(section) if isinstance(sections, dict) else None
    length = len(str(text).strip()) if text is not None else 0
    minimum = int(criterion.check_config.get("min_chars", 1))
    return length >= minimum, f"{section}: {length}/{minimum} chars"


def _min_sources(
    criterion: AcceptanceCriterion, submission: Submission
) -> tuple[bool, str]:
    sources = submission.artifacts.get("sources") or []
    minimum = int(criterion.check_config.get("min_count", 1))
    require_url = bool(criterion.check_config.get("require_url", False))
    require_date = bool(criterion.check_config.get("require_date", False))

    valid = 0
    for source in sources if isinstance(sources, list) else []:
        if not isinstance(source, dict):
            continue
        if require_url and not str(source.get("url", "")).strip():
            continue
        if require_date and not str(source.get("date", "")).strip():
            continue
        valid += 1
    return valid >= minimum, f"{valid}/{minimum} valid sources"


def _table_schema(
    criterion: AcceptanceCriterion, submission: Submission
) -> tuple[bool, str]:
    rows = submission.artifacts.get("data_table") or []
    columns = list(criterion.check_config.get("columns", []))
    minimum = int(criterion.check_config.get("min_rows", 1))
    if not isinstance(rows, list) or len(rows) < minimum:
        return False, f"{len(rows) if isinstance(rows, list) else 0}/{minimum} rows"

    for row in rows:
        if not isinstance(row, dict):
            return False, "row is not an object"
        missing = [
            column
            for column in columns
            if column not in row or row[column] in (None, "")
        ]
        if missing:
            return False, f"missing columns: {', '.join(missing)}"
    return True, f"{len(rows)} rows, columns OK"


def _arithmetic(
    criterion: AcceptanceCriterion, submission: Submission
) -> tuple[bool, str]:
    keys = list(criterion.check_config.get("keys", []))
    values = [submission.artifacts.get(key) for key in keys]
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        for value in values
    ):
        return False, "TAM/SAM/SOM must be numeric"
    ordered = all(
        left >= right for left, right in zip(values, values[1:])
    )
    positive = all(value > 0 for value in values)
    return ordered and positive, f"values: {values}"


def _deadline(
    criterion: AcceptanceCriterion, submission: Submission, task: Task
) -> tuple[bool, str]:
    submitted = _aware(submission.submitted_at)
    deadline = _aware(task.deadline)
    return submitted <= deadline, (
        f"submitted {submitted.date()} vs deadline {deadline.date()}"
    )


def _min_chars(
    criterion: AcceptanceCriterion, submission: Submission
) -> tuple[bool, str]:
    content = submission.artifacts.get("content") or ""
    length = len(str(content))
    minimum = int(criterion.check_config.get("min_chars", 1))
    return length >= minimum, f"{length}/{minimum} chars"


def _min_files(
    criterion: AcceptanceCriterion, submission: Submission
) -> tuple[bool, str]:
    files = [f for f in (submission.artifacts.get("files") or []) if str(f).strip()]
    minimum = int(criterion.check_config.get("min_files", 1))
    return len(files) >= minimum, f"{len(files)}/{minimum} files"


def _run_machine_criterion(
    criterion: AcceptanceCriterion,
    submission: Submission,
    task: Task,
) -> CriterionResult:
    if criterion.check_type == "section_present":
        passed, evidence = _section_present(criterion, submission)
    elif criterion.check_type == "min_sources":
        passed, evidence = _min_sources(criterion, submission)
    elif criterion.check_type == "table_schema":
        passed, evidence = _table_schema(criterion, submission)
    elif criterion.check_type == "arithmetic":
        passed, evidence = _arithmetic(criterion, submission)
    elif criterion.check_type == "deadline":
        passed, evidence = _deadline(criterion, submission, task)
    elif criterion.check_type == "min_chars":
        passed, evidence = _min_chars(criterion, submission)
    elif criterion.check_type == "min_files":
        passed, evidence = _min_files(criterion, submission)
    else:
        raise ValueError(
            f"unsupported machine check: {criterion.check_type}"
        )
    return CriterionResult(
        criterion_key=criterion.key,
        passed=passed,
        score=1.0 if passed else 0.0,
        evidence=evidence,
    )


def run_machine_checks(
    spec: AcceptanceSpec,
    submission: Submission,
    task: Task,
) -> list[CriterionResult]:
    return [
        _run_machine_criterion(criterion, submission, task)
        for criterion in spec.criteria
        if criterion.layer == "machine"
    ]
