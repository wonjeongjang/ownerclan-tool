"""
변경 이유: 실제 Ownerclan 인증/GraphQL 엔드포인트를 사용하도록 수정하고,
           인증 테스트 버튼과 상세 응답 표시 기능을 추가
"""

import json
import logging
import time
from typing import Dict, Optional

import streamlit as st

from config import AppConfig, load_config
from db import get_latest_logs, init_db, is_already_registered, save_raw_product, save_smartstore_log
from ownerclan_auth import OwnerclanAuthError, get_ownerclan_jwt, request_ownerclan_auth
from ownerclan_bulk import OwnerclanBulkError, fetch_all_items
from ownerclan_product import (
    OwnerclanProductError,
    fetch_ownerclan_product,
    request_ownerclan_product_debug,
    build_ownerclan_product_payload,
    DEFAULT_OWNERCLAN_PRODUCT_QUERY,
)
from smartstore_api import SmartStoreRegisterError, register_product_to_smartstore
from smartstore_transform import transform_ownerclan_to_smartstore

logger = logging.getLogger(__name__)


def _init_app() -> AppConfig:
    """
    변경 이유: 설정 로드와 DB 초기화를 한 번에 처리하여 앱 시작 코드를 단순화
    """
    config = load_config()
    init_db(config.db_path)
    return config


def main() -> None:
    """
    변경 이유: Streamlit 앱의 메인 엔트리 포인트로 전체 UI와 흐름을 구성
    """
    st.set_page_config(page_title="Ownerclan → Smart Store 상품 연동(MVP)", layout="wide")
    st.title("Ownerclan → Smart Store 상품 연동 (Phase 1 MVP)")

    config = _init_app()

    # 사이드바에 환경 및 설정 정보 표시
    with st.sidebar:
        st.header("환경 정보")
        st.write(f"APP_ENV: **{config.env}**")
        st.write(f"DB 경로: `{config.db_path}`")
        st.write(f"로그 레벨: `{config.log_level}`")

        st.markdown("---")
        st.subheader("Ownerclan 설정")
        st.write(f"ENV: `{config.ownerclan.env}`")
        st.write(f"Auth URL: `{config.ownerclan.auth_url}`")
        st.write(f"GraphQL URL: `{config.ownerclan.graphql_url}`")

        st.subheader("Smart Store 설정")
        st.write(f"Base URL: `{config.smartstore.base_url}`")
        st.write(f"Register Endpoint: `{config.smartstore.register_endpoint}`")

    tab_single, tab_bulk = st.tabs(["단일 등록", "대량 등록"])

    with tab_single:
        # 0. Ownerclan 인증 테스트
        st.subheader("0. Ownerclan 인증 테스트")

        if st.button("Ownerclan Auth 테스트 실행"):
            try:
                auth_result = request_ownerclan_auth(config.ownerclan)
            except OwnerclanAuthError as exc:
                st.error(f"Ownerclan 인증 요청 실패: {exc}")
            else:
                st.markdown("**요청 대상 URL**")
                st.code(auth_result.get("url", ""), language="text")

                st.markdown("**HTTP 상태 코드**")
                st.code(str(auth_result.get("status_code")), language="text")

                token_value = auth_result.get("token", "")
                if isinstance(token_value, str) and token_value:
                    # 토큰 미리보기(마스킹)
                    preview = token_value[:12] + "..." if len(token_value) > 15 else token_value
                    st.success("Ownerclan 인증 성공, 토큰을 정상적으로 발급받았습니다.")
                    st.markdown("**토큰 미리보기(마스킹)**")
                    st.code(preview, language="text")
                else:
                    st.error("응답에서 토큰을 추출하지 못했습니다. raw 응답을 확인해 주세요.")

                st.markdown("**파싱된 응답 JSON**")
                response_json = auth_result.get("response_json")
                if isinstance(response_json, Dict) and response_json:
                    st.json(response_json)
                else:
                    st.info("JSON 형식 응답이 없거나 비어 있습니다.")

                st.markdown("**원문 응답 본문 (Raw)**")
                with st.expander("원문 응답 본문 열기", expanded=False):
                    st.code(auth_result.get("raw_text", ""), language="text")

        st.markdown("---")

        # 메인 영역: 상품 ID 입력 및 버튼
        st.subheader("1. Ownerclan에서 상품 1개 가져오기 (GraphQL)")

        product_id = st.text_input("상품 ID 입력 (Ownerclan 기준)", value="")

        col1, col2 = st.columns(2)

        # 세션 상태에 현재 상품 원본 / 변환 데이터 보관
        if "raw_product" not in st.session_state:
            st.session_state["raw_product"] = None
        if "transformed_product" not in st.session_state:
            st.session_state["transformed_product"] = None
        if "current_product_id" not in st.session_state:
            st.session_state["current_product_id"] = None

        with col1:
            if st.button("Ownerclan에서 상품 불러오기"):
                if not product_id:
                    st.warning("먼저 상품 ID를 입력해 주세요.")
                else:
                    # 1) JWT 발급
                    try:
                        jwt_token = get_ownerclan_jwt(config.ownerclan)
                    except OwnerclanAuthError as exc:
                        st.error(f"Ownerclan 인증 실패: {exc}")
                        save_smartstore_log(
                            config.db_path,
                            product_id=product_id,
                            status="FAIL",
                            message=f"Ownerclan 인증 실패: {exc}",
                        )
                        return

                    # 2) GraphQL payload 사전 생성 및 검증 (mutation 용도, 현 디버그용 유지)
                    try:
                        payload = build_ownerclan_product_payload(config.ownerclan, product_id)
                    except OwnerclanProductError as exc:
                        st.error(str(exc))
                        save_smartstore_log(
                            config.db_path,
                            product_id=product_id,
                            status="FAIL",
                            message=f"Ownerclan GraphQL payload 오류: {exc}",
                        )
                        return

                    # 2-1) 요청 전 payload를 먼저 화면에 출력
                    st.markdown("#### Ownerclan GraphQL 요청 디버그")
                    st.markdown("**사용 중인 GraphQL query 문자열**")
                    st.code(DEFAULT_OWNERCLAN_PRODUCT_QUERY, language="graphql")

                    st.markdown("**요청 Body(JSON) - 전송 전**")
                    st.json(payload)

                    # 3) GraphQL 디버그 요청 수행
                    try:
                        debug_result = request_ownerclan_product_debug(
                            config.ownerclan,
                            jwt_token=jwt_token,
                            product_id=product_id,
                        )
                    except OwnerclanProductError as exc:
                        st.error(f"Ownerclan 상품 조회 실패(네트워크 오류): {exc}")
                        save_smartstore_log(
                            config.db_path,
                            product_id=product_id,
                            status="FAIL",
                            message=f"Ownerclan 상품 조회 실패(네트워크 오류): {exc}",
                        )
                        return

                    # 3-1. GraphQL 요청/응답 디버그 뷰
                    st.markdown("**요청 URL**")
                    st.code(debug_result.get("url", ""), language="text")

                    st.markdown("**요청 헤더 (Authorization 토큰은 일부만 표시)**")
                    st.json(debug_result.get("request_headers", {}))

                    st.markdown("**요청 Body(JSON) - 서버에 전송된 값**")
                    st.json(debug_result.get("request_body", {}))

                    st.markdown("**HTTP 상태 코드**")
                    st.code(str(debug_result.get("status_code")), language="text")

                    st.markdown("**파싱된 응답 JSON**")
                    response_json = debug_result.get("response_json", {})
                    if isinstance(response_json, Dict) and response_json:
                        st.json(response_json)
                    else:
                        st.info("응답 JSON이 없거나 비어 있습니다.")

                    st.markdown("**원문 응답 본문 (Raw)**")
                    with st.expander("원문 응답 본문 열기", expanded=False):
                        st.code(debug_result.get("raw_text", ""), language="text")

                    if not debug_result.get("ok", False):
                        # 실패 시에는 여기서 종료하고, 상세 디버그 정보만 남김
                        st.error("Ownerclan GraphQL 상품 조회가 실패했습니다. 위 디버그 정보를 확인해 주세요.")
                        save_smartstore_log(
                            config.db_path,
                            product_id=product_id,
                            status="FAIL",
                            message=f"Ownerclan 상품 조회 실패 (status={debug_result.get('status_code')})",
                        )
                        return

                    # 3-2. 성공 시 원본 상품 JSON으로 사용
                    raw_product = response_json

                    # 원본 상품 저장
                    save_raw_product(config.db_path, product_id=product_id, raw_product=raw_product)

                    # Smart Store용 변환
                    transformed_product = transform_ownerclan_to_smartstore(
                        raw_product=raw_product,
                    )

                    # 세션 상태에 저장
                    st.session_state["raw_product"] = raw_product
                    st.session_state["transformed_product"] = transformed_product
                    st.session_state["current_product_id"] = product_id

                    st.success("상품 조회 및 변환 완료. 아래에서 내용을 확인하세요.")

        st.subheader("2. 원본/변환 데이터 미리보기")

        col_raw, col_transformed = st.columns(2)

        with col_raw:
            st.markdown("**Ownerclan 원본 상품 JSON**")
            if st.session_state["raw_product"] is not None:
                st.json(st.session_state["raw_product"])
            else:
                st.info("아직 불러온 상품이 없습니다.")

        with col_transformed:
            st.markdown("**Smart Store 등록용 변환 데이터**")
            if st.session_state["transformed_product"] is not None:
                st.json(st.session_state["transformed_product"])
            else:
                st.info("아직 변환된 데이터가 없습니다.")

        st.subheader("3. Smart Store에 상품 등록 테스트")

        if st.button("Smart Store 등록 테스트 실행"):
            current_product_id: Optional[str] = st.session_state.get("current_product_id")
            transformed = st.session_state.get("transformed_product")

            if not current_product_id or transformed is None:
                st.warning("먼저 'Ownerclan에서 상품 불러오기'를 통해 상품을 조회해 주세요.")
            else:
                try:
                    result = register_product_to_smartstore(
                        config.smartstore,
                        product_data=transformed,
                    )
                    message_text = json.dumps(result, ensure_ascii=False)
                    save_smartstore_log(
                        config.db_path,
                        product_id=current_product_id,
                        status="SUCCESS",
                        message=message_text,
                    )
                    st.success("Smart Store 등록 테스트 성공")
                    st.json(result)
                except SmartStoreRegisterError as exc:
                    error_message = str(exc)
                    save_smartstore_log(
                        config.db_path,
                        product_id=current_product_id,
                        status="FAIL",
                        message=error_message,
                    )
                    st.error(f"Smart Store 등록 테스트 실패: {exc}")

        st.subheader("4. 최근 저장된 기록 확인")

        products, logs = get_latest_logs(config.db_path, limit=5)

        col_p, col_l = st.columns(2)

        with col_p:
            st.markdown("**최근 저장된 Ownerclan 원본 상품 (상위 5개)**")
            if not products:
                st.write("저장된 상품이 아직 없습니다.")
            else:
                for row in products:
                    st.write(f"- Product ID: `{row['product_id']}`, 저장 시각: {row['created_at']}")
                    with st.expander("원본 JSON 보기", expanded=False):
                        try:
                            data = json.loads(row["raw_json"])
                        except json.JSONDecodeError:
                            data = {"raw": row["raw_json"]}
                        st.json(data)

        with col_l:
            st.markdown("**최근 Smart Store 등록 로그 (상위 5개)**")
            if not logs:
                st.write("등록 로그가 아직 없습니다.")
            else:
                for row in logs:
                    st.write(
                        f"- Product ID: `{row['product_id']}`, "
                        f"Status: **{row['status']}**, "
                        f"시각: {row['created_at']}"
                    )
                    with st.expander("메시지 보기", expanded=False):
                        st.text(row["message"])

    with tab_bulk:
        st.subheader("대량 등록")

        if "bulk_items" not in st.session_state:
            st.session_state["bulk_items"] = None

        st.warning("주의: 상품이 많을수록 조회 시간이 길어집니다. 처음에는 200개부터 테스트하세요.")

        fetch_size = st.number_input(
            "한 번에 불러올 상품 수",
            min_value=50,
            max_value=1000,
            value=200,
            step=50,
        )

        if st.button("오너클랜 전체 상품 불러오기"):
            try:
                jwt_token = get_ownerclan_jwt(config.ownerclan)
                items = fetch_all_items(config.ownerclan, jwt_token=jwt_token, first=int(fetch_size))
            except OwnerclanAuthError as exc:
                st.error(f"Ownerclan 인증 실패: {exc}")
                return
            except OwnerclanBulkError as exc:
                st.error(f"Ownerclan 전체 상품 조회 실패: {exc}")
                return

            st.session_state["bulk_items"] = items
            st.success(f"전체 상품 불러오기 완료: {len(items)}개")

        bulk_items = st.session_state.get("bulk_items")
        if isinstance(bulk_items, list):
            st.write(f"현재 로드된 상품 수: **{len(bulk_items)}개**")

            if st.button("스마트스토어 대량 등록 시작"):
                total = len(bulk_items)
                if total == 0:
                    st.warning("등록할 상품이 없습니다.")
                    return

                progress = st.progress(0)
                status_box = st.empty()

                success_count = 0
                fail_count = 0
                skipped_count = 0

                for idx, item in enumerate(bulk_items):
                    # item dict -> transform 함수 입력 형식으로 래핑
                    raw_wrapper: Dict[str, object] = {"data": {"item": item}}
                    product_key = ""
                    if isinstance(item, dict):
                        key_value = item.get("key")
                        if isinstance(key_value, str):
                            product_key = key_value

                    transformed = transform_ownerclan_to_smartstore(raw_product=raw_wrapper)

                    # 중복 체크: 이미 SUCCESS로 등록된 상품이면 스킵
                    check_id = product_key or f"bulk_{idx}"
                    if product_key and is_already_registered(config.db_path, product_key):
                        skipped_count += 1
                        logger.info("중복 스킵: 이미 등록된 상품 (product_id=%s)", product_key)
                        progress.progress(int(((idx + 1) / total) * 100))
                        status_box.write(
                            f"진행: {idx + 1}/{total} | 완료: 성공 {success_count}개 / 실패 {fail_count}개 / 중복 스킵 {skipped_count}개"
                        )
                        continue

                    # 등록 (429는 대기 후 재시도)
                    retries = 0
                    while True:
                        try:
                            result = register_product_to_smartstore(
                                config.smartstore,
                                product_data=transformed,
                            )
                            save_smartstore_log(
                                config.db_path,
                                product_id=product_key or f"bulk_{idx}",
                                status="SUCCESS",
                                message=json.dumps(result, ensure_ascii=False),
                            )
                            success_count += 1
                            break
                        except SmartStoreRegisterError as exc:
                            msg = str(exc)
                            if "status=429" in msg and retries < 3:
                                retries += 1
                                time.sleep(2)
                                continue

                            save_smartstore_log(
                                config.db_path,
                                product_id=product_key or f"bulk_{idx}",
                                status="FAIL",
                                message=msg,
                            )
                            fail_count += 1
                            break

                    progress.progress(int(((idx + 1) / total) * 100))
                    status_box.write(
                        f"진행: {idx + 1}/{total} | 완료: 성공 {success_count}개 / 실패 {fail_count}개 / 중복 스킵 {skipped_count}개"
                    )

                st.success("대량 등록 완료")
                st.write(f"총 {total}개 / 성공 {success_count}개 / 실패 {fail_count}개 / 중복 스킵 {skipped_count}개")


if __name__ == "__main__":
    main()