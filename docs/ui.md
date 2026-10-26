# 分钟线行情展示与分析

基于 Streamlit + pyecharts 的分钟线可视化界面，直接读取数据库中的 `stk_mins` 表（由 `stock/quotes/stk_mins` 任务同步）。

## 功能

- 侧边栏多选股票代码（支持代码/名称搜索），每个代码一个标签页
- 按交易日查看 1 分钟分时图，支持 ◀ / ▶ 切换前后交易日
- 当日走势在前景显示，**前一交易日**（自动跳过周末、节假日和停牌日）以灰色曲线和阴影显示在背景中，便于对比分析
- 均价线（VWAP）、昨收参考线；下方成交量柱（红涨绿跌），前一交易日成交量同样以灰色叠加在背景
- 纵轴可切换「价格」或「涨跌幅%」：涨跌幅模式下两天各自按昨收归一化，便于比较走势形态
- 指标卡：最新价、涨跌幅、最高/最低、振幅、均价、成交量/成交额（与前一交易日对比）
- 与前一交易日的指标对比表、分钟线明细及 CSV 下载

## 运行

```shell
# 安装额外依赖
pip install -r ui/requirements.txt

# 在项目根目录运行，数据库配置读取 config.yaml
streamlit run ui/app.py
```

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `TI_UI_CONFIG` | 配置文件路径，默认 `config.yaml` |
| `TI_UI_DEMO` | 设为 `1` 时使用随机生成的演示数据，无需数据库 |
| `TI_UI_ECHARTS_HOST` | echarts 静态资源地址（目录，需包含 `echarts.min.js`），默认使用 jsDelivr CDN，内网环境可指向自建地址 |

支持 ClickHouse、MySQL、Doris 三种数据库，复用项目中的 `DatabaseEngineFactory`。
