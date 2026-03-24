## Ownerclan → Smart Store 상품 연동 (Phase 1 MVP)

이 프로젝트는 내부용 Python 기반 드롭쉬핑 자동화 도구의 **Phase 1** 으로,
아래 기능만을 최소 구현합니다.

- Ownerclan JWT 인증
- Ownerclan 상품 1개 조회
- 원본 상품 JSON 저장(SQLite)
- Smart Store 등록용 구조로 변환
- Streamlit UI에서 원본/변환 데이터 확인
- Smart Store에 상품 1개 등록 테스트
- 등록 성공/실패 로그(SQLite) 저장

### 1. 환경 설정

1. `requirements.txt` 설치

```bash
pip install -r requirements.txt