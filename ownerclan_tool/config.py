"""
변경 이유: 실제 Ownerclan 샌드박스/운영 인증 및 GraphQL 엔드포인트를 사용하도록 설정 구조를 수정
"""

import logging
import os
from dataclasses import dataclass
from typing import Dict

from dotenv import load_dotenv

# .env 파일에서 환경 변수 로드
load_dotenv()


@dataclass
class OwnerclanConfig:
    """Ownerclan 관련 설정 정보를 담는 데이터 클래스."""
    env: str
    auth_url: str
    graphql_url: str
    api_id: str
    api_pw: str
    product_key_variable: str
    auth_header_scheme: str


@dataclass
class SmartStoreConfig:
    """Smart Store 관련 설정 정보를 담는 데이터 클래스."""
    base_url: str
    register_endpoint: str
    client_id: str
    client_secret: str
    api_key: str


@dataclass
class AppConfig:
    """애플리케이션 전역 설정 정보를 담는 데이터 클래스."""
    env: str
    log_level: str
    db_path: str
    ownerclan: OwnerclanConfig
    smartstore: SmartStoreConfig
    product_field_mapping: Dict[str, str]


def _get_env(name: str, default: str = "") -> str:
    """
    변경 이유: Streamlit Cloud 환경에서 secrets 우선 조회 후 OS 환경 변수로 폴백하기 위함
    """
    try:
        import streamlit as st
        return st.secrets[name]
    except (KeyError, FileNotFoundError, Exception):
        return os.getenv(name, default)


def load_config() -> AppConfig:
    """
    변경 이유: .env 기반으로 전체 AppConfig를 구성하는 단일 진입점 제공
    """
    app_env = _get_env("APP_ENV", "SANDBOX").upper()
    log_level = _get_env("LOG_LEVEL", "INFO").upper()
    db_path = _get_env("DB_PATH", "ownerclan_tool.db")

    # Ownerclan: 환경에 따라 기본 URL을 설정하되, .env 로 재정의 가능
    if app_env == "PROD":
        default_auth_url = "https://auth.ownerclan.com/auth"
        default_graphql_url = "https://api.ownerclan.com/v1/graphql"
    else:
        default_auth_url = "https://auth-sandbox.ownerclan.com/auth"
        default_graphql_url = "https://api-sandbox.ownerclan.com/v1/graphql"

    ownerclan_config = OwnerclanConfig(
        env=_get_env("OWNERCLAN_ENV", app_env.lower()),
        auth_url=_get_env("OWNERCLAN_AUTH_URL", default_auth_url),
        graphql_url=_get_env("OWNERCLAN_GRAPHQL_URL", default_graphql_url),
        api_id=_get_env("OWNERCLAN_API_ID", ""),
        api_pw=_get_env("OWNERCLAN_API_PW", ""),
        product_key_variable=_get_env("OWNERCLAN_PRODUCT_KEY_VARIABLE", "key"),
        auth_header_scheme=_get_env("OWNERCLAN_AUTH_HEADER_SCHEME", "Bearer"),
    )

    smartstore_config = SmartStoreConfig(
        base_url=_get_env("SMARTSTORE_BASE_URL", "https://sandbox-api.smartstore.example.com"),
        register_endpoint=_get_env("SMARTSTORE_REGISTER_PRODUCT_ENDPOINT", "/products"),
        client_id=_get_env("SMARTSTORE_CLIENT_ID", ""),
        client_secret=_get_env("SMARTSTORE_CLIENT_SECRET", ""),
        api_key=_get_env("SMARTSTORE_API_KEY", ""),
    )

    # Ownerclan → Smart Store 필드 매핑
    # key: Smart Store 필드명, value: Ownerclan JSON에서 읽을 경로(간단 버전은 1단계 키 사용)
    product_field_mapping: Dict[str, str] = {
        # 예시: Smart Store에서 name 필드는 Ownerclan의 "title" 필드에서 가져옴
        "name": "title",
        "seller_code": "sku",
        "description": "description",
        "sale_price": "price",
        "stock": "stock",
    }

    config = AppConfig(
        env=app_env,
        log_level=log_level,
        db_path=db_path,
        ownerclan=ownerclan_config,
        smartstore=smartstore_config,
        product_field_mapping=product_field_mapping,
    )

    # 로깅 기본 설정
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    logging.getLogger(__name__).info("설정 로드 완료 (APP_ENV=%s)", app_env)
    return config