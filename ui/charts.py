"""分时图：当日分钟线 + 背景中的前一交易日分钟线"""

import math
import os

import pandas as pd
from pyecharts import options as opts
from pyecharts.charts import Bar, Grid, Line
from pyecharts.globals import CurrentConfig

from ui.data import session_axis

# 内网环境可通过TI_UI_ECHARTS_HOST指向自建的echarts静态资源目录(需包含echarts.min.js)
CurrentConfig.ONLINE_HOST = os.environ.get('TI_UI_ECHARTS_HOST', 'https://cdn.jsdelivr.net/npm/echarts@6.0.0/dist/')

TODAY_COLOR = '#2563eb'
VWAP_COLOR = '#f59e0b'
PREV_COLOR = '#94a3b8'
UP_COLOR = '#e5484d'  # A股习惯：红涨绿跌
DOWN_COLOR = '#30a46c'


def _values(series: pd.Series, scale: float = 1.0, digits: int = 4) -> list:
    return [None if v is None or (isinstance(v, float) and math.isnan(v)) else round(v * scale, digits) for v in series]


def _volume_items(day: pd.DataFrame) -> list:
    items = []
    for o, c, v in zip(day['open'], day['close'], day['vol']):
        if pd.isna(v):
            items.append(None)
        else:
            items.append({'value': float(v), 'itemStyle': {'color': UP_COLOR if c >= o else DOWN_COLOR}})
    return items


def intraday_chart(
    today: pd.DataFrame,
    yesterday: pd.DataFrame | None,
    mode: str = 'price',
    title: str = '',
    today_label: str = '当日',
    prev_label: str = '前一交易日',
    height: int = 560,
) -> Grid:
    """mode='price'按价格绘制；mode='pct'把每天都换算为相对各自昨收的涨跌幅，便于比较走势形态"""
    axis = session_axis()
    pct = mode == 'pct'
    column, scale, digits = ('pct', 100, 3) if pct else ('close', 1, 3)
    ref_close = today.attrs.get('ref_close')

    price = Line().add_xaxis(axis)
    if yesterday is not None:
        price.add_yaxis(
            prev_label,
            _values(yesterday[column], scale, digits),
            symbol='none',
            is_connect_nones=True,
            z=1,
            linestyle_opts=opts.LineStyleOpts(color=PREV_COLOR, width=1.2, opacity=0.8),
            itemstyle_opts=opts.ItemStyleOpts(color=PREV_COLOR),
            areastyle_opts=opts.AreaStyleOpts(color=PREV_COLOR, opacity=0.12),
            label_opts=opts.LabelOpts(is_show=False),
        )

    if pct:
        baseline = 0
    elif ref_close is not None and not math.isnan(ref_close):
        baseline = round(ref_close, digits)
    else:
        baseline = None
    price.add_yaxis(
        today_label,
        _values(today[column], scale, digits),
        symbol='none',
        z=3,
        linestyle_opts=opts.LineStyleOpts(color=TODAY_COLOR, width=2),
        itemstyle_opts=opts.ItemStyleOpts(color=TODAY_COLOR),
        label_opts=opts.LabelOpts(is_show=False),
        markline_opts=(
            opts.MarkLineOpts(
                symbol='none',
                data=[opts.MarkLineItem(y=baseline, name='昨收')],
                linestyle_opts=opts.LineStyleOpts(color=UP_COLOR, type_='dashed', opacity=0.6),
                label_opts=opts.LabelOpts(
                    formatter='昨收' if pct else '昨收 {c}', position='insideStartTop', color=UP_COLOR
                ),
            )
            if baseline is not None
            else None
        ),
    )
    if not pct:
        price.add_yaxis(
            '均价',
            _values(today['vwap'], 1, digits),
            symbol='none',
            z=2,
            linestyle_opts=opts.LineStyleOpts(color=VWAP_COLOR, width=1, type_='dashed'),
            itemstyle_opts=opts.ItemStyleOpts(color=VWAP_COLOR),
            label_opts=opts.LabelOpts(is_show=False),
        )

    price.set_global_opts(
        title_opts=opts.TitleOpts(title=title, pos_left='center', title_textstyle_opts=opts.TextStyleOpts(font_size=14)),
        legend_opts=opts.LegendOpts(pos_top=34),
        tooltip_opts=opts.TooltipOpts(trigger='axis', axis_pointer_type='cross'),
        axispointer_opts=opts.AxisPointerOpts(is_show=True, link=[{'xAxisIndex': 'all'}]),
        xaxis_opts=opts.AxisOpts(
            type_='category',
            boundary_gap=False,
            axislabel_opts=opts.LabelOpts(is_show=False),
            axistick_opts=opts.AxisTickOpts(is_show=False),
            splitline_opts=opts.SplitLineOpts(is_show=False),
        ),
        yaxis_opts=opts.AxisOpts(
            is_scale=True,
            splitline_opts=opts.SplitLineOpts(is_show=True, linestyle_opts=opts.LineStyleOpts(opacity=0.3)),
            axislabel_opts=opts.LabelOpts(formatter='{value}%' if pct else '{value}'),
        ),
        datazoom_opts=[
            opts.DataZoomOpts(type_='inside', xaxis_index=[0, 1], range_start=0, range_end=100),
            opts.DataZoomOpts(type_='slider', xaxis_index=[0, 1], pos_bottom='2%', range_start=0, range_end=100),
        ],
    )

    volume = Bar().add_xaxis(axis)
    if yesterday is not None:
        volume.add_yaxis(
            prev_label + '成交量',
            _values(yesterday['vol'], 1, 0),
            xaxis_index=1,
            yaxis_index=1,
            z=1,
            gap='-100%',
            itemstyle_opts=opts.ItemStyleOpts(color=PREV_COLOR, opacity=0.35),
            label_opts=opts.LabelOpts(is_show=False),
        )
    volume.add_yaxis(
        today_label + '成交量',
        _volume_items(today),
        xaxis_index=1,
        yaxis_index=1,
        z=2,
        gap='-100%',
        label_opts=opts.LabelOpts(is_show=False),
    )
    volume.set_global_opts(
        legend_opts=opts.LegendOpts(is_show=False),
        xaxis_opts=opts.AxisOpts(
            type_='category',
            grid_index=1,
            axislabel_opts=opts.LabelOpts(interval=29),
            axistick_opts=opts.AxisTickOpts(is_show=False),
        ),
        yaxis_opts=opts.AxisOpts(grid_index=1, split_number=2, axislabel_opts=opts.LabelOpts(is_show=False)),
    )

    grid = Grid(init_opts=opts.InitOpts(width='100%', height=f'{height}px', bg_color='#ffffff'))
    grid.add(price, grid_opts=opts.GridOpts(pos_left='8%', pos_right='4%', pos_top=76, height='50%'))
    grid.add(volume, grid_opts=opts.GridOpts(pos_left='8%', pos_right='4%', pos_top='74%', height='14%'))
    return grid
