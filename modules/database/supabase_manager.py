# modules/database/supabase_manager.py
import hashlib
import secrets
import requests
from datetime import datetime, timedelta
from typing import Tuple, Optional, Dict
from config import Settings

class SupabaseUserManager:
    def __init__(self):
        self.supabase_url = Settings.SUPABASE_URL
        self.supabase_key = Settings.SUPABASE_KEY
        self.headers = {
            'apikey': self.supabase_key,
            'Authorization': f'Bearer {self.supabase_key}',
            'Content-Type': 'application/json',
            'Prefer': 'return=representation'
        }
        
        self.brevo_available = False
        if Settings.BREVO_API_KEY and Settings.FROM_EMAIL:
            try:
                import sib_api_v3_sdk
                configuration = sib_api_v3_sdk.Configuration()
                configuration.api_key['api-key'] = Settings.BREVO_API_KEY
                self.brevo_api = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))
                self.from_email = Settings.FROM_EMAIL
                self.brevo_available = True
            except Exception as e:
                print(f"Brevo init failed: {e}")
        
        self.sms_available = False
        if Settings.AT_USERNAME and Settings.AT_API_KEY:
            try:
                import africastalking
                africastalking.initialize(Settings.AT_USERNAME, Settings.AT_API_KEY)
                self.sms = africastalking.SMS
                self.sms_available = True
            except Exception as e:
                print(f"AT init failed: {e}")
        
        self.admin_phone = Settings.ADMIN_PHONE

    def _make_request(self, method, endpoint, data=None, params=None):
        url = f"{self.supabase_url}/rest/v1/{endpoint}"
        try:
            if method == 'GET':
                response = requests.get(url, headers=self.headers, params=params)
            elif method == 'POST':
                response = requests.post(url, headers=self.headers, json=data)
            elif method == 'PATCH':
                response = requests.patch(url, headers=self.headers, json=data, params=params)
            elif method == 'DELETE':
                response = requests.delete(url, headers=self.headers, json=data, params=params)
            else:
                return {'error': 'Invalid method'}
            if response.status_code >= 400:
                return {'error': f"HTTP {response.status_code}: {response.text}"}
            return response.json() if response.content else {}
        except Exception as e:
            return {'error': str(e)}

    def _send_admin_sms(self, username, email, phone):
        if not self.sms_available:
            return
        message = f"New user: {username}\nEmail: {email}\nPhone: {phone}"
        try:
            self.sms.send(message, [self.admin_phone])
        except Exception:
            pass

    def _send_admin_notification(self, username, email, phone):
        if not self.brevo_available:
            return
        try:
            import sib_api_v3_sdk
            send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
                to=[{"email": "admin@uwezofx.com", "name": "Admin"}],
                sender={"name": "UWEZO-FX System", "email": self.from_email},
                subject="New User Registration Pending Approval",
                html_content=f"<html><body><h2>New User</h2><ul><li>Username: {username}</li><li>Email: {email}</li><li>Phone: {phone}</li></ul></body></html>"
            )
            self.brevo_api.send_transac_email(send_smtp_email)
        except Exception:
            pass

    def register_user(self, username, email, phone, password):
        if len(username) < 3 or len(password) < 6:
            return False, "Username >=3, password >=6"
        if '@' not in email or '.' not in email:
            return False, "Invalid email"
        if not phone.startswith('+') or len(phone) < 10:
            return False, "Phone must start with + and have at least 10 digits"
        
        res = self._make_request('GET', 'users', params={'username': f'eq.{username}', 'select': 'id'})
        if res and not isinstance(res, dict) and len(res) > 0:
            return False, "Username exists"
        res = self._make_request('GET', 'users', params={'email': f'eq.{email}', 'select': 'id'})
        if res and not isinstance(res, dict) and len(res) > 0:
            return False, "Email exists"
        res = self._make_request('GET', 'users', params={'phone_number': f'eq.{phone}', 'select': 'id'})
        if res and not isinstance(res, dict) and len(res) > 0:
            return False, "Phone exists"
        
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        user_data = {
            'username': username, 'email': email, 'phone_number': phone,
            'password_hash': password_hash, 'status': 'pending',
            'created_at': datetime.now().isoformat(), 'is_active': True
        }
        res = self._make_request('POST', 'users', data=user_data)
        if 'error' in res:
            return False, f"Registration failed: {res['error']}"
        
        self._send_admin_notification(username, email, phone)
        self._send_admin_sms(username, email, phone)
        return True, "Registration successful! Pending admin approval."

    def login(self, username, login_code):
        res = self._make_request('GET', 'users', params={
            'username': f'eq.{username}', 'login_code': f'eq.{login_code}',
            'select': 'id,username,email,status,is_active'
        })
        if not res or isinstance(res, dict) or len(res) == 0:
            return False, "Invalid username or login code", {}
        user = res[0]
        if not user.get('is_active'):
            return False, "Account deactivated", {}
        status = user.get('status')
        if status == 'pending':
            return False, "Pending admin approval", {}
        if status == 'rejected':
            return False, "Registration rejected", {}
        if status != 'approved':
            return False, "Account not approved", {}
        
        self._make_request('PATCH', 'users', params={'id': f'eq.{user["id"]}'}, data={'last_login': datetime.now().isoformat()})
        return True, "Login successful", user

    def request_password_reset(self, email):
        res = self._make_request('GET', 'users', params={'email': f'eq.{email}', 'select': 'id,username,email'})
        if not res or isinstance(res, dict) or len(res) == 0:
            return True, "If registered, you will receive a reset link"
        user = res[0]
        token = secrets.token_urlsafe(32)
        expiry = datetime.now() + timedelta(hours=24)
        self._make_request('PATCH', 'users', params={'id': f'eq.{user["id"]}'},
                           data={'reset_token': token, 'reset_token_expiry': expiry.isoformat()})
        if self.brevo_available:
            try:
                import sib_api_v3_sdk
                send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
                    to=[{"email": user['email'], "name": user['username']}],
                    sender={"name": "UWEZO-FX", "email": self.from_email},
                    subject="Password Reset",
                    html_content=f"<html><body><p>Reset token: {token}</p></body></html>"
                )
                self.brevo_api.send_transac_email(send_smtp_email)
            except Exception:
                pass
        return True, "Password reset email sent"

    def reset_password_with_token(self, token, new_password):
        res = self._make_request('GET', 'users', params={'reset_token': f'eq.{token}', 'select': 'id'})
        if not res or isinstance(res, dict) or len(res) == 0:
            return False, "Invalid or expired token"
        user = res[0]
        password_hash = hashlib.sha256(new_password.encode()).hexdigest()
        self._make_request('PATCH', 'users', params={'id': f'eq.{user["id"]}'},
                           data={'password_hash': password_hash, 'reset_token': None, 'reset_token_expiry': None})
        return True, "Password reset successful"