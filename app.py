import json
import os
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st


def parse_keywords(raw: str):
    if not raw:
        return []
    return [k.strip() for k in raw.split(",") if k.strip()]


def build_row_text(df: pd.DataFrame, columns: list[str] | None):
    if columns:
        missing = [c for c in columns if c not in df.columns]
        if missing:
            st.error(f"Columns not found: {', '.join(missing)}")
            return None
        cols = columns
    else:
        cols = list(df.columns)
    return df[cols].astype(str).agg(" ".join, axis=1)


def match_keywords(series: pd.Series, keywords: list[str], mode: str):
    if not keywords:
        default = False if mode == "any" else True
        return pd.Series([default] * len(series), index=series.index)

    lowered = series.str.lower()
    kws = [k.lower() for k in keywords]

    if mode == "any":
        mask = pd.Series([False] * len(series), index=series.index)
        for k in kws:
            mask = mask | lowered.str.contains(k, na=False, regex=False)
        return mask

    mask = pd.Series([True] * len(series), index=series.index)
    for k in kws:
        mask = mask & lowered.str.contains(k, na=False, regex=False)
    return mask


def resolve_api_key(input_value: str):
    if input_value and input_value.strip():
        return input_value.strip()
    return os.getenv("OPENAI_API_KEY", "").strip()


def default_ai_columns(df: pd.DataFrame):
    preferred = ["Job Title", "Company", "Source", "제목", "회사", "내용"]
    cols = [c for c in preferred if c in df.columns]
    if cols:
        return cols
    non_link_cols = [c for c in df.columns if "link" not in c.lower() and "url" not in c.lower()]
    if non_link_cols:
        return non_link_cols
    return list(df.columns)


def clean_json_text(text: str):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def parse_ai_results(raw_text: str):
    cleaned = clean_json_text(raw_text)
    parsed = json.loads(cleaned)
    if isinstance(parsed, dict):
        return parsed.get("results", [])
    if isinstance(parsed, list):
        return parsed
    return []


def normalize_decision(value):
    text = str(value).strip().lower()
    keep_tokens = {"keep", "pass", "include", "포함", "유지", "통과"}
    drop_tokens = {"drop", "reject", "exclude", "제외", "불합격", "탈락"}
    if text in keep_tokens:
        return True
    if text in drop_tokens:
        return False
    return None


def run_ai_filter(df: pd.DataFrame, columns: list[str], user_prompt: str, model: str, api_key: str, batch_size: int):
    try:
        from openai import OpenAI
    except ImportError:
        return None, None, "`openai` 패키지가 없습니다. `pip install -r requirements.txt` 후 다시 실행하세요."

    missing = [c for c in columns if c not in df.columns]
    if missing:
        return None, None, f"AI 판정 컬럼을 찾을 수 없습니다: {', '.join(missing)}"

    client = OpenAI(api_key=api_key)
    keep_flags = [None] * len(df)
    reasons = [""] * len(df)
    progress = st.progress(0, text="AI 필터링 준비 중...")

    system_prompt = (
        "You classify job postings. "
        "Return JSON only. "
        "For each row_id output decision KEEP or DROP and short reason in Korean."
    )

    for start in range(0, len(df), batch_size):
        end = min(start + batch_size, len(df))
        chunk = []
        for row_id in range(start, end):
            row = df.iloc[row_id]
            fields = {}
            for col in columns:
                value = row[col]
                fields[col] = "" if pd.isna(value) else str(value)
            chunk.append({"row_id": row_id, "fields": fields})

        user_message = (
            "아래 규칙으로 채용 공고를 필터링해 주세요.\n"
            f"규칙:\n{user_prompt}\n\n"
            "결과 형식(JSON):\n"
            '{"results":[{"row_id":0,"decision":"KEEP","reason":"한 줄 이유"}]}\n\n'
            f"rows:\n{json.dumps(chunk, ensure_ascii=False)}"
        )

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content or not content.strip():
                progress.empty()
                return None, None, "AI 응답이 비어 있습니다. 배치 크기를 낮추거나 다시 시도해 주세요."
            items = parse_ai_results(content)

        except Exception as exc:
            progress.empty()
            return None, None, f"AI 요청 실패: {exc}"

        batch_seen = set()
        for item in items:
            try:
                row_id = int(item.get("row_id"))
            except Exception:
                continue
            if row_id < 0 or row_id >= len(df):
                continue
            normalized = normalize_decision(item.get("decision", ""))
            if normalized is None:
                continue
            keep_flags[row_id] = normalized
            reasons[row_id] = str(item.get("reason", "")).strip()
            batch_seen.add(row_id)

        expected_batch = set(range(start, end))
        missing_ids = [i for i in expected_batch if i not in batch_seen]
        if missing_ids:
            progress.empty()
            return None, None, f"AI 응답 형식이 불완전합니다. 누락 row_id: {len(missing_ids)}건"

        ratio = end / max(len(df), 1)
        progress.progress(ratio, text=f"AI 필터링 진행 중... ({end}/{len(df)})")

    progress.empty()
    unresolved = sum(v is None for v in keep_flags)
    if unresolved:
        return None, None, f"AI 판정 누락이 있습니다. 미판정: {unresolved}건"

    keep_series = pd.Series([bool(v) for v in keep_flags], index=df.index)
    return keep_series, pd.Series(reasons, index=df.index), None


st.set_page_config(page_title="Job Filter Tool", page_icon="🔍", layout="wide")

st.markdown(
    """
<style>
    .stApp {
        background-color: #f8f9fa;
    }
    .stButton>button {
        width: 100%;
        border-radius: 8px;
        height: 3em;
        background-color: #4CAF50;
        color: white;
        font-weight: bold;
        border: none;
        transition: 0.3s;
    }
    .stButton>button:hover {
        background-color: #45a049;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
</style>
""",
    unsafe_allow_html=True,
)


def main():
    st.title("🔍 Job Filtering Intelligence")
    st.markdown("채용 공고 데이터를 필터링해 필요한 공고만 추리세요.")
    st.divider()

    with st.sidebar:
        st.header("필터 설정")

        ai_enabled = st.checkbox("AI 필터 사용", value=False)
        fallback_to_all_if_empty = False
        if ai_enabled:
            fallback_to_all_if_empty = st.checkbox(
                "키워드 결과 0건이면 AI를 전체 데이터에 적용",
                value=True,
            )

        st.divider()

        include_raw = st.text_area("포함 키워드 (쉼표 구분)", placeholder="ex) 파이썬, 데이터, 분석")
        include_mode = st.radio(
            "포함 모드",
            ["any", "all"],
            index=0,
            help="'any'는 하나라도 포함, 'all'은 모두 포함",
        )

        st.divider()

        exclude_raw = st.text_area("제외 키워드 (쉼표 구분)", placeholder="ex) 인턴, 계약직")
        exclude_mode = st.radio("제외 모드", ["any", "all"], index=0)

        st.divider()

        target_cols_raw = st.text_input("키워드 검색 컬럼 (비워두면 전체)", placeholder="ex) Job Title,Company")
        st.caption("키워드 매칭은 대/소문자를 구분하지 않습니다.")

        st.divider()

        api_key_input = ""
        ai_model = "gpt-4o-mini"
        ai_prompt = ""
        ai_cols_raw = ""
        ai_batch_size = 20
        ai_send_clicked = False

        if ai_enabled:
            st.subheader("AI 설정")
            api_key_input = st.text_input("OpenAI API Key", type="password", placeholder="sk-...")
            ai_model = st.selectbox("AI 모델", ["gpt-4o-mini", "gpt-4o"], index=0)
            ai_prompt = st.text_area(
                "AI 필터 프롬프트",
                placeholder="예: 데이터 분석 포지션만 KEEP. 영업/마케팅 중심이면 DROP.",
            )
            ai_cols_raw = st.text_input(
                "AI 판정 컬럼 (쉼표 구분)",
                placeholder="비워두면 Link/URL 제외 컬럼 자동 선택",
            )
            ai_batch_size = st.slider("AI 배치 크기", min_value=5, max_value=50, value=20, step=5)
            ai_send_clicked = st.button("프롬프트 보내기", type="primary", use_container_width=True)
            st.caption("API 키를 비워두면 `OPENAI_API_KEY` 환경변수를 사용합니다.")
            st.caption("AI 응답이 불안정하면 배치 크기를 5~10으로 낮춰보세요.")

    uploaded_file = st.file_uploader("엑셀 파일 업로드 (.xlsx)", type=["xlsx"])

    if not uploaded_file:
        st.info("엑셀 파일을 업로드하면 결과가 표시됩니다.")
        return

    try:
        df = pd.read_excel(uploaded_file)
    except Exception as exc:
        st.error(f"파일을 읽는 중 오류가 발생했습니다: {exc}")
        return

    search_cols = parse_keywords(target_cols_raw) if target_cols_raw else None
    include_kws = parse_keywords(include_raw)
    exclude_kws = parse_keywords(exclude_raw)

    row_text = build_row_text(df, search_cols)
    if row_text is None:
        return

    if include_kws:
        include_mask = match_keywords(row_text, include_kws, include_mode)
        include_match_count = int(include_mask.sum())
    else:
        include_mask = pd.Series([True] * len(df), index=df.index)
        include_match_count = len(df)

    if exclude_kws:
        exclude_mask = match_keywords(row_text, exclude_kws, exclude_mode)
    else:
        exclude_mask = pd.Series([False] * len(df), index=df.index)
    filtered_df = df[include_mask & ~exclude_mask].copy()

    use_ai = ai_enabled
    ai_input_df = filtered_df
    if use_ai and filtered_df.empty and fallback_to_all_if_empty:
        ai_input_df = df
        st.info("키워드 결과가 0건이라 AI 입력 대상을 전체 데이터로 자동 전환했습니다.")

    result_df = filtered_df
    cache_key = (
        uploaded_file.name,
        ai_enabled,
        fallback_to_all_if_empty,
        include_raw,
        include_mode,
        exclude_raw,
        exclude_mode,
        target_cols_raw,
        ai_model,
        ai_prompt,
        ai_cols_raw,
    )

    st.caption(f"포함 매칭 {include_match_count}건 / 제외 매칭 {int(exclude_mask.sum())}건")

    if use_ai:
        st.divider()
        st.subheader("AI 프롬프트 필터")

        api_key = resolve_api_key(api_key_input)

        if ai_send_clicked:
            st.session_state["ai_last_status"] = "running"
            st.session_state["ai_last_message"] = "프롬프트 전송 후 AI 필터링을 실행 중입니다."
            st.session_state["ai_last_cache_key"] = cache_key

            if ai_input_df.empty:
                st.session_state["ai_last_status"] = "failed"
                st.session_state["ai_last_message"] = "AI에 전달할 데이터가 없습니다. 키워드 조건을 완화해 주세요."
            elif not api_key:
                st.session_state["ai_last_status"] = "failed"
                st.session_state["ai_last_message"] = "API 키를 입력하거나 `OPENAI_API_KEY`를 설정해야 합니다."
            elif not ai_prompt.strip():
                st.session_state["ai_last_status"] = "failed"
                st.session_state["ai_last_message"] = "AI 필터 프롬프트를 입력해 주세요."
            else:
                ai_cols = parse_keywords(ai_cols_raw) if ai_cols_raw else default_ai_columns(ai_input_df)
                with st.spinner("AI 판정 실행 중..."):
                    ai_keep, ai_reason, ai_error = run_ai_filter(
                        ai_input_df,
                        ai_cols,
                        ai_prompt.strip(),
                        ai_model,
                        api_key,
                        ai_batch_size,
                    )
                if ai_error:
                    st.session_state["ai_last_status"] = "failed"
                    st.session_state["ai_last_message"] = ai_error
                    st.session_state["ai_last_cache_key"] = cache_key
                elif ai_keep is not None and ai_reason is not None:
                    ai_df = ai_input_df[ai_keep].copy()
                    ai_df["AI Decision Reason"] = ai_reason[ai_keep].values
                    st.session_state["ai_cache_key"] = cache_key
                    st.session_state["ai_result_df"] = ai_df
                    st.session_state["ai_used_columns"] = ai_cols
                    st.session_state["ai_last_status"] = "success"
                    st.session_state["ai_last_message"] = "프롬프트가 적용되어 AI 필터링이 완료되었습니다."
                    st.session_state["ai_last_cache_key"] = cache_key
                else:
                    st.session_state["ai_last_status"] = "failed"
                    st.session_state["ai_last_message"] = "AI 응답 처리에 실패했습니다."
                    st.session_state["ai_last_cache_key"] = cache_key

        status = st.session_state.get("ai_last_status", "idle")
        status_key = st.session_state.get("ai_last_cache_key")
        status_msg = st.session_state.get("ai_last_message", "")
        if status_key == cache_key and status == "success":
            st.success(status_msg)
        elif status_key == cache_key and status == "failed":
            st.error(status_msg)
        else:
            st.info("프롬프트 대기 중입니다. 사이드바에서 `프롬프트 보내기`를 눌러 적용하세요.")

        if st.session_state.get("ai_cache_key") == cache_key and "ai_result_df" in st.session_state:
            result_df = st.session_state["ai_result_df"]
            cols = st.session_state.get("ai_used_columns", [])
            if cols:
                st.caption(f"AI 적용 컬럼: {', '.join(cols)}")
        else:
            result_df = ai_input_df

        if not ai_send_clicked and ai_input_df.empty:
            st.warning("AI에 전달할 데이터가 없습니다. 키워드 조건을 완화해 주세요.")
        if not ai_send_clicked and not api_key:
            st.caption("API 키가 없으면 프롬프트를 보내도 AI 실행이 실패합니다.")
        if not ai_send_clicked and not ai_prompt.strip():
            st.caption("AI 프롬프트를 입력한 뒤 `프롬프트 보내기`를 눌러야 반영됩니다.")

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("전체 데이터", f"{len(df)} 건")
    with col2:
        st.metric("키워드 필터 결과", f"{len(filtered_df)} 건")
    with col3:
        st.metric("AI 입력 건수", f"{len(ai_input_df) if use_ai else '-'}")
    with col4:
        st.metric("최종 결과 건수", f"{len(result_df)} 건")
    with col5:
        reduction = ((len(df) - len(result_df)) / len(df) * 100) if len(df) > 0 else 0
        st.metric("최종 제외 비율", f"{reduction:.1f}%")

    st.divider()
    st.subheader("필터링 결과")

    if result_df.empty:
        st.warning("조건에 맞는 데이터가 없습니다.")
        return

    st.dataframe(result_df, use_container_width=True)

    output_name = Path(uploaded_file.name).stem + "_filtered.xlsx"
    towrap = BytesIO()
    with pd.ExcelWriter(towrap, engine="openpyxl") as writer:
        result_df.to_excel(writer, index=False)

    st.download_button(
        label="필터링된 엑셀 다운로드",
        data=towrap.getvalue(),
        file_name=output_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    main()
