"""
변경 이유: 실제 Ownerclan 샌드박스/운영 인증 엔드포인트를 사용하도록 로직을 수정하고,
          UI에서 사용할 수 있는 인증 테스트 함수와 토큰 발급 함수를 분리하며,
          JSON 필드가 없고 raw 텍스트로 JWT가 내려오는 경우를 처리
"""

import logging
from typing import Dict

import requests

from config import OwnerclanConfig

logger = logging.getLogger(__name__)


class OwnerclanAuthError(Exception):
    """Ownerclan 인증 과정에서 발생한 예외를 표현하는 클래스."""
    pass


def extract_ownerclan_token(response_json: object, raw_text: str) -> str:
    """
    변경 이유: Ownerclan 인증 응답에서 토큰을 일관되게 추출하기 위해 헬퍼 함수 추가

    우선 일반적인 JSON 토큰 필드를 확인하고,
    그렇지 않으면 raw 텍스트가 JWT 형태(예: 'eyJ'로 시작)인지 검사하여 토큰으로 사용한다.
    """
    token = ""

    # 1) JSON 응답에 토큰 필드가 있는 경우 우선 사용
    if isinstance(response_json, dict):
        for key in ("accessToken", "access_token", "token", "jwt"):
            value = response_json.get(key)
            if isinstance(value, str) and value:
                token = value
                break

    # 2) JSON에서 찾지 못했고, raw 텍스트가 JWT처럼 보이는 경우
    if not token:
        candidate = raw_text.strip()
        if candidate.startswith("eyJ") and "." in candidate:
            token = candidate

    return token


def request_ownerclan_auth(
    config: OwnerclanConfig,
    timeout_seconds: float = 10.0,
) -> Dict[str, object]:
    """
    변경 이유: Ownerclan 인증 요청/응답 전체를 UI에서 확인할 수 있도록 세부 정보를 반환하는 함수 추가
    """
    url = config.auth_url
    payload: Dict[str, str] = {
        "service": "ownerclan",
        "userType": "seller",
        "username": config.api_id,
        "password": config.api_pw,
    }

    logger.info("Ownerclan 인증 요청 시작: %s", url)

    try:
        response = requests.post(url, json=payload, timeout=timeout_seconds)
    except requests.RequestException as exc:
        logger.error("Ownerclan 인증 요청 중 네트워크 오류 발생: %s", exc)
        raise OwnerclanAuthError("Ownerclan 인증 요청 실패(네트워크 오류).") from exc

    logger.info("Ownerclan 인증 응답 수신 - 상태 코드: %s", response.status_code)

    try:
        response_json: Dict[str, object] = response.json()
    except ValueError:
        response_json = {}

    token = extract_ownerclan_token(response_json, response.text)

    return {
        "url": url,
        "status_code": response.status_code,
        "response_json": response_json,
        "raw_text": response.text,
        "ok": response.ok and bool(token),
        "token": token,
    }


def get_ownerclan_jwt(config: OwnerclanConfig, timeout_seconds: float = 10.0) -> str:
    """
    변경 이유: 기존 토큰 발급 함수는 유지하되, 내부적으로 request_ownerclan_auth를 사용하고
              JSON 토큰 필드가 없을 때 raw 텍스트 JWT도 처리
    """
    result = request_ownerclan_auth(config, timeout_seconds=timeout_seconds)

    if not result.get("ok", False):
        raise OwnerclanAuthError(
            f"Ownerclan 인증 실패 (status={result.get('status_code')})."
        )

    token_value = result.get("token", "")
    if not isinstance(token_value, str) or not token_value:
        logger.error("Ownerclan 인증 응답에서 토큰을 추출하지 못함: %s", result)
        raise OwnerclanAuthError("Ownerclan 인증 응답에서 토큰을 추출하지 못했습니다.")

    logger.info("Ownerclan JWT 발급 성공")
    return token_value