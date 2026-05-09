import asyncio
import websockets
import json

ADMIN_API_TOKEN = "BfQGSYCstinYbMV"
APP_NAME = "UWEZO-FX Bot"

async def register_app():
    uri = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
    async with websockets.connect(uri) as ws:
        # Authorize
        await ws.send(json.dumps({"authorize": ADMIN_API_TOKEN}))
        auth = json.loads(await ws.recv())
        print("Auth response:", auth)  # ← This will show the exact error
        if auth.get('error'):
            return
        # Register app
        await ws.send(json.dumps({"app_register": 1, "name": APP_NAME, "scopes": ["trade", "read"]}))
        resp = json.loads(await ws.recv())
        print("App register response:", resp)

asyncio.run(register_app())