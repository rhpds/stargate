"""Fail-closed ownership contracts; real PostgreSQL races run separately."""
from unittest.mock import Mock

import pytest

from db import summary_refresh
from db.models import MVClusterSummary, MVPipelineStage, MVLabEvalSummary


def postgres_session(acquired=True):
    db=Mock(new=set(), dirty=set(), deleted=set())
    db.in_nested_transaction.return_value=False
    db.get_bind.return_value.dialect.name='postgresql'
    db.connection.return_value.get_isolation_level.return_value='READ COMMITTED'
    db.execute.return_value.scalar_one.return_value=acquired
    return db


@pytest.mark.parametrize('model',[MVClusterSummary,MVPipelineStage,MVLabEvalSummary])
def test_busy_worker_never_aggregates_or_publishes(model):
    db=postgres_session(False)
    work=Mock()
    refresh=summary_refresh._single_writer(model)(work)
    assert refresh(db, None) is False
    work.assert_not_called()
    db.rollback.assert_called_once_with()
    db.commit.assert_not_called()
    sql=str(db.execute.call_args.args[0])
    assert 'pg_try_advisory_xact_lock' in sql
    assert 'pg_advisory_xact_lock(' not in sql


def test_acquisition_precedes_work_and_preserves_result():
    db=postgres_session()
    def work(session, now):
        session.execute.assert_called_once()
        return 'completed'
    assert summary_refresh._single_writer(MVClusterSummary)(work)(db,None)=='completed'


@pytest.mark.parametrize('error',[RuntimeError('synthetic failure'),KeyboardInterrupt()])
def test_failure_or_cancellation_rolls_back_and_propagates(error):
    db=postgres_session()
    work=Mock(side_effect=error)
    with pytest.raises(type(error)):
        summary_refresh._single_writer(MVClusterSummary)(work)(db,None)
    db.rollback.assert_called_once_with()


def test_lock_query_failure_also_rolls_back():
    db=postgres_session()
    db.execute.side_effect=RuntimeError('synthetic connection failure')
    with pytest.raises(RuntimeError):
        summary_refresh._single_writer(MVClusterSummary)(Mock())(db,None)
    db.rollback.assert_called_once_with()


def test_old_transaction_snapshot_fails_closed():
    db=postgres_session()
    db.connection.return_value.get_isolation_level.return_value='REPEATABLE READ'
    work=Mock()
    with pytest.raises(RuntimeError,match='READ COMMITTED'):
        summary_refresh._single_writer(MVClusterSummary)(work)(db,None)
    work.assert_not_called()
    db.rollback.assert_called_once_with()


@pytest.mark.parametrize('attribute',['new','dirty','deleted'])
def test_refresh_refuses_to_commit_or_discard_unrelated_pending_work(attribute):
    db=postgres_session()
    setattr(db,attribute,{object()})
    with pytest.raises(RuntimeError,match='clean'):
        summary_refresh._single_writer(MVClusterSummary)(Mock())(db,None)
    db.execute.assert_not_called()
    db.rollback.assert_not_called()


def test_nested_transaction_is_not_owned_by_refresh():
    db=postgres_session()
    db.in_nested_transaction.return_value=True
    with pytest.raises(RuntimeError,match='nested'):
        summary_refresh._single_writer(MVClusterSummary)(Mock())(db,None)
    db.execute.assert_not_called()
    db.rollback.assert_not_called()
