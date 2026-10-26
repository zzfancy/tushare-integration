import datetime
import json

import numpy as np
import pandas as pd
import pytest

from ui import data
from ui.charts import intraday_chart


def make_day(day: str, minutes: list[str], close: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            'ts_code': '000001.SZ',
            'trade_time': [pd.Timestamp(f'{day} {m}') for m in minutes],
            'open': close,
            'high': [c + 0.1 for c in close],
            'low': [c - 0.1 for c in close],
            'close': close,
            'vol': [100.0] * len(close),
            'amount': [c * 100 for c in close],
        }
    )


def test_session_axis():
    axis = data.session_axis()
    assert len(axis) == 241
    assert axis[:2] == ['09:30', '09:31'] and axis[-1] == '15:00'
    assert '11:30' in axis and '13:01' in axis and '12:00' not in axis and '13:00' not in axis


def test_validate_ts_code():
    assert data.validate_ts_code('600519.SH') == '600519.SH'
    for bad in ["000001.SZ' OR '1'='1", '000001', '', None]:
        with pytest.raises(ValueError):
            data.validate_ts_code(bad)


def test_previous_trade_date_skips_gaps():
    dates = [datetime.date(2024, 1, 4), datetime.date(2024, 1, 5), datetime.date(2024, 1, 8)]
    assert data.previous_trade_date(dates, datetime.date(2024, 1, 8)) == datetime.date(2024, 1, 5)
    assert data.previous_trade_date(dates, datetime.date(2024, 1, 4)) is None


def test_align_with_missing_minutes():
    day = make_day('2024-01-08', ['09:30', '09:31', '09:33'], [10.0, 10.5, 11.0])
    aligned = data.align_to_session(data.normalize_minutes(day), ref_close=10.0)
    assert len(aligned) == 241
    assert np.isnan(aligned.loc['09:32', 'close'])
    assert aligned.loc['09:33', 'pct'] == pytest.approx(0.1)
    assert aligned.loc['09:33', 'vwap'] == pytest.approx(10.5)


def test_align_without_ref_close_uses_first_open():
    aligned = data.align_to_session(make_day('2024-01-08', ['09:30'], [8.0]))
    assert aligned.attrs['ref_close'] == 8.0


def test_tz_aware_trade_time_is_localised():
    day = make_day('2024-01-08', ['09:30'], [10.0])
    day['trade_time'] = day['trade_time'].dt.tz_localize('Asia/Shanghai').dt.tz_convert('UTC')
    assert data.normalize_minutes(day)['trade_time'].iloc[0] == pd.Timestamp('2024-01-08 09:30')


def test_summary_and_compare():
    today = data.align_to_session(make_day('2024-01-08', ['09:30', '15:00'], [10.0, 11.0]), ref_close=10.0)
    prev = data.align_to_session(make_day('2024-01-05', ['09:30', '15:00'], [9.0, 10.0]), ref_close=9.0)
    s = data.day_summary(today)
    assert s['close'] == 11.0 and s['pct_change'] == pytest.approx(0.1)
    assert s['high'] == pytest.approx(11.1) and s['low'] == pytest.approx(9.9)
    assert s['vwap'] == pytest.approx(10.5) and s['bars'] == 2
    table = data.compare(s, data.day_summary(prev))
    assert table.loc['收盘价', '差值'] == pytest.approx(1.0)


def test_demo_source_comparison():
    source = data.DemoSource(days=5, today=datetime.date(2024, 1, 12))
    dates = source.list_trade_dates('600519.SH')
    result = data.load_comparison(source, '600519.SH', dates[-1], dates)
    assert result['prev_day'] == dates[-2]
    assert result['today']['close'].notna().sum() == 241
    # 当日参考价等于前一交易日收盘价
    assert result['today'].attrs['ref_close'] == data.day_summary(result['yesterday'])['close']

    first = data.load_comparison(source, '600519.SH', dates[0], dates)
    assert first['prev_day'] is None and first['yesterday'] is None


@pytest.mark.parametrize('mode', ['price', 'pct'])
def test_chart_contains_both_days(mode):
    source = data.DemoSource(days=3, today=datetime.date(2024, 1, 12))
    dates = source.list_trade_dates('000001.SZ')
    result = data.load_comparison(source, '000001.SZ', dates[-1], dates)
    options = json.loads(intraday_chart(result['today'], result['yesterday'], mode=mode,
                                        today_label='T', prev_label='P').dump_options())
    names = [s['name'] for s in options['series']]
    assert {'T', 'P', 'T成交量', 'P成交量'} <= set(names)
    assert ('均价' in names) == (mode == 'price')
    assert len(options['xAxis']) == 2 and len(options['xAxis'][0]['data']) == 241

    only_today = json.loads(intraday_chart(result['today'], None, mode=mode, prev_label='P').dump_options())
    assert 'P' not in [s['name'] for s in only_today['series']]
