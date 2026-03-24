"""
변경 이유: 실제 네이버 커머스 OAuth2 토큰 발급 및 상품 등록/이미지 업로드 스펙에 맞춰 Smart Store 연동 로직을 구현
"""

import bcrypt
import pybase64
import logging
import time
from typing import Dict
from io import BytesIO

import requests
from PIL import Image

from config import SmartStoreConfig

logger = logging.getLogger(__name__)


class SmartStoreRegisterError(Exception):
    """Smart Store 상품 등록 과정에서 발생한 예외를 표현하는 클래스."""
    pass


def _get_smartstore_token(
    config: SmartStoreConfig,
    timeout_seconds: float = 10.0,
) -> str:
    """
    네이버 커머스 OAuth2 client_credentials 플로우에 맞춰
    bcrypt 기반 client_secret_sign 방식으로 토큰을 발급받는다.
    """
    token_url = "https://api.commerce.naver.com/external/v1/oauth2/token"

    timestamp_ms = int(time.time() * 1000)
    password = f"{config.client_id}_{timestamp_ms}"

    try:
        hashed = bcrypt.hashpw(password.encode("utf-8"), config.client_secret.encode("utf-8"))
    except Exception as exc:
        logger.error("Smart Store client_secret_sign 생성 중 오류 발생: %s", exc)
        raise SmartStoreRegisterError("Smart Store client_secret_sign 생성 실패.") from exc

    client_secret_sign = pybase64.standard_b64encode(hashed).decode("utf-8")

    data = {
        "client_id": config.client_id,
        "timestamp": str(timestamp_ms),
        "client_secret_sign": client_secret_sign,
        "grant_type": "client_credentials",
        "type": "SELF",
    }

    logger.info("Smart Store OAuth2 토큰 발급 요청 시작: %s", token_url)

    try:
        response = requests.post(
            token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=data,
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        logger.error("Smart Store 토큰 발급 요청 중 네트워크 오류 발생: %s", exc)
        raise SmartStoreRegisterError("Smart Store 토큰 발급 실패(네트워크 오류).") from exc

    if not response.ok:
        logger.error("Smart Store 토큰 발급 실패 - 상태 코드: %s, 본문: %s", response.status_code, response.text)
        raise SmartStoreRegisterError(f"Smart Store 토큰 발급 실패 (status={response.status_code}).")

    try:
        token_json = response.json()
    except ValueError as exc:
        raise SmartStoreRegisterError("Smart Store 토큰 응답 형식이 올바르지 않습니다.") from exc

    access_token_value = token_json.get("access_token")
    if not isinstance(access_token_value, str) or not access_token_value:
        raise SmartStoreRegisterError("Smart Store 토큰 응답에 access_token이 없습니다.")

    logger.info("Smart Store OAuth2 토큰 발급 성공")
    return access_token_value


def _upload_image(access_token: str, image_url: str, timeout_seconds: float = 10.0) -> str:
    """
    외부 이미지 URL을 네이버 커머스에 업로드하여 내부 이미지 URL로 변환한다.
    업로드 실패 시 원본 URL을 그대로 반환한다.
    429 rate limit 발생 시 1초 대기 후 1회 재시도한다.
    """
    if not image_url:
        return image_url

    upload_url = "https://api.commerce.naver.com/external/v1/product-images/upload"

    # 이미지 다운로드
    try:
        download_resp = requests.get(image_url, timeout=timeout_seconds)
    except requests.RequestException as exc:
        logger.warning("이미지 다운로드 실패, 원본 URL 사용: %s (%s)", image_url, exc)
        return image_url

    if not download_resp.ok:
        logger.warning("이미지 다운로드 실패(status=%s), 원본 URL 사용: %s", download_resp.status_code, image_url)
        return image_url

    image_bytes = download_resp.content
    converted_bytes = image_bytes

    # WebP 등 비호환 포맷을 JPEG로 변환
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            rgb_img = img.convert("RGB")
            buffer = BytesIO()
            rgb_img.save(buffer, format="JPEG")
            converted_bytes = buffer.getvalue()
    except Exception as exc:
        logger.warning("이미지 JPEG 변환 실패, 원본 바이트 사용: %s", exc)

    def _do_upload() -> requests.Response:
        return requests.post(
            upload_url,
            headers={"Authorization": f"Bearer {access_token}"},
            files={"imageFiles": ("image.jpg", converted_bytes, "image/jpeg")},
            timeout=timeout_seconds,
        )

    # 업로드 시도
    try:
        upload_resp = _do_upload()
    except requests.RequestException as exc:
        logger.warning("이미지 업로드 실패, 원본 URL 사용: %s (%s)", image_url, exc)
        return image_url

    # 429 rate limit 시 1초 대기 후 재시도
    if upload_resp.status_code == 429:
        logger.warning("이미지 업로드 rate limit(429), 1초 대기 후 재시도: %s", image_url)
        time.sleep(1)
        try:
            upload_resp = _do_upload()
        except requests.RequestException as exc:
            logger.warning("이미지 업로드 재시도 실패, 원본 URL 사용: %s (%s)", image_url, exc)
            return image_url

    if not upload_resp.ok:
        logger.warning(
            "이미지 업로드 실패(status=%s), 원본 URL 사용: %s, body=%s",
            upload_resp.status_code,
            image_url,
            upload_resp.text,
        )
        return image_url

    try:
        upload_json = upload_resp.json()
    except ValueError:
        logger.warning("이미지 업로드 응답 JSON 파싱 실패, 원본 URL 사용: %s", image_url)
        return image_url

    uploaded_url = ""
    if isinstance(upload_json, dict):
        images = upload_json.get("images")
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, dict):
                url_value = first.get("url")
                if isinstance(url_value, str):
                    uploaded_url = url_value
        if not uploaded_url:
            url_value_single = upload_json.get("url")
            if isinstance(url_value_single, str):
                uploaded_url = url_value_single

    if not uploaded_url:
        logger.warning("이미지 업로드 응답에서 URL을 찾지 못해 원본 URL 사용: %s", image_url)
        return image_url

    logger.info("이미지 업로드 성공: %s -> %s", image_url, uploaded_url)
    return uploaded_url


def register_product_to_smartstore(
    config: SmartStoreConfig,
    product_data: Dict[str, object],
    timeout_seconds: float = 10.0,
) -> Dict[str, object]:
    """
    스마트스토어에 상품을 등록한다.
    """
    access_token = _get_smartstore_token(config, timeout_seconds=timeout_seconds)

    url = "https://api.commerce.naver.com/external/v2/products"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    name_value = product_data.get("name")
    sale_price_value = product_data.get("salePrice")
    detail_content_value = product_data.get("detailContent")
    shipping_fee_value = product_data.get("shippingFee")
    category_id_value = product_data.get("categoryId")
    images_value = product_data.get("images")
    stock_quantity_value = product_data.get("stockQuantity")
    status_value = product_data.get("status")

    images_list = images_value if isinstance(images_value, list) else []
    representative_image_url = images_list[0] if images_list else None
    optional_images_urls = images_list[1:] if len(images_list) > 1 else []

    # 이미지 업로드 (rate limit 방지를 위해 0.3초 딜레이)
    representative_image_url = _upload_image(access_token, representative_image_url, timeout_seconds)
    time.sleep(0.3)

    uploaded_optional = []
    for u in optional_images_urls:
        time.sleep(0.3)
        uploaded_optional.append(_upload_image(access_token, u, timeout_seconds))
    optional_images_urls = uploaded_optional

    payload = {
        "originProduct": {
            "statusType": status_value,
            "saleType": "NEW",
            "leafCategoryId": category_id_value,
            "name": name_value,
            "images": {
                "representativeImage": {"url": representative_image_url},
                "optionalImages": [{"url": u} for u in optional_images_urls],
            },
            "detailContent": detail_content_value,
            "salePrice": sale_price_value,
            "stockQuantity": stock_quantity_value,
            "deliveryInfo": {
                "deliveryType": "DELIVERY",
                "deliveryAttributeType": "NORMAL",
                "deliveryBundleGroupUsable": False,
                "deliveryCompany": "CJGLS",
                "deliveryFee": {
                    "deliveryFeeType": "PAID",
                    "baseFee": max(int(shipping_fee_value or 0), 10),
                    "deliveryFeePayType": "COLLECT",
                },
                "claimDeliveryInfo": {
                    "returnDeliveryFee": 3000,
                    "exchangeDeliveryFee": 3000,
                },
            },
            "detailAttribute": {
                "naverProductCode": None,
                "taxType": "TAX",
                "isbnCode": None,
                "ecCode": None,
                "useModelName": False,
                "modelName": None,
                "manufacture": None,
                "brandName": None,
                "minorPurchasable": True,
                "originAreaInfo": {
                    "originNation": "04",
                    "originNationName": "중국",
                    "importer": "",
                    "originAreaCode": "04",
                    "content": "중국",
                },
                "afterServiceInfo": {
                    "afterServiceTelephoneNumber": "070-0000-0000",
                    "afterServiceGuideContent": "판매자 문의",
                },
                "purchaseQuantityInfo": None,
                "productInfoProvidedNotice": {
                    "productInfoProvidedNoticeType": "ETC",
                    "etc": {
                        "itemName": "상세페이지 참조",
                        "modelName": "상세페이지 참조",
                        "manufacturer": "상세페이지 참조",
                        "customerServicePhoneNumber": "070-0000-0000",
                        "returnCostReason": "판매자 문의",
                        "noRefundReason": "판매자 문의",
                        "qualityAssuranceStandard": "판매자 문의",
                        "compensationProcedure": "판매자 문의",
                        "troubleShootingContents": "판매자 문의",
                    },
                },
                "optionInfo": None,
            },
        },
        "smartstoreChannelProduct": {
            "naverShoppingRegistration": False,
            "channelProductDisplayStatusType": "ON",
        },
    }

    logger.info("Smart Store 상품 등록 요청 시작: %s", url)

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=timeout_seconds)
    except requests.RequestException as exc:
        logger.error("Smart Store 상품 등록 요청 중 네트워크 오류 발생: %s", exc)
        raise SmartStoreRegisterError("Smart Store 상품 등록 실패(네트워크 오류).") from exc

    if not response.ok:
        logger.error("Smart Store 상품 등록 실패 - 상태 코드: %s, 본문: %s", response.status_code, response.text)
        raise SmartStoreRegisterError(
            f"Smart Store 상품 등록 실패 (status={response.status_code}, body={response.text})."
        )

    try:
        data = response.json()
    except ValueError:
        logger.warning("Smart Store 응답 JSON 파싱 실패, 텍스트로 대체: %s", response.text)
        data = {"raw_text": response.text}

    logger.info("Smart Store 상품 등록 성공")
    return data