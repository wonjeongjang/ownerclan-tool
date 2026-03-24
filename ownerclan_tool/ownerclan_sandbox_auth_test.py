"""
변경 이유: Ownerclan 샌드박스 인증을 단일 파이썬 스크립트로 간단히 검증하기 위해 생성
"""

import json
import logging
import os
from typing import Dict

import requests
from dotenv import load_dotenv


def setup_logging() -> None:
    """
    변경 이유: 콘솔에 기본 로깅 설정을 적용하여 디버깅을 쉽게 하기 위함
    """
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )


def load_env_variables() -> Dict[str, str]:
    """
    변경 이유: .env에서 필요한 환경 변수를 읽어와 검증하고, 이후 로직에서 재사용 가능하도록 반환
    """
    load_dotenv()

    auth_url = os.getenv("OWNERCLAN_AUTH_URL", "").strip()
    api_id = os.getenv("OWNERCLAN_API_ID", "").strip()
    api_pw = os.getenv("OWNERCLAN_API_PW", "").strip()

    if not auth_url:
        raise ValueError("환경 변수 OWNERCLAN_AUTH_URL 이(가) 설정되어 있지 않습니다.")
    if not api_id:
        raise ValueError("환경 변수 OWNERCLAN_API_ID 이(가) 설정되어 있지 않습니다.")
    if not api_pw:
        raise ValueError("환경 변수 OWNERCLAN_API_PW 이(가) 설정되어 있지 않습니다.")

    return {
        "auth_url": auth_url,
        "api_id": api_id,
        "api_pw": api_pw,
    }


def build_payload(api_id: str, api_pw: str) -> Dict[str, str]:
    """
    변경 이유: 요청 payload 구성을 별도 함수로 분리하여 향후 변경 시 수정 범위를 줄이기 위함
    """
    payload: Dict[str, str] = {
        "service": "ownerclan",
        "userType": "seller",
        "username": api_id,
        "password": api_pw,
    }
    return payload


def call_ownerclan_auth(auth_url: str, payload: Dict[str, str]) -> requests.Response:
    """
    변경 이유: Ownerclan 샌드박스 인증 요청을 담당하는 함수를 분리하여 테스트와 재사용을 용이하게 하기 위함
    """
    logger = logging.getLogger("ownerclan_auth_test")
    logger.info("Ownerclan 샌드박스 인증 요청 시작: %s", auth_url)

    try:
        response = requests.post(auth_url, json=payload, timeout=10.0)
    except requests.RequestException as exc:
        logger.error("Ownerclan 인증 요청 중 네트워크 오류 발생: %s", exc)
        raise

    logger.info("Ownerclan 응답 수신 완료 - HTTP 상태 코드: %s", response.status_code)
    return response


def print_response(response: requests.Response) -> None:
    """
    변경 이유: HTTP 상태 코드와 응답 본문을 보기 좋게 출력하기 위해 별도 함수로 분리
    """
    print("=== Ownerclan 샌드박스 인증 응답 ===")
    print(f"HTTP 상태 코드: {response.status_code}")
    print("--- 응답 헤더 ---")
    for key, value in response.headers.items():
        print(f"{key}: {value}")

    print("\n--- 응답 본문 ---")
    text = response.text

    # JSON 여부 판단 후 pretty-print 시도
    try:
        parsed = response.json()
        pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
        print(pretty)
    except ValueError:
        # JSON 이 아니면 원문 그대로 출력
        print(text)


def main() -> None:
    """
    변경 이유: 전체 인증 테스트 흐름(환경 변수 로드 → payload 생성 → 요청 → 응답 출력)을 한 곳에서 관리
    """
    setup_logging()
    logger = logging.getLogger("ownerclan_auth_test")

    try:
        env_vars = load_env_variables()
    except ValueError as exc:
        logger.error("환경 변수 로드 오류: %s", exc)
        print(f"[에러] {exc}")
        return

    auth_url = env_vars["auth_url"]
    api_id = env_vars["api_id"]
    api_pw = env_vars["api_pw"]

    payload = build_payload(api_id=api_id, api_pw=api_pw)

    logger.debug("인증 요청 payload: %s", payload)

    try:
        response = call_ownerclan_auth(auth_url=auth_url, payload=payload)
    except requests.RequestException:
        print("[에러] Ownerclan 샌드박스 인증 요청 중 네트워크 오류가 발생했습니다.")
        return

    print_response(response)


if __name__ == "__main__":
    main()