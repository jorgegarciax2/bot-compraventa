import pandas as pd
import pytest

from tbot.data import schema


def test_normalize_ordena_y_quita_duplicados():
    base = pd.Timestamp("2024-01-01", tz="UTC")
    df = pd.DataFrame({
        "ts": [base + pd.Timedelta(days=2), base, base],
        "open": [3, 1, 1], "high": [3, 1, 1], "low": [3, 1, 1],
        "close": [3, 1, 99], "volume": [1, 1, 1],
        "ingested_at": [base, base, base + pd.Timedelta(hours=1)],
    })
    out = schema.normalize(df)
    assert len(out) == 2
    assert out["ts"].is_monotonic_increasing
    # Ante duplicado, gana la ingesta más reciente.
    assert out.loc[0, "close"] == 99


def test_normalize_exige_columnas():
    with pytest.raises(ValueError, match="faltan columnas"):
        schema.normalize(pd.DataFrame({"ts": [1], "close": [2]}))


def test_timeframe_delta():
    assert schema.timeframe_delta("1d") == pd.Timedelta(days=1)
    assert schema.timeframe_delta("4h") == pd.Timedelta(hours=4)
    with pytest.raises(ValueError):
        schema.timeframe_delta("3s")
