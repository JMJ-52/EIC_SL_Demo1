# EIC 교체 타당성 검토 데모

이 디렉터리(`SL/`) 자체를 저장소 루트로 배포하는 독립 Streamlit 시연 앱입니다. 영구 데이터베이스를
사용하지 않으며 시연 데이터, 변경 내용, 업로드는 현재 브라우저 세션에만 보관됩니다.
사이드바의 `로그아웃 및 세션 초기화`는 해당 세션의 업로드와 모든 데모 변경 사항을
삭제합니다. 다른 세션의 파일이나 운영 데이터는 삭제하지 않습니다. 프로세스 시작 시에는
전용 임시 루트에 남은 이전 프로세스의 세션 디렉터리를 최대 64개까지 안전하게 정리하고,
실행 중에는 24시간이 지난 디렉터리를 로그아웃/초기화 때 최대 64개씩 정리합니다. 강제 종료
직후 파일은 다음 시작 정리 전까지 OS 임시 저장소에 남을 수 있습니다.

## 로컬 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m streamlit run streamlit_app.py
```

위 명령은 이 README와 `streamlit_app.py`가 있는 `SL/` 저장소 루트에서 실행합니다.
상위 프로젝트 루트에서 개발 중이라면 먼저 `cd SL` 하세요. 표시된 로컬 URL에서 초대 사용자와 관리자 흐름을 각각 확인합니다. 앱을 다시 시작해도
이전 브라우저 세션의 변경 사항이 영구 데이터로 복원되지 않는 것이 정상입니다.

## Secrets

Streamlit Cloud의 Secrets 관리 화면에 다음 이름을 TOML 키로 등록합니다. 저장소에는
실제 값이나 예시 값을 넣지 마세요.

```text
GUEST_USERNAME
GUEST_PASSWORD
ADMIN_USERNAME
ADMIN_PASSWORD
OPENAI_API_KEY
OPENAI_MODEL
TAVILY_API_KEY
SMTP_HOST
SMTP_PORT
SMTP_USER
SMTP_PASSWORD
REQUEST_RECIPIENT_EMAIL
```

각 이름에는 배포 환경의 실제 값을 지정해야 하지만, 값은 코드, 문서, 커밋, 화면 캡처에
절대 기록하지 않습니다. `GUEST_USERNAME`과 `GUEST_PASSWORD`는 초대 이용자의 일반
워크플로 접근을 보호하며, 관리자 계정과 분리해 운용합니다. 앱은 관리자·초대 이용자 인증,
OpenAI/Tavily 호출, SMTP 확인 요청에 필요한 Secrets만 사용하며 UI에는 키 값을 표시하지 않습니다.
`SMTP_PORT`는 TOML 정수(`SMTP_PORT = 587`) 또는 숫자 문자열 모두 사용할 수 있습니다.

## Streamlit Community Cloud

1. `SL/`의 내용이 저장소 최상위에 오도록 별도 비공개 저장소 또는 subtree 배포 브랜치를
   준비합니다. 이 저장소 루트에는 `streamlit_app.py`, `lifecycle/`, `.streamlit/config.toml`이
   함께 있어야 합니다. 상위 프로젝트 전체를 Community Cloud 저장소로 선택하지 않습니다.
2. Streamlit Community Cloud에서 해당 저장소와 배포 브랜치를 선택하고 main file path를
   `streamlit_app.py`로 지정합니다.
3. 앱은 공개 URL로 배포됩니다. URL은 초대 대상에게만 전달하고, 민감한 데이터나 장기 보관
   파일은 이 배포에 포함하지 마세요. 일반 기능은 초대 이용자 로그인 후에만 사용할 수 있습니다.
4. 앱 설정의 Secrets 입력란에 위의 열두 가지 이름과 실제 값을 등록합니다. 값은 저장소에
   커밋하지 않습니다.
5. 배포 직후 아래 스모크 테스트를 완료한 뒤 참석자에게 URL을 전달합니다.

## 키 사용 범위

`OPENAI_API_KEY`와 `TAVILY_API_KEY`는 이 데모 전용 저한도 프로젝트 키만 사용하세요.
운영 키, 개인 키, 고객 데이터는 사용하지 않습니다. 공급자 측 예산·호출 한도도 함께
설정하고, 키가 노출되었다고 의심되면 즉시 폐기·교체하세요.

`REQUEST_RECIPIENT_EMAIL`은 시연 전에 승인된 고정 SMTP 수신자 한 명으로 설정합니다.
화면 입력으로 수신자를 바꾸지 않으며, `SMTP_USER`와 `SMTP_PASSWORD`에도 데모 전용
자격 증명과 공급자 측 전송 한도를 적용합니다.

## 배포 후 스모크 테스트

- 초대 이용자 계정으로 로그인해 프로젝트 생성, 편집, 업로드와 세션 전용 경고를 확인합니다.
- PDF/PPTX/XLSX 원본 미리보기가 제한된 페이지·슬라이드·행만 표시되는지 확인합니다.
- 관리자 계정으로 접속해 사용자 승인, 수명주기 검토, 승인 설비 JSON 다운로드를
  확인하고, 일반 워크플로와 관리자 화면 사이를 이동하며 비밀값이나 임시 파일 경로가
  표시되지 않는지 확인합니다. 초대 사용자는 관리자 화면을 선택할 수 없어야 합니다.
- AI 분석과 설비 챗봇을 각각 한 번 실행해 세션별 사용량이 증가하고 키 값은 표시되지
  않는지 확인합니다. 공급자 오류에는 일반 오류 메시지만 표시되어야 합니다.
- 공식 PDF 확인 요청을 한 번 보내 승인된 고정 SMTP 수신자에게만 도착하는지 확인합니다.
- `로그아웃 및 세션 초기화` 후 다시 들어가 시연 중 변경한 프로젝트와 업로드가 제거되고
  기본 데모 상태로 시작하는지 확인합니다.
