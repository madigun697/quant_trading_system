# 커스텀 서브에이전트 안내 한글 참고본

이 문서는 한국어 사용자를 위한 참고용 번역본입니다. 실제 운영 규칙과 우선순위는 루트의 `AGENTS.md`와 원본 `agents/README.md`를 따릅니다.

이 디렉터리에는 프로젝트 전용 전문 프롬프트 라이브러리가 들어 있습니다.

## 호출 패턴

1. 작업에 가장 잘 맞는 전문 프롬프트를 선택합니다.
2. 해당 프롬프트 파일을 읽습니다.
3. 프롬프트 내용을 지시 블록으로 감쌉니다.
4. 감싼 프롬프트를 넣어 `worker` 에이전트를 실행합니다.
5. 프롬프트 내용과 `AGENTS.md`가 충돌하면 항상 `AGENTS.md`를 우선합니다.

## 권장 메시지 프레임

```text
Your task is to perform the following. Follow the instructions below exactly.

<agent-instructions>
[선택한 프롬프트 파일 내용을 여기에 붙여넣기]
</agent-instructions>

Project root AGENTS.md is authoritative for workflow, git, uv, validation,
and reporting rules. Execute this now and return only the requested output.
```

## 예시 실행 패턴

```text
spawn_agent(
  agent_type="worker",
  message="[agents/senior-backend-engineer-python.md를 감싼 프롬프트]"
)
```

## 권장 체인

- 퀀트 리서치 -> 구현 -> 리뷰:
  `quant-trading-expert` -> `senior-backend-engineer-python` -> `paranoid-staff-engineer-reviewer`
- 차트 중심 UI 기능:
  `stock-chart-analyst` -> `ui-ux-designer` -> `senior-frontend-engineer` -> `qa-engineer`
- 사용자 영향이 있는 백엔드 기능:
  `senior-backend-engineer-python` -> `paranoid-staff-engineer-reviewer` -> `qa-engineer`

## 역할 소유권 메모

- 각 전문 에이전트는 자신의 도메인 안에서 판단 책임을 가집니다.
- 다음 단계가 자신의 소관을 벗어나면 적절한 담당 에이전트에게 넘겨야 합니다.
- `explorer`는 읽기 전용 탐색에는 사용할 수 있지만, 전문 에이전트의 책임을 대신하지는 못합니다.
