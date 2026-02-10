# Clinical Trial Watch

이 프로젝트는 ClinicalTrials.gov API를 사용하여 특정 임상시험의 변동 사항을 정기적으로 모니터링하고, 그 결과를 Quarto 기반의 웹사이트로 배포하는 시스템입니다.

## 주요 기능

- 정기 크롤링: ClinicalTrials.gov API v2를 사용하여 최신 임상 데이터를 가져옵니다.
- 상태 변화 감지: 이전 스냅샷과 비교하여 모집 현황(Recruitment Status), 단계(Phase), 예상 종료일(Primary Completion Date) 등의 주요 필드 변화를 추적합니다.
- 자동 배포: GitHub Actions를 통해 매일 정해진 시간에 작업을 수행하고, 변경 사항이 있을 경우 GitHub Pages에 업데이트된 리포트를 배포합니다.
- 브라우징: Quarto로 생성된 웹 페이지를 통해 현재 상태 summary와 전체 변경 이력을 확인할 수 있습니다.

## 프로젝트 구조

- `src/`: 핵심 로직 소스 코드
  - `crawler.py`: API 데이터 수집
  - `diff_engine.py`: 데이터 비교 및 리포트 생성
  - `main.py`: 전체 프로세스 코디네이션
- `data/`: 데이터 저장소
  - `snapshots/`: 각 임상의 최신 JSON 스냅샷
  - `history/`: 감지된 변경 이력
- `trials.yaml`: 모니터링할 임상 목록 설정
- `.github/workflows/daily-watch.yml`: 자동화 워크플로우

## 시작하기

이 프로젝트는 `pixi`를 사용하여 패키지를 관리합니다.

### 설치 및 실행

```bash
# 의존성 설치 및 환경 구축
pixi install

# 로컬에서 모니터링 스크립트 실행
pixi run python src/main.py

# Quarto 웹사이트 미리보기
quarto preview
```

### 모니터링 대상 일괄 추가 (CSV 활용)

`NCT Number`, `Study Title` 컬럼이 포함된 CSV 파일을 사용하여 특정 타겟에 임상시험을 일괄 추가할 수 있습니다.

```bashpixi run python src/update_trials_from_csv.py --target TIGIT --csv data/ctg-studies_tigit.csv
# CCR8 타겟에 CSV 데이터 추가
pixi run python src/update_trials_from_csv.py --target CCR8 --csv data/ctg-studies.csv

# 새 타겟(TIGIT) 생성 및 추가
pixi run python src/update_trials_from_csv.py --target TIGIT --csv data/ctg-studies_tigit.csv

# 옵션
#   --target, -t : 타겟 이름 (필수)
#   --csv, -c    : CSV 파일 경로 (기본값: data/ctg-studies.csv)
#   --replace    : 기존 trials 대체 (기본값: 추가)
```

## 기술 스택

- Language: Python 3.11+
- Dependency Management: Pixi
- Libraries: `requests`, `deepdiff`, `PyYAML`
- Visualization: Quarto, GitHub Pages
- Automation: GitHub Actions
