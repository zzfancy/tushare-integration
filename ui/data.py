"""stk_mins 分钟线数据读取与分析

本模块不依赖 Streamlit，方便单元测试。数据源有两种：
- StkMinsSource: 通过项目自身的 DBEngine 读取数据库中的 stk_mins 表（默认）
- DemoSource: 生成随机游走的演示数据，设置环境变量 TI_UI_DEMO=1 时使用，无需数据库
"""

import datetime
import os
import re
import zlib

import numpy as np
import pandas as pd
import yaml

TABLE_NAME = 'stk_mins'
BASIC_TABLE = 'stock_basic'
MINUTE_COLUMNS = ['ts_code', 'trade_time', 'open', 'high', 'low', 'close', 'vol', 'amount']

TS_CODE_PATTERN = re.compile(r'^[0-9A-Z]{6}\.[A-Z]{2,3}$')


def validate_ts_code(ts_code: str) -> str:
    # DBEngine只接受拼接好的SQL，这里必须严格校验，避免SQL注入
    if not isinstance(ts_code, str) or not TS_CODE_PATTERN.match(ts_code):
        raise ValueError(f'Invalid ts_code: {ts_code!r}')
    return ts_code


def session_axis() -> list[str]:
    """A股1分钟线的241个时间点：09:30(集合竞价) + 09:31~11:30 + 13:01~15:00"""
    labels = ['09:30']
    for start, end in (('09:31', '11:30'), ('13:01', '15:00')):
        for t in pd.date_range(f'2000-01-01 {start}', f'2000-01-01 {end}', freq='1min'):
            labels.append(t.strftime('%H:%M'))
    return labels


def _naive_local(series: pd.Series) -> pd.Series:
    series = pd.to_datetime(series)
    if series.dt.tz is not None:
        series = series.dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
    return series


def normalize_minutes(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=MINUTE_COLUMNS)
    df = df.copy()
    df['trade_time'] = _naive_local(df['trade_time'])
    for column in ['open', 'high', 'low', 'close', 'vol', 'amount']:
        df[column] = pd.to_numeric(df[column], errors='coerce').astype(float)
    return df.sort_values('trade_time').reset_index(drop=True)


def split_by_day(df: pd.DataFrame) -> dict[datetime.date, pd.DataFrame]:
    if df.empty:
        return {}
    return {day: group.reset_index(drop=True) for day, group in df.groupby(df['trade_time'].dt.date)}


def previous_trade_date(dates: list[datetime.date], day: datetime.date) -> datetime.date | None:
    """取day之前最近一个有数据的交易日，自动跳过周末、节假日与停牌日"""
    earlier = [d for d in dates if d < day]
    return max(earlier) if earlier else None


def align_to_session(day_df: pd.DataFrame, ref_close: float | None = None) -> pd.DataFrame:
    """把单日分钟线按HH:MM对齐到固定的241个时间点，缺失的分钟保留为NaN

    ref_close为参考价（通常是前一交易日收盘价），用于计算涨跌幅；缺失时使用当日第一根K线的开盘价
    """
    axis = session_axis()
    if day_df.empty:
        aligned = pd.DataFrame(index=pd.Index(axis, name='minute'), columns=MINUTE_COLUMNS[2:], dtype=float)
    else:
        keyed = day_df.assign(minute=day_df['trade_time'].dt.strftime('%H:%M'))
        keyed = keyed.drop_duplicates('minute', keep='last').set_index('minute')
        aligned = keyed[MINUTE_COLUMNS[2:]].reindex(axis)
        aligned.index.name = 'minute'

    if ref_close is None or not np.isfinite(ref_close) or ref_close == 0:
        first_open = aligned['open'].dropna()
        ref_close = float(first_open.iloc[0]) if not first_open.empty else np.nan

    cum_vol = aligned['vol'].fillna(0).cumsum()
    cum_amount = aligned['amount'].fillna(0).cumsum()
    aligned['vwap'] = (cum_amount / cum_vol.replace(0, np.nan)).where(aligned['close'].notna())
    aligned['pct'] = aligned['close'] / ref_close - 1
    aligned.attrs['ref_close'] = ref_close
    return aligned


def last_close(day_df: pd.DataFrame | None) -> float | None:
    if day_df is None or day_df.empty:
        return None
    closes = day_df['close'].dropna()
    return float(closes.iloc[-1]) if not closes.empty else None


def day_summary(aligned: pd.DataFrame) -> dict[str, float]:
    ref_close = aligned.attrs.get('ref_close', np.nan)
    bars = aligned.dropna(subset=['close'])
    if bars.empty:
        return {}
    high, low, close = bars['high'].max(), bars['low'].min(), float(bars['close'].iloc[-1])
    vol, amount = bars['vol'].sum(), bars['amount'].sum()
    return {
        'open': float(bars['open'].iloc[0]),
        'high': float(high),
        'low': float(low),
        'close': close,
        'ref_close': float(ref_close),
        'change': close - ref_close,
        'pct_change': close / ref_close - 1,
        'amplitude': (high - low) / ref_close,
        'vol': float(vol),
        'amount': float(amount),
        'vwap': float(amount / vol) if vol else np.nan,
        'bars': int(len(bars)),
    }


SUMMARY_LABELS = {
    'open': '开盘价',
    'high': '最高价',
    'low': '最低价',
    'close': '收盘价',
    'ref_close': '昨收(参考价)',
    'change': '涨跌额',
    'pct_change': '涨跌幅',
    'amplitude': '振幅',
    'vol': '成交量',
    'amount': '成交额',
    'vwap': '均价(VWAP)',
    'bars': 'K线数量',
}


def compare(today: dict[str, float], yesterday: dict[str, float]) -> pd.DataFrame:
    """当日与前一交易日的指标对比表"""
    rows = []
    for key, label in SUMMARY_LABELS.items():
        t, y = today.get(key, np.nan), yesterday.get(key, np.nan)
        diff = t - y
        ratio = t / y - 1 if key in ('vol', 'amount', 'vwap', 'close') and y else np.nan
        rows.append({'指标': label, '当日': t, '前一交易日': y, '差值': diff, '变化率': ratio})
    return pd.DataFrame(rows).set_index('指标')


class StkMinsSource(object):
    """通过项目的DBEngine读取stk_mins表"""

    def __init__(self, config_path: str = 'config.yaml'):
        # 延迟导入：演示模式和单元测试不需要数据库驱动
        from tushare_integration.db_engine import DatabaseEngineFactory
        from tushare_integration.settings import TushareIntegrationSettings

        settings = TushareIntegrationSettings.model_validate(
            yaml.safe_load(open(config_path, 'r', encoding='utf-8').read())
        )
        self.db_name = settings.database.db_name
        self.engine = DatabaseEngineFactory.create(settings)
        self.to_date = self.engine.functions.get('to_date', 'to_date')

    def describe(self) -> str:
        return f'{self.db_name}.{TABLE_NAME}'

    def list_codes(self) -> pd.DataFrame:
        codes = self.engine.query_df(f'SELECT DISTINCT ts_code FROM {self.db_name}.{TABLE_NAME}')
        try:
            names = self.engine.query_df(f'SELECT ts_code, name FROM {self.db_name}.{BASIC_TABLE}')
            codes = codes.merge(names, on='ts_code', how='left')
        except Exception:
            codes['name'] = ''
        codes['name'] = codes['name'].fillna('')
        return codes.sort_values('ts_code').reset_index(drop=True)

    def list_trade_dates(self, ts_code: str) -> list[datetime.date]:
        df = self.engine.query_df(
            f"""
                SELECT DISTINCT {self.to_date}(trade_time) AS trade_date
                FROM {self.db_name}.{TABLE_NAME}
                WHERE ts_code = '{validate_ts_code(ts_code)}'"""
        )
        if df.empty:
            return []
        return sorted(pd.to_datetime(df['trade_date']).dt.date.unique().tolist())

    def load_minutes(self, ts_code: str, start_date: datetime.date, end_date: datetime.date) -> pd.DataFrame:
        start = start_date.strftime('%Y-%m-%d 00:00:00')
        end = (end_date + datetime.timedelta(days=1)).strftime('%Y-%m-%d 00:00:00')
        df = self.engine.query_df(
            f"""
                SELECT {', '.join(MINUTE_COLUMNS)}
                FROM {self.db_name}.{TABLE_NAME}
                WHERE ts_code = '{validate_ts_code(ts_code)}'
                  AND trade_time >= '{start}' AND trade_time < '{end}'
                ORDER BY trade_time"""
        )
        return normalize_minutes(df)


class DemoSource(object):
    """随机游走演示数据，与StkMinsSource接口一致"""

    CODES = [
        ('000001.SZ', '平安银行', 11.5),
        ('600519.SH', '贵州茅台', 1450.0),
        ('300750.SZ', '宁德时代', 260.0),
        ('601318.SH', '中国平安', 52.0),
    ]

    def __init__(self, days: int = 15, today: datetime.date | None = None):
        today = today or datetime.date.today()
        self.dates = [d.date() for d in pd.bdate_range(end=today, periods=days)]

    def describe(self) -> str:
        return '演示数据 (TI_UI_DEMO=1)'

    def list_codes(self) -> pd.DataFrame:
        return pd.DataFrame([(c, n) for c, n, _ in self.CODES], columns=['ts_code', 'name'])

    def list_trade_dates(self, ts_code: str) -> list[datetime.date]:
        validate_ts_code(ts_code)
        return list(self.dates)

    def load_minutes(self, ts_code: str, start_date: datetime.date, end_date: datetime.date) -> pd.DataFrame:
        base = {c: p for c, _, p in self.CODES}.get(validate_ts_code(ts_code), 10.0)
        price, frames = base, []
        for day in self.dates:
            frame, price = self._day(ts_code, day, price)
            if start_date <= day <= end_date:
                frames.append(frame)
        return normalize_minutes(pd.concat(frames) if frames else pd.DataFrame())

    @staticmethod
    def _day(ts_code: str, day: datetime.date, prev_close: float) -> tuple[pd.DataFrame, float]:
        rng = np.random.default_rng(zlib.crc32(f'{ts_code}{day}'.encode()))
        axis = session_axis()
        n = len(axis)
        drift = rng.normal(0, 0.00008)
        returns = rng.normal(drift, 0.0009, n)
        returns[0] = rng.normal(0, 0.004)  # 开盘跳空
        close = prev_close * np.exp(np.cumsum(returns))
        open_ = np.concatenate([[prev_close], close[:-1]])
        spread = np.abs(rng.normal(0, 0.0006, n)) * close
        high = np.maximum(open_, close) + spread
        low = np.minimum(open_, close) - spread
        # U型成交量：开盘和收盘放量
        shape = 1 + 2.5 * np.exp(-np.arange(n) / 15) + 1.5 * np.exp(-(n - 1 - np.arange(n)) / 12)
        vol = np.round(rng.lognormal(0, 0.4, n) * shape * 2e7 / prev_close / 100) * 100
        times = [pd.Timestamp(f'{day} {t}') for t in axis]
        frame = pd.DataFrame(
            {
                'ts_code': ts_code,
                'trade_time': times,
                'open': open_.round(2),
                'high': high.round(2),
                'low': low.round(2),
                'close': close.round(2),
                'vol': vol,
                'amount': (vol * close).round(2),
            }
        )
        return frame, float(close[-1])


def create_source():
    if os.environ.get('TI_UI_DEMO', '').lower() in ('1', 'true', 'yes'):
        return DemoSource()
    return StkMinsSource(os.environ.get('TI_UI_CONFIG', 'config.yaml'))


def load_comparison(source, ts_code: str, day: datetime.date, dates: list[datetime.date]) -> dict:
    """读取所选交易日、前一交易日以及再前一日（用于前一交易日的涨跌幅基准）的分钟线并对齐"""
    prev_day = previous_trade_date(dates, day)
    prev2_day = previous_trade_date(dates, prev_day) if prev_day else None
    days = split_by_day(source.load_minutes(ts_code, prev2_day or prev_day or day, day))

    today_raw = days.get(day, pd.DataFrame(columns=MINUTE_COLUMNS))
    prev_raw = days.get(prev_day) if prev_day else None
    prev_close = last_close(prev_raw)

    today = align_to_session(today_raw, prev_close)
    yesterday = align_to_session(prev_raw, last_close(days.get(prev2_day))) if prev_raw is not None else None
    return {
        'day': day,
        'prev_day': prev_day,
        'raw': today_raw,
        'today': today,
        'yesterday': yesterday,
    }
