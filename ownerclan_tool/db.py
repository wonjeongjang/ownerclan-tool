"""
변경 이유: SQLite 기반의 데이터 저장/조회 로직을 한 곳에 모아 관리하기 위해 db 모듈 생성
"""

import json
import logging
import sqlite3
from datetime import datetime
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def get_connection(db_path: str) -> sqlite3.Connection:
    """
    변경 이유: DB 연결 생성 과정을 함수로 캡슐화하여 재사용성 향상
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str) -> None:
    """
    변경 이유: 애플리케이션 시작 시 필요한 테이블을 자동 생성하기 위해 초기화 함수 추가
    """
    logger.info("SQLite DB 초기화 시작: %s", db_path)
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()

        # 원본 상품 저장 테이블
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ownerclan_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        # Smart Store 등록 로그 테이블
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS smartstore_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                status TEXT NOT NULL,        -- SUCCESS 또는 FAIL
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        conn.commit()
        logger.info("SQLite DB 초기화 완료")
    finally:
        conn.close()


def save_raw_product(db_path: str, product_id: str, raw_product: object) -> None:
    """
    변경 이유: Ownerclan 원본 상품 JSON을 그대로 저장하여 나중에 디버깅과 추적이 가능하도록 하기 위함
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        raw_json = json.dumps(raw_product, ensure_ascii=False)
        cursor.execute(
            """
            INSERT INTO ownerclan_products (product_id, raw_json, created_at)
            VALUES (?, ?, ?)
            """,
            (product_id, raw_json, now),
        )
        conn.commit()
        logger.info("원본 상품 JSON 저장 완료 (product_id=%s)", product_id)
    finally:
        conn.close()


def save_smartstore_log(db_path: str, product_id: str, status: str, message: str) -> None:
    """
    변경 이유: Smart Store 등록 성공/실패 이력을 남겨 추후 문제 분석을 쉽게 하기 위함
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute(
            """
            INSERT INTO smartstore_logs (product_id, status, message, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (product_id, status, message, now),
        )
        conn.commit()
        logger.info("Smart Store 로그 저장 완료 (product_id=%s, status=%s)", product_id, status)
    finally:
        conn.close()


def is_already_registered(db_path: str, product_id: str) -> bool:
    """
    변경 이유: 대량 등록 시 이미 SUCCESS로 등록된 상품은 중복 등록을 피하기 위해 사전 체크가 필요함
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 1
            FROM smartstore_logs
            WHERE product_id = ? AND status = 'SUCCESS'
            LIMIT 1
            """,
            (product_id,),
        )
        row = cursor.fetchone()
        return row is not None
    finally:
        conn.close()


def get_latest_logs(
    db_path: str,
    limit: int = 10,
) -> Tuple[list, list]:
    """
    변경 이유: Streamlit UI에서 최근 저장된 원본 상품 및 등록 로그를 확인할 수 있게 하기 위함
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT product_id, raw_json, created_at
            FROM ownerclan_products
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        products = cursor.fetchall()

        cursor.execute(
            """
            SELECT product_id, status, message, created_at
            FROM smartstore_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        logs = cursor.fetchall()

        return list(products), list(logs)
    finally:
        conn.close()