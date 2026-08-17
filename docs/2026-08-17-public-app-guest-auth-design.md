# 공개 Streamlit 앱 초대 이용자 인증 설계

## 목적

공개 URL로 배포되는 Streamlit 앱에서 일반 기능은 초대 이용자 인증을 통과한 현재 세션에만 제공한다. 초대 계정은 하나이며 관리자 계정과 분리한다.

## 접근 제어

- 첫 화면에는 `초대 이용자`와 `관리자` 진입 버튼만 표시한다.
- `초대 이용자`를 선택하면 ID와 비밀번호 입력 폼을 표시한다. 두 값이 Streamlit Secrets의 `GUEST_USERNAME`, `GUEST_PASSWORD`와 모두 일치할 때만 `guest` 역할을 부여한다.
- `관리자`는 기존 `ADMIN_USERNAME`, `ADMIN_PASSWORD`로만 인증하며, 관리자와 초대 이용자 자격 증명은 상호 교차 사용할 수 없다.
- 인증은 `hmac.compare_digest`로 두 값을 비교한다. Secret 누락, 자료형 오류, 틀린 ID 또는 틀린 비밀번호는 모두 동일한 일반 실패 메시지로 처리한다.
- 인증 전, 또는 변조된 역할 세션에서는 일반·관리자 페이지를 렌더링하지 않는다. 로그아웃/세션 초기화 시 두 로그인 폼의 ID·비밀번호 위젯 값과 역할을 제거한다.

## 구성 요소

- `auth.py`: `authenticate_guest(username, password, secrets) -> bool`를 추가한다. 기존 관리자 인증과 같은 실패-폐쇄 및 상수 시간 비교 규칙을 적용한다.
- `views/landing.py`: 초대 이용자용 폼 상태와 위젯 키를 분리하고, 성공 시 `enter_guest` 및 로그인 이력 기록을 수행한다. 실패 메시지는 자격 증명 정보를 공개하지 않는다.
- `streamlit_app.py`: `required_secret_names()`에 두 초대 이용자 Secret을 추가한다.
- `tests/test_auth.py`, `tests/test_app_bootstrap.py`: 초대 계정 성공/실패, 관리자와의 분리, 성공 뒤 위젯 값 삭제, 요구 Secrets 목록을 검증한다.
- `README.md`: 공개 Community Cloud 배포임을 명시하고, 두 초대 이용자 Secret과 공개 URL의 한계를 설명한다.

## 오류 처리와 검증

Secrets가 없거나 잘못된 형식이면 로그인은 실패하며 Secret 이름·값을 화면에 표시하지 않는다. 성공한 초대 이용자는 일반 워크플로만 볼 수 있고, 관리자 화면은 계속 차단된다. 테스트는 비밀값을 사용하지 않는 임의 문자열로 실행한다.

공개 URL 자체 및 앱의 정적 자산은 숨겨지지 않는다. 이 인증은 앱 기능의 서버 측 접근 경계이며, 민감한 데이터나 장기 보관 파일은 공개 배포에 두지 않는다.
