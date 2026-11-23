"""What counts as a lab namespace — one predicate, two spellings.

`sandbox-%` is not an identity test. The platform's own services carry the
prefix, so the old filter would count them as labs. That was dormant only
because the five scanned clusters hold no such namespace.

The predicate also has to stay *loose* enough. A five-character sandbox code
looks like the invariant — 16,210 distinct codes in `runs` are exactly five
characters — but `sandbox-hcptest3`, `hcptest5`–`hcptest8` and `sandbox-hcprt2`
were real catalog labs in Jul–Aug 2026 (1,894 evaluations). A strict length
rule hides real labs, which is silent and expensive; admitting a service
produces a visibly failing "lab", which is cheap. Both directions are tested
here so neither drifts.

The SQL and Python spellings are run against the same fixtures.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, select

from db.lab_identity import LAB_CODE_LIKE, is_lab_namespace, lab_code_filter

LABS = [
    "sandbox-5bz2j-ocp4-cluster",
    "sandbox-24wzh-ocp4-cluster",
    "sandbox-225qt-zt-ansiblebu",
    "sandbox-a-b",
    # Longer codes are real: HCP test labs, Jul-Aug 2026.
    "sandbox-hcptest3-ocp4-cluster",
    "sandbox-hcprt2-ocp4-cluster",
]

NOT_LABS = [
    # Platform services and leftovers with the same prefix.
    "sandbox-assignment-api",
    "sandbox-api-metrics",
    "sandbox-diag2",
    # Not sandbox namespaces at all.
    "babylon-sandbox-api",
    "showroom-ab12c",
    "sandbox",
    "",
]

NAMES = LABS + NOT_LABS


@pytest.mark.parametrize("name", NAMES)
def test_python_predicate(name):
    assert is_lab_namespace(name) is (name in LABS)


def test_sql_predicate_agrees_with_python(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'labs.db'}")
    table = Table(
        "codes",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("code", String, nullable=False),
    )
    table.create(engine)

    with engine.begin() as conn:
        conn.execute(table.insert(), [{"code": n} for n in NAMES])
        got = {
            row[0]
            for row in conn.execute(select(table.c.code).where(lab_code_filter(table.c.code)))
        }

    assert got == set(LABS)
    assert got == {n for n in NAMES if is_lab_namespace(n)}


def test_a_service_name_is_not_a_lab():
    """The reason this module exists."""
    assert not is_lab_namespace("sandbox-assignment-api")


def test_a_long_code_is_still_a_lab():
    """The reason a length rule was rejected: HCP test labs are real."""
    assert is_lab_namespace("sandbox-hcptest7-ocp4-cluster")


def test_the_pattern_is_the_two_segment_shape():
    assert LAB_CODE_LIKE == "sandbox-%-%"
