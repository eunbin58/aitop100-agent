import unittest
from unittest.mock import AsyncMock, patch

import main


class KnowledgeTests(unittest.TestCase):
    def test_retrieval_finds_policy_and_promotion(self):
        self.assertIn("7일", main.search_knowledge("하자 환불 신고기간"))
        self.assertIn("DANGOL5", main.search_knowledge("단골 할인 쿠폰"))

    def test_session_id_and_memory(self):
        event = {"d": {"sender": {"id": "customer-1"}}}
        self.assertEqual(main.extract_session_id(event, "callback"), "customer-1")
        main.remember_exchange("customer-1", "주문 문의", "주문번호를 알려주세요")
        self.assertEqual(len(main.get_history("customer-1")), 2)

    def test_refund_needs_reason(self):
        plan = main.select_action_request("주문 100100003 전액 환불해주세요")
        self.assertIn("환불 사유와 상품 또는 배송 상태", plan["missing"])

    def test_information_question_does_not_submit(self):
        self.assertIsNone(main.select_action_request("주문 100100003 환불 정책을 알려주세요"))


class ActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_refund_is_submitted_as_request(self):
        plan = main.select_action_request("곰팡이가 생긴 주문 100100003 전액 환불해주세요")
        with (
            patch.object(main, "action_get", AsyncMock(return_value={"amount": 30000, "status": "PAID"})),
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
            "주문 100100003 배송지 변경 신청 새 주소: 서울시 강남구 테헤란로 1"
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


if __name__ == "__main__":
    unittest.main()
