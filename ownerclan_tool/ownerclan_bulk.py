"""
변경 이유: Ownerclan GraphQL에서 전체 상품을 페이징으로 조회하는 대량 등록용 기능을 별도 모듈로 분리
"""

import logging
import time
from typing import Dict, List, Optional

import requests

from config import OwnerclanConfig

logger = logging.getLogger(__name__)


# TODO: Ownerclan 실제 스키마에 맞게 allItems 쿼리를 조정하세요.
# - 페이징 구조(edges/pageInfo)는 예시이며, 응답 구조에 맞춰 수정이 필요할 수 있습니다.
ALL_ITEMS_QUERY_TEMPLATE = """
query bulkItemsQuery {
  allItems(first: %d%s) {
    edges {
      cursor
      node {
        key
        name
        price
        shippingFee
        shippingType
        status
        images(size: large)
        options {
          optionAttributes { name value }
          price
          quantity
        }
        taxFree
        openmarketSellable
        metadata
        content
        origin
        production
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
""".strip()


class OwnerclanBulkError(Exception):
    """Ownerclan 대량 상품 조회 과정에서 발생한 예외를 표현하는 클래스."""


def _build_query(first: int, after: Optional[str]) -> str:
    """
    변경 이유: after 커서 유무에 따라 GraphQL 쿼리 문자열을 안전하게 조립하기 위함
    """
    after_part = ""
    if after:
        # after는 문자열 커서라고 가정
        escaped = after.replace('"', '\\"')
        after_part = f', after: "{escaped}"'
    return ALL_ITEMS_QUERY_TEMPLATE % (first, after_part)


def fetch_all_items(
    config: OwnerclanConfig,
    jwt_token: str,
    first: int = 50,
    timeout_seconds: float = 60.0,
) -> List[Dict[str, object]]:
    """
    변경 이유: Ownerclan 전체 상품을 페이징(after 커서)으로 조회하되, 지정한 limit 개수만 수집 후 중단하기 위함
    """
    url = config.graphql_url
    headers = {
        "Authorization": f"{config.auth_header_scheme} {jwt_token}",
        "Accept": "application/json",
    }

    items: List[Dict[str, object]] = []
    after: Optional[str] = None

    limit = first
    page_size = 50
    logger.info("Ownerclan 전체 상품 조회 시작 (limit=%s, page_size=%s)", limit, page_size)

    while True:
        # hard stop: limit 만큼 수집하면 즉시 종료
        if isinstance(limit, int) and limit > 0 and len(items) >= limit:
            break

        remaining = limit - len(items) if isinstance(limit, int) and limit > 0 else page_size
        query_first = min(page_size, remaining) if isinstance(remaining, int) and remaining > 0 else page_size

        query_str = _build_query(first=query_first, after=after)
        params = {"query": query_str}

        # 네트워크/타임아웃 오류 시 최대 3회 재시도
        retries = 0
        while True:
            try:
                response = requests.get(url, params=params, headers=headers, timeout=timeout_seconds)
                break
            except requests.RequestException as exc:
                retries += 1
                logger.warning(
                    "Ownerclan 전체 상품 조회 중 네트워크/타임아웃 오류(%s회 시도): %s",
                    retries,
                    exc,
                )
                if retries >= 3:
                    logger.error(
                        "Ownerclan 전체 상품 조회 재시도 횟수 초과, 현재까지 %s개 수집 후 중단",
                        len(items),
                    )
                    return items
                time.sleep(5.0)

        if not response.ok:
            logger.error(
                "Ownerclan 전체 상품 조회 실패(status=%s): %s, 현재까지 %s개 수집 후 중단",
                response.status_code,
                response.text,
                len(items),
            )
            return items

        try:
            data: Dict[str, object] = response.json()
        except ValueError as exc:
            logger.error("Ownerclan 전체 상품 응답 JSON 파싱 실패: %s", exc)
            raise OwnerclanBulkError("Ownerclan 전체 상품 응답 형식이 올바르지 않습니다.") from exc

        data_root = data.get("data")
        if not isinstance(data_root, dict):
            raise OwnerclanBulkError("Ownerclan 전체 상품 응답에 data가 없습니다.")

        all_items = data_root.get("allItems")
        if not isinstance(all_items, dict):
            raise OwnerclanBulkError("Ownerclan 전체 상품 응답에 allItems가 없습니다.")

        edges = all_items.get("edges")
        if not isinstance(edges, list):
            raise OwnerclanBulkError("Ownerclan 전체 상품 응답에 edges가 없습니다.")

        for edge in edges:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node")
            if isinstance(node, dict):
                items.append(node)
                # 100개 단위로 진행 상황 로그
                if len(items) % 100 == 0:
                    logger.info("Ownerclan 전체 상품 조회 진행 중: %s개 수집", len(items))
                # limit 도달 시 즉시 루프 종료
                if isinstance(limit, int) and limit > 0 and len(items) >= limit:
                    break

        page_info = all_items.get("pageInfo")
        if not isinstance(page_info, dict):
            logger.warning("pageInfo가 없어 페이징을 종료합니다.")
            break

        has_next = page_info.get("hasNextPage")
        end_cursor = page_info.get("endCursor")

        if isinstance(limit, int) and limit > 0 and len(items) >= limit:
            break

        if has_next is True and isinstance(end_cursor, str) and end_cursor:
            after = end_cursor
            logger.info("다음 페이지 조회 (누적=%s)", len(items))
            continue

        break

    if isinstance(limit, int) and limit > 0:
        items = items[:limit]

    logger.info("Ownerclan 전체 상품 조회 완료 (총 %s건)", len(items))
    return items

