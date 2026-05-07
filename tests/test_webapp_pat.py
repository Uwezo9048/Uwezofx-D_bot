import asyncio
import sys
import types
import unittest
from unittest.mock import patch


class FakeFlask:
    def __init__(self, *args, **kwargs):
        self.wsgi_app = None

    def route(self, *args, **kwargs):
        def decorator(view_func):
            return view_func

        return decorator

    def run(self, *args, **kwargs):
        return None


sys.modules.setdefault(
    "flask",
    types.SimpleNamespace(
        Flask=FakeFlask,
        flash=lambda *args, **kwargs: None,
        jsonify=lambda *args, **kwargs: {},
        redirect=lambda *args, **kwargs: None,
        render_template=lambda *args, **kwargs: "",
        request=types.SimpleNamespace(args={}, form={}, json={}),
        session={},
        url_for=lambda endpoint, **kwargs: f"/{endpoint}",
    ),
)
sys.modules.setdefault(
    "werkzeug.middleware.proxy_fix",
    types.SimpleNamespace(ProxyFix=lambda app, **kwargs: app),
)
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None))
sys.modules.setdefault("requests", types.SimpleNamespace(get=None, post=None, patch=None, delete=None, request=None))
sys.modules.setdefault("websockets", types.SimpleNamespace(connect=None, ConnectionClosedError=ConnectionError))
sys.modules.setdefault(
    "modules.trading.indicator",
    types.SimpleNamespace(
        CombinedICTandSMSIndicator=lambda *args, **kwargs: None,
        TradeSignal=types.SimpleNamespace(
            BUY="BUY",
            SELL="SELL",
            NEUTRAL="NEUTRAL",
            OVER="OVER",
            UNDER="UNDER",
            EVEN="EVEN",
            ODD="ODD",
        ),
    ),
)
sys.modules.setdefault(
    "modules.trading.analyzer",
    types.SimpleNamespace(
        MarketAnalyzer=types.SimpleNamespace(
            calculate_rsi=lambda *args, **kwargs: 50.0,
            moving_average_cross=lambda *args, **kwargs: 0,
        )
    ),
)

from webapp.app import (
    WebBotManager,
    authorize_deriv_token,
    create_pairing_link,
    deriv_non_json_error_message,
    normalize_deriv_token,
    pairing_links,
    pairing_lock,
    parse_deriv_json_response,
    session,
    uses_deriv_options_auth,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", json_error=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


class DerivPatAuthorizationTests(unittest.TestCase):
    def test_parse_deriv_json_response_reports_empty_body(self):
        payload, detail = parse_deriv_json_response(
            FakeResponse(json_error=ValueError("Expecting value"))
        )

        self.assertIsNone(payload)
        self.assertEqual(detail, "empty response")

    def test_pat_authorization_handles_non_json_account_service_response(self):
        with patch(
            "requests.get",
            return_value=FakeResponse(
                status_code=502,
                text="",
                json_error=ValueError("Expecting value: line 1 column 1 (char 0)"),
            ),
        ):
            ok, message, accounts = asyncio.run(authorize_deriv_token("pat_test", 1234))

        self.assertFalse(ok)
        self.assertIsNone(accounts)
        self.assertIn("non-JSON response", message)
        self.assertIn("HTTP 502", message)
        self.assertIn("PAT-type app", message)
        self.assertNotIn("Expecting value", message)

    def test_pat_authorization_handles_invalid_expired_token_response(self):
        with patch(
            "requests.get",
            return_value=FakeResponse(
                status_code=401,
                text="Invalid or expired token",
                json_error=ValueError("Expecting value: line 1 column 1 (char 0)"),
            ),
        ):
            ok, message, accounts = asyncio.run(authorize_deriv_token("pat_test", 1234))

        self.assertFalse(ok)
        self.assertIsNone(accounts)
        self.assertIn("Deriv rejected this PAT token", message)
        self.assertIn("Invalid or expired token", message)
        self.assertIn("Generate a fresh PAT token", message)
        self.assertNotIn("legacy Deriv app IDs", message)

    def test_non_json_401_message_prioritizes_token_guidance(self):
        message = deriv_non_json_error_message(
            FakeResponse(status_code=401),
            "Invalid or expired token",
        )

        self.assertIn("Generate a fresh PAT token", message)
        self.assertNotIn("legacy Deriv app IDs", message)

    def test_pat_authorization_returns_all_accounts_and_sends_alphanumeric_app_id(self):
        with patch(
            "requests.get",
            return_value=FakeResponse(
                status_code=200,
                payload={
                    "data": {
                        "accounts": [
                            {"account_id": "VRTC123", "currency": "USD", "account_type": "demo"},
                            {"account_id": "CR123", "currency": "USD", "account_type": "real"},
                        ]
                    }
                },
            ),
        ) as mock_get:
            ok, message, accounts = asyncio.run(authorize_deriv_token("up32_test", "33cqkvVDkguOv3GBkC6OU"))

        self.assertTrue(ok)
        self.assertEqual(message, "Deriv PAT token connected.")
        self.assertEqual([account["account"] for account in accounts], ["VRTC123", "CR123"])
        self.assertEqual([account["type"] for account in accounts], ["Demo", "Real"])
        self.assertEqual(mock_get.call_args.kwargs["headers"]["Deriv-App-ID"], "33cqkvVDkguOv3GBkC6OU")

    def test_alphanumeric_app_id_uses_options_auth_for_non_pat_prefix(self):
        self.assertTrue(uses_deriv_options_auth("up32_test", "33cqkvVDkguOv3GBkC6OU"))
        self.assertFalse(uses_deriv_options_auth("up32_test", "133059"))

    def test_multiline_token_is_joined_before_notes(self):
        token = """up32xxt9Z38oEO0

9T9357T6

eTwt0mcPs5C2hky

SLZOTRGQ


corrections()
Progressively maximum confidence
"""

        self.assertEqual(
            normalize_deriv_token(token),
            "up32xxt9Z38oEO09T9357T6eTwt0mcPs5C2hkySLZOTRGQ",
        )

    def test_web_config_keeps_alphanumeric_app_id(self):
        manager = WebBotManager()
        manager.state["config"]["app_id"] = "33cqkvVDkguOv3GBkC6OU"

        config = manager._make_config()

        self.assertEqual(config.app_id, "33cqkvVDkguOv3GBkC6OU")

    def test_account_dropdown_selection_updates_token_and_app_id(self):
        manager = WebBotManager()
        manager.remember_deriv_accounts(
            [
                {
                    "token": "demo-token",
                    "account": "VRTC123",
                    "currency": "USD",
                    "type": "Demo",
                    "auth_app_id": "oauth-app",
                },
                {
                    "token": "real-token",
                    "account": "CR123",
                    "currency": "USD",
                    "type": "Real",
                    "auth_app_id": "oauth-app",
                },
            ]
        )

        manager.update_config_from_form({"deriv_account": "CR123"})

        self.assertEqual(manager.get_session_token(), "real-token")
        self.assertEqual(manager.state["config"]["app_id"], "oauth-app")

    def test_pairing_link_can_be_created_before_bot_is_running(self):
        session.clear()
        session["user"] = {"id": "pair-user", "username": "Pair User"}
        with pairing_lock:
            pairing_links.clear()

        create_pairing_link()

        with pairing_lock:
            self.assertEqual(len(pairing_links), 1)

    def test_partial_manual_settings_sync_keeps_adaptive_enabled(self):
        manager = WebBotManager()
        manager.state["config"]["adaptive_enabled"] = "on"

        manager.update_config_from_form({"manual_stake": "7"})

        self.assertEqual(manager.state["config"]["manual_stake"], "7")
        self.assertEqual(manager.state["config"]["adaptive_enabled"], "on")


if __name__ == "__main__":
    unittest.main()
