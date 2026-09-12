import pandas as pd
import pytest

from tbot.data.sources.synthetic import SyntheticSource


@pytest.fixture
def serie():
    """3 años de velas diarias sintéticas, reproducibles."""
    src = SyntheticSource(seed=7, mu=0.15, sigma=0.35, s0=100.0)
    return src.fetch_ohlcv("SYN/USD", "1d",
                           pd.Timestamp("2021-01-01", tz="UTC"),
                           pd.Timestamp("2024-01-01", tz="UTC"))


@pytest.fixture
def datos(serie):
    return {"SYN/USD": serie}
