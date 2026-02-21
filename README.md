# 구인 공고 필터 도구

엑셀(.xlsx) 파일에서 포함/제외 키워드로 공고를 필터링하는 간단한 스크립트입니다.

## 설치

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

## 사용법

### 1) 컬럼 목록 확인

```bash
python filter_jobs.py --input "c:\\Users\\종이\\Downloads\\job_crawl_results_2026-02-14 (1).xlsx" --list-columns
```

### 2) 필터링 실행

```bash
python filter_jobs.py ^
  --input "c:\\Users\\종이\\Downloads\\job_crawl_results_2026-02-14 (1).xlsx" ^
  --output "c:\\Users\\종이\\Downloads\\job_crawl_filtered.xlsx" ^
  --include "데이터,분석,Python" ^
  --exclude "인턴,계약직,프리랜서" ^
  --columns "제목,회사,내용"
```

## Streamlit 앱 실행

```bash
streamlit run app.py
```

브라우저에서 앱을 열고 엑셀 파일을 업로드하면 필터링 결과를 바로 다운로드할 수 있습니다.

## OpenAI API 연결 (프롬프트 필터)

앱 사이드바에서 `AI 프롬프트 필터 사용`을 켠 뒤 아래 둘 중 하나로 API 키를 설정합니다.

### 방법 1) 앱에 직접 입력

- `OpenAI API Key` 입력칸에 `sk-...` 키를 붙여 넣기

### 방법 2) 환경변수 사용

PowerShell:

```powershell
$env:OPENAI_API_KEY="sk-..."
streamlit run app.py
```

앱에서 `AI 필터 프롬프트`를 입력하고 `AI 필터 실행`을 누르면, GPT가 각 공고를 `KEEP/DROP`으로 판정해서 최종 결과에 반영합니다.

## 실행 방식 (앱)

- `키워드만`: 일반 포함/제외 필터만 적용
- `AI만`: 키워드와 무관하게 전체 공고를 AI 프롬프트로 필터링
- `키워드+AI`: 키워드 필터 결과를 다시 AI 프롬프트로 필터링

## 동작 규칙

- `--exclude` 키워드가 포함된 공고는 항상 제외됩니다.
- `--include`가 비어있으면 전체 공고가 대상입니다.
- 기본값은 대/소문자 구분 없이 매칭합니다.

## 옵션 요약

- `--include`: 포함 키워드(쉼표 구분)
- `--exclude`: 제외 키워드(쉼표 구분)
- `--include-mode`: `any` 또는 `all`
- `--exclude-mode`: `any` 또는 `all`
- `--columns`: 검색할 컬럼 목록(쉼표 구분, 기본: 전체 컬럼)
- `--output-csv`: 추가 CSV 출력 경로
- `--list-columns`: 컬럼 목록 출력 후 종료
