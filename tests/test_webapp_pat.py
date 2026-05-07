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

from webapp.app import authorize_deriv_token, parse_deriv_json_response


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
            ok, message, account = asyncio.run(authorize_deriv_token("pat_test", 1234))

        self.assertFalse(ok)
        self.assertIsNone(account)
        self.assertIn("non-JSON response", message)
        self.assertIn("HTTP 502", message)
        self.assertIn("PAT-type app", message)
        self.assertNotIn("Expecting value", message)


if __name__ == "__main__":
    unittest.main()
