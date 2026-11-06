import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from openai_codex.generated.v2_all import GetAccountRateLimitsResponse, GetAccountResponse
from openai_codex.errors import MethodNotFoundError

from quizchirp.config import Settings
from quizchirp.engine import Engine, ACCESS_UNVERIFIED


class AnswerResults(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = Engine.__new__(Engine)
        self.engine.settings = Settings()
        self.engine.workdir = str(Path.cwd())
        self.engine.client = AsyncMock()
        self.engine.client._client.request.return_value = SimpleNamespace(data=[])
        self.thread = self.engine.client.thread_start.return_value
        self.turn = self.thread.turn.return_value
        self.result = SimpleNamespace(
            error=None, status=SimpleNamespace(value="completed"), final_response=None,
        )
        self.turn.run.return_value = self.result

    async def test_all_six_answers_pass_schema_and_result_validation(self):
        for answer in ("A", "B", "C", "D", "E", "F", "FAIL"):
            with self.subTest(answer=answer):
                self.result.final_response = json.dumps({"answer": answer})
                self.assertEqual(await self.engine.solve([Path("question.png")]), answer)
                schema = self.thread.turn.call_args.kwargs["output_schema"]
                self.assertIn(answer, schema["properties"]["answer"]["enum"])

    async def test_out_of_range_multiple_and_malformed_answers_fail(self):
        for response in (
            {"answer": "G"}, {"answer": "A,B"}, {"answer": ["A", "B"]},
            {"answer": "e"}, {"answer": 6}, {"answer": None},
            {"answer": "E", "extra": True}, {}, ["F"],
        ):
            with self.subTest(response=response):
                self.result.final_response = json.dumps(response)
                self.assertEqual(await self.engine.solve([Path("question.png")]), "FAIL")
        schema = self.thread.turn.call_args.kwargs["output_schema"]
        self.assertNotIn("G", schema["properties"]["answer"]["enum"])
        self.result.final_response = "F"
        self.assertEqual(await self.engine.solve([Path("question.png")]), "FAIL")


class AccessChecks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = Engine.__new__(Engine)
        self.engine.client = AsyncMock()
        self.engine.client.account.return_value = GetAccountResponse.model_validate({
            "account": {"type": "chatgpt", "email": None, "planType": "pro"}, "requiresOpenaiAuth": True})

    async def test_only_authoritative_usage_permission_confirms_recovery(self):
        for allowed, snapshot, expected in (
            (True, {}, "Ready"),
            (False, {}, "Usage limit reached"),
            (None, {"primary": {"usedPercent": 0, "resetsAt": 1}}, ACCESS_UNVERIFIED),
            (None, {"primary": {"usedPercent": 100, "resetsAt": 1}}, ACCESS_UNVERIFIED),
            (None, {"rateLimitReachedType": "rate_limit_reached"}, "Usage limit reached"),
            (True, {"spendControlReached": True}, "Usage limit reached"),
        ):
            with self.subTest(allowed=allowed, snapshot=snapshot):
                self.engine.client._client.request.return_value = GetAccountRateLimitsResponse.model_validate(
                    {"ordinaryUsageAllowed": allowed, "rateLimits": snapshot})
                self.assertEqual(await self.engine.check_access(), expected)
        self.assertEqual(self.engine.client._client.request.call_args.args[0], "account/rateLimits/read")
        self.engine.client.thread_start.assert_not_awaited()

    async def test_signed_out_and_unsupported_accounts_do_not_claim_ready(self):
        for kind, required, expected in (
            (None, True, "Sign-in required"),
            ("apiKey", True, ACCESS_UNVERIFIED),
            (None, False, ACCESS_UNVERIFIED),
        ):
            with self.subTest(kind=kind, required=required):
                self.engine.client.account.return_value = GetAccountResponse.model_validate({
                    "account": {"type": kind} if kind else None, "requiresOpenaiAuth": required})
                self.assertEqual(await self.engine.check_access(), expected)
        self.engine.client._client.request.assert_not_awaited()
        self.engine.client.account.return_value = GetAccountResponse.model_validate({
            "account": {"type": "chatgpt", "email": None, "planType": "pro"}, "requiresOpenaiAuth": True})
        self.engine.client._client.request.side_effect = MethodNotFoundError(-32601, "Unavailable")
        self.assertEqual(await self.engine.check_access(), ACCESS_UNVERIFIED)

    async def test_network_failure_is_not_mistaken_for_a_successful_account_read(self):
        self.engine.client._client.request.side_effect = ConnectionError("Cannot reach service")
        with self.assertRaises(ConnectionError):
            await self.engine.check_access(refresh_token=True)
        self.engine.client.account.assert_awaited_once_with(refresh_token=True)
