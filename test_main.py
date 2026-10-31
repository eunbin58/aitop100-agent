import unittest
from unittest.mock import AsyncMock, patch

import main


class KnowledgeTests(unittest.TestCase):
    def test_ai_instructions_do_not_treat_public_examples_as_live_order_facts(self):
        self.assertIn("현재 고객에게 확인된 사실이 아닙니다", main.AI_INSTRUCTIONS)
        self.assertIn("섭취 여부와 신체 이상 여부", main.AI_INSTRUCTIONS)
        self.assertIn("조회 실패 문구를 쓰지 말고", main.AI_INSTRUCTIONS)

    def test_retrieval_finds_policy_and_promotion(self):
        self.assertIn("7일", main.search_knowledge("하자 환불 신고기간"))
        self.assertIn("DANGOL5", main.search_knowledge("단골 할인 쿠폰"))

    def test_retrieval_finds_new_interview_rules(self):
        result = main.search_knowledge("배송지 변경 집하 전 상세주소")
        self.assertIn("집하 전", result)
        self.assertIn("동·호수", result)

    def test_current_policy_ranks_above_old_leaflet(self):
        result = main.search_knowledge("신선식품 하자 접수 기한", limit=6)
        current_position = result.find("D40_current")
        old_position = result.find("D40_old")
        self.assertGreaterEqual(current_position, 0)
        self.assertTrue(old_position == -1 or current_position < old_position)

    def test_session_id_and_memory(self):
        event = {"d": {"sender": {"id": "customer-1"}}}
        self.assertEqual(main.extract_session_id(event, "callback"), "customer-1")
        main.remember_exchange("customer-1", "주문 문의", "주문번호를 알려주세요")
        self.assertEqual(len(main.get_history("customer-1")), 2)

    def test_refund_needs_reason(self):
        plan = main.select_action_request("주문 100100003 전액 환불해주세요")
        self.assertIn("환불 사유와 상품 또는 배송 상태", plan["missing"])

    def test_refund_without_order_collects_all_missing_fields(self):
        plan = main.select_action_request("환불 신청해줘")
        self.assertIn("주문번호", plan["missing"])
        self.assertIn("환불 금액 또는 전액 여부", plan["missing"])

    def test_information_question_does_not_submit(self):
        self.assertIsNone(main.select_action_request("주문 100100003 환불 정책을 알려주세요"))

    def test_direct_identifiers_use_detail_lookups(self):
        self.assertEqual(
            main.select_action_lookup("배송 SHP-100100004-01 상태 확인해줘")[1],
            "/api/shipments/SHP-100100004-01",
        )
        self.assertEqual(
            main.select_action_lookup("결제 PAY-3706-0001 확인해줘")[1],
            "/api/payments/PAY-3706-0001",
        )

    def test_new_actions_require_their_mandatory_details(self):
        schedule = main.select_action_request("주문 100100003 배송 일정 변경해줘")
        self.assertIn("변경할 날짜(YYYY-MM-DD)", schedule["missing"])
        reship = main.select_action_request("배송 SHP-100100004-01 재배송해줘")
        self.assertIn("재배송 사유와 상품 상태", reship["missing"])
        receipt = main.select_action_request("결제 PAY-3706-0001 현금영수증 발급해줘")
        self.assertIn("현금영수증 발급 번호", receipt["missing"])

    def test_order_change_and_memo_are_parsed(self):
        change = main.select_action_request(
            "주문 100100003 품목을 GAL-STD-1 2개로 변경해줘"
        )
        self.assertEqual(change["requested_items"], ["GAL-STD-1 2개"])
        memo = main.select_action_request(
            "주문 100100003 배송 메모: 문 앞에 놓아주세요 등록해줘"
        )
        self.assertEqual(memo["memo"], "문 앞에 놓아주세요 등록해줘")

    def test_escalation_and_expedite_collect_required_details(self):
        escalation = main.select_action_request("환불 담당자에게 연결해줘")
        self.assertEqual(escalation["lane"], "결제·환불")
        self.assertIn("문의 내용", escalation["missing"][0])
        expedite = main.select_action_request(
            "주문 100100003 긴급 출고해줘"
        )
        self.assertTrue(any("수량" in item for item in expedite["missing"]))
        self.assertTrue(any("사유" in item for item in expedite["missing"]))


class ActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_refund_is_submitted_as_request(self):
        plan = main.select_action_request(
            "먹지 않았고 몸 이상 없는 곰팡이가 생긴 주문 100100003 전액 환불해주세요"
        )
        with (
            patch.object(
                main,
                "action_get",
                AsyncMock(side_effect=[{"amount": 30000, "status": "PAID"}, []]),
            ),
            patch.object(main, "action_post", AsyncMock(return_value={"refund_id": "RF-1"})) as post,
        ):
            result = await main.execute_action_request(plan, "TC-1")
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(post.await_args.args[1], "TC-1")
        self.assertEqual(post.await_args.args[2]["amount"], 30000)

    async def test_change_of_mind_refund_is_rejected(self):
        plan = main.select_action_request("마음에 안 드는 주문 100100003 전액 환불해주세요")
        result = await main.execute_action_request(plan, "TC-1")
        self.assertEqual(result["status"], "rejected")

    async def test_started_shipment_blocks_address_change(self):
        plan = main.select_action_request(
            "주문 100100003 배송지 변경 신청 새 주소: 서울시 강남구 테헤란로 1, 그 주문 맞아요"
        )
        with patch.object(
            main,
            "action_get",
            AsyncMock(return_value=[{"status": "IN_TRANSIT"}]),
        ):
            result = await main.execute_action_request(plan, "TC-1")
        self.assertEqual(result["status"], "rejected")

    async def test_missing_test_case_never_calls_action_api(self):
        with patch.object(main, "action_get", AsyncMock()) as get:
            result = await main.process_action("주문 100100003 배송 조회", None)
        self.assertEqual(result["status"], "unavailable")
        get.assert_not_awaited()

    async def test_missing_refund_reason_is_requested_before_test_case(self):
        with (
            patch.object(main, "action_get", AsyncMock()) as get,
            patch.object(main, "action_post", AsyncMock()) as post,
        ):
            result = await main.process_action(
                "주문번호는 100100003이고 전액 환불해줘",
                None,
            )
        self.assertEqual(result["status"], "needs_information")
        self.assertIn("환불 사유와 상품 또는 배송 상태", result["missing"])
        get.assert_not_awaited()
        post.assert_not_awaited()

    async def test_ready_shipment_allows_schedule_change_request(self):
        plan = main.select_action_request(
            "주문 100100003 배송 일정을 2037-06-30으로 변경해줘"
        )
        with (
            patch.object(main, "action_get", AsyncMock(return_value=[{"status": "READY"}])),
            patch.object(main, "action_post", AsyncMock(return_value={"request_id": "SC-1"})) as post,
        ):
            result = await main.execute_action_request(plan, "TC-1")
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(post.await_args.args[2], {"requested_date": "2037-06-30"})

    async def test_refund_details_are_collected_across_messages(self):
        session_id = "multi-turn-refund"
        main._sessions.pop(session_id, None)
        first = await main.process_action("환불 신청해줘", "TC-1", session_id)
        second = await main.process_action("주문번호는 100100003이야", "TC-1", session_id)
        self.assertEqual(first["status"], "needs_information")
        self.assertEqual(second["status"], "needs_information")
        with (
            patch.object(
                main,
                "action_get",
                AsyncMock(side_effect=[{"amount": 30000, "status": "PAID"}, []]),
            ),
            patch.object(main, "action_post", AsyncMock(return_value={"refund_id": "RF-2"})) as post,
        ):
            third = await main.process_action(
                "전액이고 곰팡이가 생겼지만 먹지 않았고 몸 이상 없어",
                "TC-1",
                session_id,
            )
        self.assertEqual(third["status"], "submitted")
        self.assertEqual(post.await_args.args[2]["order_no"], "100100003")
        self.assertNotIn("pending_action_text", main._sessions[session_id])

    async def test_other_member_order_is_blocked_and_handed_off(self):
        with (
            patch.object(
                main,
                "action_get",
                AsyncMock(return_value={"order_no": "100100033", "member_id": "MB-OTHER"}),
            ),
            patch.object(main, "action_post", AsyncMock(return_value={"escalation_id": "E-1"})) as post,
        ):
            result = await main.lookup_action(
                "주문 100100033 배송 상태 알려줘",
                "TC-X",
                "MB-ME",
            )
        self.assertEqual(result["reason"], "order_owner_mismatch")
        self.assertNotIn("result", result)
        self.assertEqual(post.await_args.args[2]["lane"], "LANE2_HANDOFF")

    async def test_safety_refund_with_same_lot_report_creates_separate_handoff(self):
        plan = main.select_action_request(
            "먹지 않았고 몸 이상 없는 곰팡이 주문 100100003 전액 환불해주세요"
        )
        with (
            patch.object(
                main,
                "action_get",
                AsyncMock(
                    side_effect=[
                        {"amount": 30000, "status": "PAID"},
                        [{"lot_id": "LOT-1"}],
                        {"lot_id": "LOT-1"},
                        None,
                        [{"ticket_id": "T-1"}],
                    ]
                ),
            ),
            patch.object(
                main,
                "action_post",
                AsyncMock(side_effect=[{"refund_id": "RF-1"}, {"escalation_id": "E-2"}]),
            ) as post,
        ):
            result = await main.execute_action_request(plan, "TC-X")
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(post.await_count, 2)
        self.assertEqual(post.await_args_list[1].args[2]["lane"], "LANE2_HANDOFF")

    async def test_unconfirmed_medical_claim_is_handed_to_claim_lane(self):
        plan = main.select_action_request("주문 100100003 수박 먹고 배탈 나서 병원비 배상 요구")
        with (
            patch.object(main, "action_get", AsyncMock(side_effect=[{"status": "PAID"}, []])),
            patch.object(main, "action_post", AsyncMock(return_value={"escalation_id": "E-3"})) as post,
        ):
            result = await main.execute_action_request(plan, "TC-X")
        self.assertFalse(result["details"]["liability_confirmed"])
        self.assertFalse(result["details"]["refund_submitted"])
        self.assertEqual(post.await_args.args[2]["lane"], "LANE3_CLAIM")

    async def test_price_drop_uses_care_coupon_and_not_cash_refund(self):
        plan = main.select_action_request("주문 100100003 어제 샀는데 가격 인하 차액 돌려줘")
        with (
            patch.object(
                main,
                "action_get",
                AsyncMock(
                    side_effect=[
                        {
                            "member_id": "MB-1",
                            "items": [{"sku": "SKU-1", "unit_price": 32000, "qty": 1}],
                        },
                        {"sku": "SKU-1", "price": 27900},
                    ]
                ),
            ),
            patch.object(main, "action_post", AsyncMock(return_value={"request_id": "CP-1"})) as post,
        ):
            result = await main.execute_action_request(plan, "TC-X")
        self.assertEqual(result["details"]["promo_code"], "CARE5000")
        self.assertFalse(result["details"]["cash_refund_submitted"])
        self.assertIn("coupon-issue-requests", post.await_args.args[0])

    def test_weather_reship_parses_without_confusing_invoice_with_pickup(self):
        plan = main.select_action_request("결항 때문에 배송 SHP-100100004-01 재배송해줘")
        self.assertEqual(plan["missing"], [])
        self.assertIn("결항", plan["reason"])

    async def test_address_change_follows_l03_confirmation_flow(self):
        session_id = "l03-address"
        main._sessions.pop(session_id, None)
        first = await main.process_action(
            "주소 잘못 넣었어요. 경기 성남시로 바꿔주세요",
            "L-03",
            session_id,
        )
        second = await main.process_action("주문번호는 100100003이에요", "L-03", session_id)
        third = await main.process_action(
            "변경할 주소: 경기 성남시 분당구 판교로 123 101동 202호",
            "L-03",
            session_id,
        )
        self.assertEqual(first["missing"], ["배송지를 변경할 주문번호"])
        self.assertIn("상세주소", second["missing"][0])
        self.assertIn("맞는지 확인", third["missing"][0])
        with (
            patch.object(main, "action_get", AsyncMock(return_value=[])) as get,
            patch.object(main, "action_post", AsyncMock(return_value={"request_id": "AC-1"})) as post,
        ):
            fourth = await main.process_action("네, 그 주문 맞아요", "L-03", session_id)
        self.assertEqual(fourth["status"], "submitted")
        self.assertEqual(get.await_args.args[0], "/api/shipments")
        self.assertEqual(post.await_args.args[2]["new_address"], "경기 성남시 분당구 판교로 123 101동 202호")

    async def test_pending_action_can_be_cancelled_or_replaced(self):
        cancel_session = "cancel-pending"
        main._sessions.pop(cancel_session, None)
        await main.process_action("환불 신청해줘", "TC-1", cancel_session)
        cancelled = await main.process_action("그만할게요", "TC-1", cancel_session)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertNotIn("pending_action_text", main._sessions[cancel_session])

        switch_session = "switch-pending"
        main._sessions.pop(switch_session, None)
        await main.process_action("환불 신청해줘", "TC-1", switch_session)
        switched = await main.process_action(
            "배송지를 변경해줘",
            "TC-1",
            switch_session,
        )
        self.assertEqual(switched["type"], "배송지 변경 접수")
        self.assertIn("주문번호", switched["missing"][0])


if __name__ == "__main__":
    unittest.main()
