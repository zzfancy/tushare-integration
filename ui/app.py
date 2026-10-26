"""分钟线行情展示与分析

在项目根目录运行：
    streamlit run ui/app.py
无数据库时可使用演示数据：
    TI_UI_DEMO=1 streamlit run ui/app.py
"""

import datetime
import os
import sys

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import data  # noqa: E402
from ui.charts import intraday_chart  # noqa: E402

CHART_HEIGHT = 560

st.set_page_config(page_title='分钟线行情分析', page_icon='📈', layout='wide')


@st.cache_resource(show_spinner='连接数据库...')
def get_source():
    return data.create_source()


@st.cache_data(ttl=300, show_spinner=False)
def get_codes(_source, key: str) -> pd.DataFrame:
    return _source.list_codes()


@st.cache_data(ttl=300, show_spinner=False)
def get_dates(_source, key: str, ts_code: str) -> list[datetime.date]:
    return _source.list_trade_dates(ts_code)


@st.cache_data(ttl=300, show_spinner='读取分钟线...')
def get_comparison(_source, key: str, ts_code: str, day: datetime.date, dates: tuple) -> dict:
    return data.load_comparison(_source, ts_code, day, list(dates))


def fmt_volume(v: float) -> str:
    if pd.isna(v):
        return '-'
    for unit, size in (('亿', 1e8), ('万', 1e4)):
        if abs(v) >= size:
            return f'{v / size:,.2f}{unit}'
    return f'{v:,.0f}'


def fmt_pct(v: float) -> str:
    return '-' if pd.isna(v) else f'{v * 100:+.2f}%'


def shift_day(dates: list[datetime.date], step: int):
    current = st.session_state.get('day')
    if current not in dates:
        return
    index = min(max(dates.index(current) + step, 0), len(dates) - 1)
    st.session_state['day'] = dates[index]


def render_metrics(today: dict, yesterday: dict):
    cols = st.columns(4) + st.columns(4)
    cols[0].metric('最新价', f"{today['close']:.2f}", f"{today['change']:+.2f} ({fmt_pct(today['pct_change'])})",
                   delta_color='inverse')  # A股红涨绿跌
    cols[1].metric('最高', f"{today['high']:.2f}", fmt_pct(today['high'] / today['ref_close'] - 1),
                   delta_color='inverse')
    cols[2].metric('最低', f"{today['low']:.2f}", fmt_pct(today['low'] / today['ref_close'] - 1),
                   delta_color='inverse')
    cols[3].metric('昨收', f"{today['ref_close']:.2f}")
    cols[4].metric('均价(VWAP)', f"{today['vwap']:.2f}")
    cols[5].metric('振幅', fmt_pct(today['amplitude']).lstrip('+'),
                   f"{fmt_pct(today['amplitude'] - yesterday['amplitude'])} 较前日" if yesterday else None,
                   delta_color='off')
    vol_delta = fmt_pct(today['vol'] / yesterday['vol'] - 1) if yesterday and yesterday['vol'] else None
    cols[6].metric('成交量', fmt_volume(today['vol']), f'{vol_delta} 较前日' if vol_delta else None, delta_color='off')
    amount_delta = fmt_pct(today['amount'] / yesterday['amount'] - 1) if yesterday and yesterday['amount'] else None
    cols[7].metric('成交额', fmt_volume(today['amount']), f'{amount_delta} 较前日' if amount_delta else None,
                   delta_color='off')


def render_code(source, key: str, ts_code: str, name: str, day: datetime.date, show_prev: bool, mode: str):
    dates = get_dates(source, key, ts_code)
    if day not in dates:
        st.info(f'{ts_code} 在 {day} 没有分钟线数据（可能停牌或尚未同步）。')
        return

    result = get_comparison(source, key, ts_code, day, tuple(dates))
    today, yesterday, prev_day = result['today'], result['yesterday'], result['prev_day']
    today_summary = data.day_summary(today)
    prev_summary = data.day_summary(yesterday) if yesterday is not None else {}
    if not today_summary:
        st.info(f'{ts_code} 在 {day} 没有有效的分钟线数据。')
        return

    render_metrics(today_summary, prev_summary)
    if prev_day is None:
        st.caption('没有更早的交易日数据，仅显示当日。')

    chart = intraday_chart(
        today,
        yesterday if show_prev else None,
        mode=mode,
        title=f'{ts_code} {name}  {day}',
        today_label=f'{day:%m-%d}',
        prev_label=f'{prev_day:%m-%d}' if prev_day else '前一交易日',
        height=CHART_HEIGHT,
    )
    components.html(chart.render_embed(), height=CHART_HEIGHT + 20)

    with st.expander('与前一交易日对比' + (f'（{prev_day}）' if prev_day else '')):
        if prev_summary:
            table = data.compare(today_summary, prev_summary)
            percent_rows = ['涨跌幅', '振幅']
            styled = table.copy().astype(object)
            for label in table.index:
                for column in table.columns:
                    value = table.loc[label, column]
                    if column == '变化率' or label in percent_rows:
                        styled.loc[label, column] = fmt_pct(value)
                    elif label in ('成交量', '成交额'):
                        styled.loc[label, column] = fmt_volume(value)
                    else:
                        styled.loc[label, column] = '-' if pd.isna(value) else f'{value:,.2f}'
            st.dataframe(styled)
        else:
            st.write('无前一交易日数据。')

    with st.expander('分钟线明细'):
        raw = result['raw']
        st.dataframe(raw, hide_index=True)
        st.download_button(
            '下载CSV',
            raw.to_csv(index=False).encode('utf-8-sig'),
            file_name=f'{ts_code}_{day:%Y%m%d}_1min.csv',
            mime='text/csv',
            key=f'download-{ts_code}',
        )


def main():
    st.title('📈 分钟线行情分析')

    try:
        source = get_source()
        key = source.describe()
        codes = get_codes(source, key)
    except Exception as e:
        st.error(f'无法读取 {data.TABLE_NAME} 表：{e}')
        st.caption('请检查项目根目录下 config.yaml 中的数据库配置，或使用 TI_UI_DEMO=1 体验演示数据。')
        st.stop()

    st.caption(f'数据源：{key}')
    if codes.empty:
        st.warning(f'{data.TABLE_NAME} 表中没有数据，请先运行 `python main.py run spider stock/quotes/stk_mins`。')
        st.stop()

    labels = {row.ts_code: f'{row.ts_code} {row.name}'.strip() for row in codes.itertuples()}

    with st.sidebar:
        selected = st.multiselect(
            '股票代码', options=list(labels), default=list(labels)[:1], format_func=labels.get,
            placeholder='输入代码或名称搜索',
        )
        if not selected:
            st.info('请选择至少一个股票代码。')
            st.stop()

        dates = sorted({d for code in selected for d in get_dates(source, key, code)})
        if not dates:
            st.warning('所选股票没有分钟线数据。')
            st.stop()
        if st.session_state.get('day') not in dates:
            st.session_state['day'] = dates[-1]

        left, right = st.columns(2)
        left.button('◀ 前一日', on_click=shift_day, args=(dates, -1), width='stretch',
                    disabled=st.session_state['day'] == dates[0])
        right.button('后一日 ▶', on_click=shift_day, args=(dates, 1), width='stretch',
                     disabled=st.session_state['day'] == dates[-1])
        day = st.selectbox('交易日', options=dates[::-1], key='day', format_func=lambda d: f'{d} ({d:%a})')

        show_prev = st.toggle('背景显示前一交易日', value=True)
        mode = st.radio(
            '纵轴', options=['price', 'pct'], horizontal=True,
            format_func={'price': '价格', 'pct': '涨跌幅%'}.get,
            help='涨跌幅模式下，两天均按各自的昨收归一化，便于比较走势形态',
        )
        if st.button('刷新数据', width='stretch'):
            st.cache_data.clear()
            st.rerun()

    if len(selected) == 1:
        render_code(source, key, selected[0], codes.set_index('ts_code').loc[selected[0], 'name'], day, show_prev, mode)
    else:
        names = codes.set_index('ts_code')['name']
        for tab, ts_code in zip(st.tabs([labels[c] for c in selected]), selected):
            with tab:
                render_code(source, key, ts_code, names.get(ts_code, ''), day, show_prev, mode)


main()
