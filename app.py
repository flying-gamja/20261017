from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

DATA_PATH = Path(__file__).parent / "seoul_temperature.csv"
COL_DATE, COL_MEAN, COL_MIN, COL_MAX = "날짜", "평균기온(℃)", "최저기온(℃)", "최고기온(℃)"
COL_RANGE = "일교차(℃)"
MA_WINDOW = 5

st.set_page_config(page_title="서울 기온 분석", page_icon="🌡️", layout="wide")


@st.cache_data
def load_data(source) -> pd.DataFrame:
    """CSV를 읽고 날짜 앞의 탭/공백 제거, 결측 행 정리, 파생 컬럼 생성."""
    try:
        df = pd.read_csv(source, encoding="utf-8-sig")
    except UnicodeDecodeError:
        if hasattr(source, "seek"):
            source.seek(0)
        df = pd.read_csv(source, encoding="cp949")

    df.columns = df.columns.str.strip()
    df[COL_DATE] = pd.to_datetime(df[COL_DATE].astype(str).str.strip(), errors="coerce")
    df = df.dropna(subset=[COL_DATE]).copy()  # 날짜가 비어 있는 행 제거
    df["연도"] = df[COL_DATE].dt.year
    df["월"] = df[COL_DATE].dt.month
    df[COL_RANGE] = df[COL_MAX] - df[COL_MIN]  # 일교차
    return df


@st.cache_data
def yearly_summary(df: pd.DataFrame) -> pd.DataFrame:
    """연도별 평균기온, 관측일수 (빠진 연도는 NaN 행으로 채움)."""
    g = df.groupby("연도")[COL_MEAN]
    out = pd.DataFrame({"평균기온": g.mean(), "관측일수": g.count()})
    out = out.reindex(range(out.index.min(), out.index.max() + 1))
    out["관측일수"] = out["관측일수"].fillna(0).astype(int)
    return out


# ---------------------------------------------------------------- 데이터 로드
if DATA_PATH.exists():
    raw = load_data(DATA_PATH)
else:
    uploaded = st.sidebar.file_uploader("seoul_temperature.csv 업로드", type="csv")
    if uploaded is None:
        st.info("app.py와 같은 폴더에 seoul_temperature.csv를 두거나 CSV를 업로드하세요.")
        st.stop()
    raw = load_data(uploaded)

summary_all = yearly_summary(raw)

# ---------------------------------------------------------------- 사이드바
st.sidebar.header("설정")
exclude_partial = st.sidebar.checkbox(
    "관측일수가 부족한 연도 제외",
    value=True,
    help="연간 평균이 왜곡되는 것을 막기 위해 관측일수가 기준보다 적은 연도를 제외합니다.",
)
min_days = st.sidebar.number_input(
    "연도별 최소 관측일수", 1, 366, 300, disabled=not exclude_partial
)

valid = summary_all["관측일수"] >= (min_days if exclude_partial else 1)
summary = summary_all.copy()
summary.loc[~valid, ["평균기온"]] = float("nan")

# 이동평균은 전체 기간에서 계산 → 구간 시작부에서도 값이 끊기지 않음
summary["이동평균"] = summary["평균기온"].rolling(MA_WINDOW, min_periods=MA_WINDOW).mean()

valid_years = summary.index[valid]
y_min, y_max = int(valid_years.min()), int(valid_years.max())

start, end = st.sidebar.slider(
    "연도 범위", min_value=y_min, max_value=y_max, value=(y_min, y_max), step=1
)

# ---------------------------------------------------------------- 선택 구간 필터
view = summary.loc[start:end]
view_valid = view[valid.loc[start:end]]
daily = raw[raw["연도"].isin(view_valid.index)]

# ---------------------------------------------------------------- 본문
st.title("🌡️ 서울 연도별 기온 추이")
st.caption(f"선택 구간: {start}년 ~ {end}년 ({len(view_valid)}개 연도)")

# ---- 1) 연평균 + 5년 이동평균
fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=view.index,
        y=view["평균기온"],
        mode="lines+markers",
        name="연평균기온",
        line=dict(color="#4C78A8", width=1.5),
        marker=dict(size=5),
        hovertemplate="%{x}년<br>연평균 %{y:.2f}℃<extra></extra>",
    )
)
fig.add_trace(
    go.Scatter(
        x=view.index,
        y=view["이동평균"],
        mode="lines",
        name=f"{MA_WINDOW}년 이동평균",
        line=dict(color="#E45756", width=3),
        hovertemplate="%{x}년<br>이동평균 %{y:.2f}℃<extra></extra>",
    )
)
fig.update_layout(
    xaxis_title="연도",
    yaxis_title="평균기온 (℃)",
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=10, r=10, t=40, b=10),
    height=480,
)
st.plotly_chart(fig, use_container_width=True)

# ---- 요약 지표
if daily.empty:
    st.warning("선택한 구간에 유효한 데이터가 없습니다.")
    st.stop()

hot = daily.loc[daily[COL_MAX].idxmax()]
cold = daily.loc[daily[COL_MIN].idxmin()]

c1, c2, c3 = st.columns(3)
c1.metric("평균기온", f"{daily[COL_MEAN].mean():.2f} ℃")
c2.metric("최고기온", f"{hot[COL_MAX]:.1f} ℃", help="선택 구간 일별 최고기온 중 최댓값")
c2.caption(f"관측일: {hot[COL_DATE]:%Y-%m-%d}")
c3.metric("최저기온", f"{cold[COL_MIN]:.1f} ℃", help="선택 구간 일별 최저기온 중 최솟값")
c3.caption(f"관측일: {cold[COL_DATE]:%Y-%m-%d}")

# ---- 2) 월별 히트맵
st.subheader("월별 평균기온 히트맵")
heat = (
    daily.pivot_table(index="연도", columns="월", values=COL_MEAN, aggfunc="mean")
    .reindex(columns=range(1, 13))
)
heat_fig = go.Figure(
    go.Heatmap(
        z=heat.values,
        x=heat.columns,
        y=heat.index,
        colorscale="RdYlBu_r",
        colorbar=dict(title="℃"),
        hovertemplate="%{y}년 %{x}월<br>평균 %{z:.1f}℃<extra></extra>",
    )
)
heat_fig.update_layout(
    xaxis=dict(title="월", tickmode="array", tickvals=list(range(1, 13)), side="top"),
    yaxis=dict(title="연도", autorange="reversed", dtick=10),
    margin=dict(l=10, r=10, t=40, b=10),
    height=max(500, min(1100, 7 * len(heat) + 120)),
)
st.plotly_chart(heat_fig, use_container_width=True)

# ---- 3) 최고기온 상위 10일 / 최저기온 하위 10일
st.subheader("극값 상위 10일")
left, right = st.columns(2)

top_hot = (
    daily.nlargest(10, COL_MAX)[[COL_DATE, COL_MAX, COL_MIN, COL_MEAN]]
    .assign(**{COL_DATE: lambda d: d[COL_DATE].dt.strftime("%Y-%m-%d")})
    .reset_index(drop=True)
)
top_hot.index = top_hot.index + 1
top_hot.index.name = "순위"

top_cold = (
    daily.nsmallest(10, COL_MIN)[[COL_DATE, COL_MIN, COL_MAX, COL_MEAN]]
    .assign(**{COL_DATE: lambda d: d[COL_DATE].dt.strftime("%Y-%m-%d")})
    .reset_index(drop=True)
)
top_cold.index = top_cold.index + 1
top_cold.index.name = "순위"

with left:
    st.markdown("**🔥 최고기온 상위 10일**")
    st.dataframe(top_hot, use_container_width=True)
with right:
    st.markdown("**🥶 최저기온 하위 10일**")
    st.dataframe(top_cold, use_container_width=True)

# ---- 4) 연도별 평균 일교차
st.subheader("연도별 평균 일교차")
range_by_year = daily.groupby("연도")[COL_RANGE].mean()

range_fig = go.Figure(
    go.Scatter(
        x=range_by_year.index,
        y=range_by_year.values,
        mode="lines+markers",
        name="평균 일교차",
        line=dict(color="#54A24B", width=2),
        marker=dict(size=5),
        hovertemplate="%{x}년<br>평균 일교차 %{y:.2f}℃<extra></extra>",
    )
)
range_fig.update_layout(
    xaxis_title="연도",
    yaxis_title="평균 일교차 (℃)",
    hovermode="x unified",
    margin=dict(l=10, r=10, t=30, b=10),
    height=420,
)
st.plotly_chart(range_fig, use_container_width=True)

# ---- 연도별 데이터
with st.expander("연도별 데이터 보기"):
    table = view_valid[["평균기온", "이동평균", "관측일수"]].copy()
    table["평균 일교차"] = range_by_year
    table = table.round(2)
    table.index.name = "연도"
    st.dataframe(table, use_container_width=True)
