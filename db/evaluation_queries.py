"""Compact, indexed history probes for the namespaces displayed by Operations."""
from sqlalchemy import func, literal, select, union_all

from db.models import EvaluationRecord as Evaluation


def first_observed_by_lab(db, lab_codes):
    """Preserve all-time first observation without grouping entire lab histories."""
    if not lab_codes:
        return {}
    labs = union_all(*[
        select(literal(lab).label("lab_code")) for lab in sorted(set(lab_codes))
    ]).subquery("requested_labs")
    first_at = select(func.min(Evaluation.evaluated_at)).where(
        Evaluation.lab_code == labs.c.lab_code,
    ).correlate(labs).scalar_subquery()
    return dict(db.execute(select(labs.c.lab_code, first_at)).all())


def latest_evaluations_by_pair(db, pairs):
    """Latest means highest ID, including late-arriving historical evaluations."""
    if not pairs:
        return {}
    requested = union_all(*[
        select(literal(lab).label("lab_code"), literal(fc).label("failure_class"))
        for lab, fc in sorted(set(pairs))
    ]).subquery("requested_pairs")
    latest_id = select(func.max(Evaluation.id)).where(
        Evaluation.lab_code == requested.c.lab_code,
        Evaluation.failure_class == requested.c.failure_class,
    ).correlate(requested).scalar_subquery()
    rows = db.execute(select(
        Evaluation.lab_code, Evaluation.failure_class,
        Evaluation.outcome, Evaluation.evaluated_at,
    ).select_from(requested).join(Evaluation, Evaluation.id == latest_id)).all()
    return {(row.lab_code, row.failure_class): row for row in rows}
