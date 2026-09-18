"""Log I/O round-trips and a view sub-log induces a single view."""

from tpv.log import io as tio
from tpv.log.demo import hidden_context_log, running_example
from tpv.views.views import induce_views


def test_event_log_roundtrip_preserves_views(tmp_path):
    log = running_example()
    path = tmp_path / "run.xes"
    tio.export_xes(log, str(path))
    reloaded = tio.load_xes(str(path))
    assert reloaded.n_cases == log.n_cases
    assert {v.identifier.canonical_str() for v in induce_views(reloaded)} == {
        v.identifier.canonical_str() for v in induce_views(log)
    }


def test_view_sublog_induces_single_view(tmp_path):
    log, _ = hidden_context_log({"admin": 20, "clerk": 20, "auditor": 10})
    view = induce_views(log)[0]
    path = tmp_path / "view.xes"
    tio.export_xes(view.sublog, str(path))
    reloaded = tio.load_xes(str(path))
    sub_views = induce_views(reloaded)
    assert len(sub_views) == 1
    assert sub_views[0].identifier.canonical_str() == view.identifier.canonical_str()


def test_dataframe_loader_detects_enabled_column():
    import pandas as pd

    df = pd.DataFrame(
        {
            "case:concept:name": ["1", "1", "2", "2"],
            "concept:name": ["o", "b", "o", "c"],
            "enabled": ["o", "b,c", "o", "b,c"],
        }
    )
    log = tio.from_dataframe(df)
    assert log.n_cases == 2
    assert log.activities == {"o", "b", "c"}
