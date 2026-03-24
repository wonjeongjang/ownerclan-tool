"""
변경 이유: 실제 Ownerclan GraphQL 응답 구조(data.item.*)를 기반으로
          Smart Store 등록용 구조를 생성하도록 변환 로직을 재작성
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


def _warn_missing(path: str) -> None:
    """
    변경 이유: 예상된 필드가 없을 때 경고 로그를 남기되, 예외는 발생시키지 않기 위함
    """
    logger.warning("Ownerclan 상품 응답에 예상된 필드가 없습니다: %s", path)


def _safe_dict(value: object) -> Dict[str, object]:
    """
    변경 이유: dict 가 아닐 수 있는 값을 안전하게 딕셔너리로 변환하기 위함
    """
    if isinstance(value, dict):
        return value
    return {}


def _safe_list(value: object) -> List[object]:
    """
    변경 이유: list 가 아닐 수 있는 값을 안전하게 리스트로 변환하기 위함
    """
    if isinstance(value, list):
        return value
    return []


def transform_ownerclan_to_smartstore(
    raw_product: Dict[str, object],
) -> Dict[str, object]:
    """
    변경 이유: Ownerclan GraphQL 응답(data.item.*)을 Smart Store 상품 등록 구조로 직접 변환하기 위함

    raw_product: Ownerclan GraphQL 원본 응답(JSON dict)
    """
    logger.info("Ownerclan 상품 데이터를 Smart Store 형식으로 변환 시작")

    data = _safe_dict(raw_product.get("data"))
    if not data:
        _warn_missing("data")

    item = _safe_dict(data.get("item"))
    if not item:
        _warn_missing("data.item")

    metadata = _safe_dict(item.get("metadata"))
    options_list = _safe_list(item.get("options"))
    images_list = _safe_list(item.get("images"))

    # 기본 필드 추출 (모두 .get 사용, 기본값은 None 또는 적절한 기본값)
    name = item.get("name")
    price = item.get("price")
    content = item.get("content")
    shipping_fee = item.get("shippingFee")
    tax_free = item.get("taxFree")
    status_raw = item.get("status")
    return_shipping_fee = metadata.get("returnShippingFee")
    category_code = metadata.get("smartstoreCategoryCode")

    if name is None:
        _warn_missing("data.item.name")
    if price is None:
        _warn_missing("data.item.price")
    if content is None:
        _warn_missing("data.item.content")
    if shipping_fee is None:
        _warn_missing("data.item.shippingFee")
    if category_code is None:
        _warn_missing("data.item.metadata.smartstoreCategoryCode")
    if return_shipping_fee is None:
        _warn_missing("data.item.metadata.returnShippingFee")

    # 이미지 리스트 (대표 이미지는 첫 번째로 사용 가능)
    images: List[object] = []
    for img in images_list:
        if isinstance(img, str) and img:
            images.append(img)
        else:
            _warn_missing("data.item.images[] (URL 문자열 아님)")

    # 재고 수량: 모든 옵션의 quantity 합계
    stock_quantity = 0
    options_output: List[Dict[str, object]] = []

    for opt in options_list:
        opt_dict = _safe_dict(opt)
        quantity_value = opt_dict.get("quantity")
        if isinstance(quantity_value, int):
            stock_quantity += quantity_value

        option_attributes = _safe_list(opt_dict.get("optionAttributes"))
        # 옵션 이름/값은 여러 개일 수 있으므로 간단하게 join 처리
        names: List[str] = []
        values: List[str] = []
        for attr in option_attributes:
            attr_dict = _safe_dict(attr)
            name_attr = attr_dict.get("name")
            value_attr = attr_dict.get("value")
            if isinstance(name_attr, str):
                names.append(name_attr)
            else:
                _warn_missing("data.item.options[].optionAttributes[].name")
            if isinstance(value_attr, str):
                values.append(value_attr)
            else:
                _warn_missing("data.item.options[].optionAttributes[].value")

        name_joined = ", ".join(names) if names else None
        value_joined = ", ".join(values) if values else None

        price_value = opt_dict.get("price")
        if price_value is None:
            _warn_missing("data.item.options[].price")

        option_entry: Dict[str, object] = {
            "name": name_joined,
            "value": value_joined,
            "price": price_value,
            "quantity": quantity_value,
        }
        options_output.append(option_entry)

    # 판매 상태 변환: available -> SALE, 그 외 -> SUSPENSION
    status_converted = "SALE" if status_raw == "available" else "SUSPENSION"

    transformed: Dict[str, object] = {
        "name": name,
        "salePrice": price,
        "detailContent": content,
        "shippingFee": shipping_fee,
        "categoryId": category_code,
        "images": images,
        "stockQuantity": stock_quantity,
        "options": options_output,
        "taxFree": tax_free,
        "status": status_converted,
        "returnShippingFee": return_shipping_fee,
    }

    logger.info("Ownerclan 상품 데이터를 Smart Store 형식으로 변환 완료")
    return transformed