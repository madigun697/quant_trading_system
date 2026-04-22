# Quant 프로젝트 운영 규칙 한글 참고본

이 문서는 한국어 사용자를 위한 참고용 번역본입니다. 실제로 Codex 세션과 서브에이전트가 따라야 하는 공식 규칙은 루트의 `AGENTS.md`입니다. 규칙 해석이 충돌하면 항상 `AGENTS.md`를 우선합니다.

## 목적과 적용 범위

- 이 문서는 이 프로젝트에서 동작하는 모든 Codex 세션과 모든 서브에이전트가 따라야 하는 운영 규칙의 한국어 설명본입니다.
- 규칙 적용 범위는 루트 워크스페이스와 그 하위 프로젝트 전체이며, `cherry_quant_wikidocs/`도 포함됩니다.
- 커스텀 전문 프롬프트는 `agents/` 디렉터리에 있고, `spawn_agent(agent_type="worker")`와 함께 프롬프트 라이브러리처럼 사용합니다.
- Codex에서 커스텀 서브에이전트 실행이 안 되면 `~/.codex/config.toml`에서 멀티에이전트 기능을 켭니다.

```toml
[features]
multi_agent = true
```

## 서브에이전트 목록

| 에이전트 | 프롬프트 파일 | 주 사용 용도 |
| --- | --- | --- |
| `quant-trading-expert` | `agents/quant-trading-expert.md` | 퀀트 전략, 팩터, 백테스트, 리스크, 포트폴리오 로직 |
| `stock-chart-analyst` | `agents/stock-chart-analyst.md` | 캔들, 지표, 차트 패턴, 시각적 차트 리뷰 |
| `senior-backend-engineer-python` | `agents/senior-backend-engineer-python.md` | Python API, 데이터 파이프라인, 배치 작업, 백테스트 엔진 |
| `senior-frontend-engineer` | `agents/senior-frontend-engineer.md` | 대시보드, UI 상태, 상호작용, 프론트엔드 구조 |
| `ui-ux-designer` | `agents/ui-ux-designer.md` | 정보구조, 사용자 흐름, 레이아웃, 비주얼 방향성 |
| `paranoid-staff-engineer-reviewer` | `agents/paranoid-staff-engineer-reviewer.md` | 구현 후 리스크 중심 기술 리뷰 |
| `qa-engineer` | `agents/qa-engineer.md` | 회귀 검증, 시나리오 점검, 출시 준비도 확인 |

## 서브에이전트 선택 규약

1. 사용자가 특정 에이전트를 지정하지 않으면, 본격적인 작업 전에 가장 적합한 서브에이전트를 먼저 선택합니다.
2. 첫 번째 실질 응답에서 선택한 에이전트를 짧게 밝힙니다.
   예시: `Selected agent: senior-backend-engineer-python`
3. 기본 라우팅 규칙은 아래를 따릅니다.
   - 퀀트 전략, 팩터, 백테스트, 리스크, 포트폴리오 구성: `quant-trading-expert`
   - 캔들, 패턴, 보조지표, 차트 해석, 시각적 차트 리뷰: `stock-chart-analyst`
   - Python API, 데이터 파이프라인, 배치, 백테스트 엔진, 인프라 로직: `senior-backend-engineer-python`
   - 웹 UI, 대시보드, 코드 수준 상호작용 설계, 상태 관리: `senior-frontend-engineer`
   - 정보구조, 사용자 흐름, 화면 구조, 비주얼 방향성: `ui-ux-designer`
   - 규모가 크거나 위험한 변경 완료 후 리뷰: `paranoid-staff-engineer-reviewer`
   - 사용자 영향 검증 또는 회귀 확인: `qa-engineer`
4. 혼합 작업은 특별한 이유가 없으면 아래 순서를 따릅니다.
   - 도메인 전문가
   - 구현 엔지니어
   - 규모가 크거나 위험한 경우 리뷰어
   - 사용자 영향 검증을 위한 QA
5. 커스텀 전문 프롬프트는 모두 `spawn_agent(agent_type="worker")`로 실행합니다.
6. `explorer`는 읽기 전용 탐색에는 쓸 수 있지만, 전문 판단이나 구현 책임이 필요한 상황에서 전문 에이전트를 대체하면 안 됩니다.

## 공통 작업 절차

1. 수정 전에 먼저 탐색합니다. 코드, 문서, 설정, 제약을 읽고 이해한 뒤 변경합니다.
2. 탐색으로 해결할 수 없는 중요한 제품/구현/리스크 결정만 사용자에게 질문합니다.
3. 현재 디렉터리가 Git 저장소가 아니면 첫 추적 변경 전에 `git init`을 실행합니다.
4. Python 작업은 `uv` 기반으로 표준화합니다.
5. 요청을 완전히 해결하는 가장 작은 일관된 변경을 우선합니다.
6. 변경 후에는 관련 검증을 실행합니다. 우선 가장 좁고 유의미한 검증부터 실행하고, 위험도가 높으면 범위를 넓힙니다.
7. 아래 리뷰/QA 게이트 조건에 해당하면 반드시 통과시킵니다.
8. 논리적으로 완료된 작업 단위마다 즉시 커밋합니다.
9. 무엇을 바꿨는지, 어떻게 검증했는지, 무엇을 일부러 검증하지 않았는지 보고합니다.

## UV 규칙

- 이 프로젝트의 모든 Python 실행, 패키지 관리, 스크립트, 테스트, 툴링에는 이 규칙이 강제됩니다.
- `pyproject.toml`이 없고 Python 작업이 필요하면 `uv init`으로 시작합니다.
- 의존성 추가는 `uv add`를 사용합니다.
- 환경 동기화나 갱신은 `uv sync`를 사용합니다.
- Python 엔트리포인트, 스크립트, 테스트, 린트는 `uv run ...`으로 실행합니다.
- 프로젝트 Python 작업에서 bare `python`, `pip`, `pytest`, 임의 가상환경 관리는 사용하지 않습니다.
- 프론트엔드 전용 작업은 해당 생태계 기본 도구를 써도 되지만, 그 과정에 Python 헬퍼가 끼면 그 부분은 여전히 `uv`를 사용해야 합니다.

## Git 및 커밋 규칙

- 워크스페이스가 Git 저장소가 아니면 첫 추적 변경 전에 `git init`으로 초기화합니다.
- 긴 세션 마지막에 한 번만 커밋하지 말고, 논리적 작업 단위마다 커밋합니다.
- 현재 커밋과 관련 있는 파일만 스테이징합니다.
- 커밋 메시지 형식은 `type(scope): summary`를 사용합니다.
- 권장 커밋 타입은 `feat`, `fix`, `docs`, `refactor`, `test`, `chore`입니다.
- 사용자가 명시적으로 요청하지 않았다면 amend, reset, rebase, force-push, 기존 작업 폐기는 하지 않습니다.
- 내가 만들지 않은 관련 없는 변경을 되돌리지 않습니다.

## 리뷰 및 QA 게이트

### 필수 리뷰어 게이트

아래 중 하나라도 해당하면 최종 마무리 전에 `paranoid-staff-engineer-reviewer`를 거칩니다.

- 변경이 여러 파일에 걸치거나 새로운 구조를 도입한 경우
- 트레이딩 로직, 팩터 로직, 실행 로직, 리스크 로직이 바뀐 경우
- 데이터 모델, 스키마, 저장 계약, API 계약이 바뀐 경우
- 보안, 인증, 권한, 성능 민감 로직이 바뀐 경우
- 겉보기에 맞아 보여도 틀렸을 때 손실이 큰 경우

### 필수 QA 게이트

아래 중 하나라도 해당하면 최종 마무리 전에 `qa-engineer`를 거칩니다.

- 사용자에게 보이는 동작이 바뀐 경우
- UI 레이아웃, 흐름, 문구가 바뀐 경우
- 회귀 위험이 큰 경우
- 새로운 엔드포인트, 리포트, 내보내기, 계산 결과가 downstream 사용자에게 영향을 주는 경우
- 사용자가 테스트 커버리지, 검증, 출시 준비 확인을 명시적으로 요청한 경우

## 금지 사항

- 명시적 허가 없이 사용자 변경사항을 덮어쓰거나 폐기하지 않습니다.
- 사용자가 요청하지 않았다면 `git reset --hard`, `git checkout --` 같은 파괴적 Git 명령은 사용하지 않습니다.
- Python 작업에서 `uv`를 우회하지 않습니다.
- 검증을 건너뛰고도 검증했다고 말하지 않습니다.
- 선택한 에이전트의 소관 밖 영역에서 과도한 확신을 보이지 말고 적절한 전문 에이전트로 넘깁니다.
- 실제 전문 판단이 필요한데 `explorer`로 대신하지 않습니다.

## 보고 규칙

의미 있는 작업 완료 보고에는 아래 항목이 포함되어야 합니다.

- 선택한 에이전트 또는 에이전트 체인
- 짧은 변경 요약
- 실행한 명령 또는 점검 항목
- 검증 범위
- 실행하지 않았거나 검증하지 않은 항목
- 남은 리스크

사용자-facing 응답은 사용자가 다른 언어를 요구하지 않는 한 한국어를 사용합니다. 코드 식별자, 명령어, 파일명, 커밋 메시지는 저장소에서 다른 규칙을 강제하지 않는 한 영어를 유지합니다.

## 검증 시나리오

### 라우팅 스모크 테스트

- `Design a factor rotation strategy for KOSPI sectors with monthly rebalancing.` -> `quant-trading-expert`
- `Review this RSI and MACD chart setup and explain the invalidation levels.` -> `stock-chart-analyst`
- `Implement a Python batch job that recalculates factor scores every night.` -> `senior-backend-engineer-python`
- `Build a dashboard page that compares drawdown and turnover interactively.` -> `senior-frontend-engineer`
- `Restructure the onboarding flow for a retail quant dashboard.` -> `ui-ux-designer`
- `Review the completed order-routing refactor for hidden risks.` -> `paranoid-staff-engineer-reviewer`
- `Validate whether the new rebalance screen introduces regressions.` -> `qa-engineer`

### 혼합 작업 체인 예시

- `Design and implement a factor backtest API, then review it.` -> `quant-trading-expert` -> `senior-backend-engineer-python` -> `paranoid-staff-engineer-reviewer`
- `Redesign a signal dashboard and ship the UI safely.` -> `ui-ux-designer` -> `senior-frontend-engineer` -> `qa-engineer`

### 운영 시나리오 점검

- Git 저장소가 없음 -> 첫 추적 변경 전에 `git init`
- `pyproject.toml`이 없는데 Python 작업 요청이 들어옴 -> `uv init`
- Python 코드 변경 -> `uv run ...`으로 검증 후 커밋
- UI 변경 -> 필요 시 디자이너/프론트엔드 체인을 사용하고 검증 후 커밋
- 큰 구조 변경 -> 최종 커밋 전에 리뷰어 게이트 필수
