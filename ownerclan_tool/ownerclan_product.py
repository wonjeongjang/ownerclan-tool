"""
변경 이유: Ownerclan 상품 조회가 REST가 아닌 단일 GraphQL 엔드포인트를 사용하므로,
          GraphQL POST 요청으로 상품 1개를 조회하도록 로직을 수정하고,
          Streamlit에서 디버깅이 가능하도록 요청/응답 전체 정보를 반환하는 함수 추가
"""

import logging
from typing import Dict

import requests

from config import OwnerclanConfig

logger = logging.getLogger(__name__)


class OwnerclanProductError(Exception):
    """Ownerclan 상품 조회 과정에서 발생한 예외를 표현하는 클래스."""
    pass


# 변경 이유: Ownerclan 공식 문서에 따른 실제 단일 상품 조회용 GraphQL 쿼리를 상수로 정의
DEFAULT_OWNERCLAN_PRODUCT_QUERY = """
query testQuery {
  item(key: "%s") {
    key
    name
    model
    production
    origin
    price
    content
    shippingFee
    shippingType
    images(size: large)
    status
    options {
      optionAttributes {
        name
        value
      }
      price
      quantity
    }
    taxFree
    openmarketSellable
    metadata
  }
}
""".strip()


def build_ownerclan_product_payload(config: OwnerclanConfig, product_id: str) -> Dict[str, object]:
    """
    변경 이유: GraphQL 요청 payload 구조를 한 곳에서 관리하고, 변수명(key 등)을 설정에서 제어하며,
              query 문자열이 비어 있을 경우 요청을 보내지 않도록 사전 검증
    """
    query = DEFAULT_OWNERCLAN_PRODUCT_QUERY
    if not isinstance(query, str) or not query.strip():
        raise OwnerclanProductError(
            "Ownerclan GraphQL 쿼리가 비어 있습니다. DEFAULT_OWNERCLAN_PRODUCT_QUERY를 확인해 주세요."
        )

    variables: Dict[str, object] = {
        config.product_key_variable: product_id,
    }
    payload: Dict[str, object] = {
        "query": query,
        "variables": variables,
    }
    return payload


def request_ownerclan_product_debug(
    config: OwnerclanConfig,
    jwt_token: str,
    product_id: str,
    timeout_seconds: float = 10.0,
) -> Dict[str, object]:
    """
    변경 이유: GraphQL 요청/응답을 전체적으로 확인하여 쿼리/변수 구조 문제를 디버깅하기 위해 디버그용 함수를 추가

    반환값에는 요청 URL, 헤더(마스킹된 Authorization), 요청 body, 상태 코드, raw 텍스트, JSON 파싱 결과 등이 포함된다.
    """
    url = config.graphql_url

    auth_header_value = f"{config.auth_header_scheme} {jwt_token}"

    headers = {
        "Authorization": auth_header_value,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    logger.info("Ownerclan 상품(GraphQL) 조회 요청 시작: %s (product_id=%s)", url, product_id)

    # Ownerclan 문서에 따르면 READ는 GET + query 문자열을 URL 파라미터로 전달해야 함
    query_str = DEFAULT_OWNERCLAN_PRODUCT_QUERY % product_id
    params: Dict[str, object] = {"query": query_str}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=timeout_seconds)
    except requests.RequestException as exc:
        logger.error("Ownerclan 상품 조회 중 네트워크 오류 발생: %s", exc)
        raise OwnerclanProductError("Ownerclan 상품 조회 실패(네트워크 오류).") from exc

    # 헤더 디버그용 사본 생성 및 토큰 마스킹
    debug_headers: Dict[str, object] = dict(headers)
    auth_header = debug_headers.get("Authorization")
    if isinstance(auth_header, str) and auth_header:
        # 예: "Bearer eyJ..." 형태에서 앞부분만 남기고 나머지 마스킹
        parts = auth_header.split(" ", 1)
        if len(parts) == 2:
            scheme, token_part = parts
            preview = token_part[:8] + "..." if len(token_part) > 11 else token_part
            debug_headers["Authorization"] = f"{scheme} {preview}"

    try:
        response_json: Dict[str, object] = response.json()
    except ValueError:
        response_json = {}

    ok = response.ok

    if not ok:
        logger.error(
            "Ownerclan 상품 조회 실패 - 상태 코드: %s, 본문: %s",
            response.status_code,
            response.text,
        )

    return {
        "url": url,
        "request_headers": debug_headers,
        # GET 요청이므로 실제로는 쿼리 파라미터를 통해 전송된 내용을 기록
        "request_body": {"query": query_str},
        "status_code": response.status_code,
        "raw_text": response.text,
        "response_json": response_json,
        "ok": ok,
    }


def fetch_ownerclan_product(
    config: OwnerclanConfig,
    jwt_token: str,
    product_id: str,
    timeout_seconds: float = 10.0,
) -> Dict[str, object]:
    """
    변경 이유: 기존 fetch 함수는 유지하되, 내부적으로 디버그용 함수를 사용하여 실패 시 자세한 로그를 남김
    """
    debug_result = request_ownerclan_product_debug(
        config=config,
        jwt_token=jwt_token,
        product_id=product_id,
        timeout_seconds=timeout_seconds,
    )

    if not debug_result.get("ok", False):
        raise OwnerclanProductError(
            f"Ownerclan 상품 조회 실패 (status={debug_result.get('status_code')})."
        )

    response_json = debug_result.get("response_json", {})
    if not isinstance(response_json, dict):
        raise OwnerclanProductError("Ownerclan 상품 응답 형식이 올바르지 않습니다.")

    logger.info("Ownerclan 상품 조회 성공 (product_id=%s)", product_id)
    return response_json