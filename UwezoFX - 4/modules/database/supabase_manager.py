# modules/database/supabase_manager.py
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Tuple, Optional, Dict
import requests
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
                print(f"⚠️ Brevo initialization failed: {e}")

        self.sms_available = False
        if Settings.AT_USERNAME and Settings.AT_API_KEY:
            try:
                import africastalking
                africastalking.initialize(Settings.AT_USERNAME, Settings.AT_API_KEY)
                self.sms = africastalking.SMS
                self.sms_available = True
            except Exception as e:
                print(f"⚠️ Africa's Talking init failed: {e}")

        self.admin_phone = Settings.ADMIN_PHONE

    def _make_request(self, method: str, endpoint: str, data: dict = None, params: dict = None) -> dict:
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

    def _send_admin_sms(self, username: str, email: str, phone: str):
        if not self.sms_available:
            return
        message = f"New user waiting approval: {username}\nEmail: {email}\nPhone: {phone}"
        try:
            response = self.sms.send(message, [self.admin_phone])
            print(f"📱 SMS sent to admin: {response}")
        except Exception as e:
            print(f"❌ Failed to send SMS: {e}")

    def _send_admin_notification(self, username: str, email: str, phone: str):
        if not self.brevo_available:
            return
        try:
            import sib_api_v3_sdk
            send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
                to=[{"email": "admin@uwezofx.com", "name": "Admin"}],
                sender={"name": "UWEZO-FX System", "email": self.from_email},
                subject="New User Registration Pending Approval",
                html_content=f"""
                <html><body>
                <h2>New User Registration</h2>
                <ul>
                    <li><strong>Username:</strong> {username}</li>
                    <li><strong>Email:</strong> {email}</li>
                    <li><strong>Phone:</strong> {phone}</li>
                    <li><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</li>
                </ul>
                <p>Please log in to the admin panel to approve or reject this user.</p>
                </body></html>
                """
            )
            self.brevo_api.send_transac_email(send_smtp_email)
        except Exception:
            pass

    def _send_login_code_email(self, email: str, username: str, login_code: str):
        if not self.brevo_available:
            return
        try:
            import sib_api_v3_sdk
            send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
                to=[{"email": email, "name": username}],
                sender={"name": "UWEZO-FX Trading", "email": self.from_email},
                subject="Your UWEZO-FX Account Has Been Approved",
                html_content=f"""
                <html><body>
                <h2>Account Approved!</h2>
                <p>Hello {username},</p>
                <p>Your UWEZO-FX trading account has been approved.</p>
                <p>Your login code is:</p>
                <div style="background:#1A253C; padding:20px; text-align:center;">
                    <span style="font-size:32px; color:#2ECC71;">{login_code}</span>
                </div>
                <p>Use this code along with your username to log in.</p>
                </body></html>
                """
            )
            self.brevo_api.send_transac_email(send_smtp_email)
        except Exception as e:
            print(f"Failed to send login code email: {e}")

    def register_user(self, username: str, email: str, phone: str, password: str) -> Tuple[bool, str]:
        if not username or not email or not phone or not password:
            return False, "All fields are required"
        if len(username) < 3:
            return False, "Username must be at least 3 characters"
        if len(password) < 6:
            return False, "Password must be at least 6 characters"
        if '@' not in email or '.' not in email:
            return False, "Invalid email address"
        if not phone.startswith('+') or len(phone) < 10:
            return False, "Invalid phone number. Use format: +254XXXXXXXXX"

        result = self._make_request('GET', 'users', params={
            'username': f'eq.{username}', 'select': 'id'
        })
        if result and not isinstance(result, dict) and len(result) > 0:
            return False, "Username already exists"

        result = self._make_request('GET', 'users', params={
            'email': f'eq.{email}', 'select': 'id'
        })
        if result and not isinstance(result, dict) and len(result) > 0:
            return False, "Email already registered"

        result = self._make_request('GET', 'users', params={
            'phone_number': f'eq.{phone}', 'select': 'id'
        })
        if result and not isinstance(result, dict) and len(result) > 0:
            return False, "Phone number already registered"

        password_hash = hashlib.sha256(password.encode()).hexdigest()
        user_data = {
            'username': username,
            'email': email,
            'phone_number': phone,
            'password_hash': password_hash,
            'status': 'pending',
            'created_at': datetime.now().isoformat(),
            'is_active': True
        }
        result = self._make_request('POST', 'users', data=user_data)
        if 'error' in result:
            return False, f"Registration failed: {result['error']}"

        self._send_admin_notification(username, email, phone)
        self._send_admin_sms(username, email, phone)

        return True, "Registration successful! Your account is pending admin approval."

    def login(self, username: str, login_code: str) -> Tuple[bool, str, dict]:
        result = self._make_request('GET', 'users', params={
            'username': f'eq.{username}',
            'login_code': f'eq.{login_code}',
            'select': 'id,username,email,status,is_active,profile_photo'
        })
        if not result or isinstance(result, dict) or len(result) == 0:
            return False, "Invalid username or login code", {}

        user = result[0]
        if not user.get('is_active', False):
            return False, "Account is deactivated", {}
        status = user.get('status')
        if status == 'pending':
            return False, "Your account is pending admin approval", {}
        elif status == 'rejected':
            return False, "Your registration was rejected", {}
        elif status != 'approved':
            return False, "Account not approved", {}

        self._make_request('PATCH', f"users",
                           params={'id': f'eq.{user["id"]}'},
                           data={'last_login': datetime.now().isoformat()})

        self._make_request('POST', 'audit_log', data={
            'user_id': user['id'],
            'action_type': 'USER_LOGIN',
            'action_details': f'User {username} logged in'
        })

        return True, "Login successful", user

    def request_password_reset(self, email: str) -> Tuple[bool, str]:
        result = self._make_request('GET', 'users', params={
            'email': f'eq.{email}',
            'status': 'eq.approved',
            'is_active': 'eq.true',
            'select': 'id,username,email'
        })
        if not result or isinstance(result, dict) or len(result) == 0:
            return True, "If your email is registered, you will receive a reset link"

        user = result[0]
        reset_token = secrets.token_urlsafe(32)
        expiry = datetime.now() + timedelta(hours=24)

        self._make_request('PATCH', 'users',
                           params={'id': f'eq.{user["id"]}'},
                           data={
                               'reset_token': reset_token,
                               'reset_token_expiry': expiry.isoformat()
                           })

        if self.brevo_available:
            try:
                import sib_api_v3_sdk
                send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
                    to=[{"email": user['email'], "name": user['username']}],
                    sender={"name": "UWEZO-FX Trading", "email": self.from_email},
                    subject="Password Reset Request",
                    html_content=f"""
                    <html><body>
                    <h2>Password Reset Request</h2>
                    <p>Click the button below to reset your password:</p>
                    <div style="text-align:center; margin:30px;">
                        <a href="https://UwezoX2.pythonanywhere.com/reset?token={reset_token}" 
                           style="background:#4F7DF3; color:white; padding:12px 30px; text-decoration:none;">
                            Reset Password
                        </a>
                    </div>
                    <p>Or copy this token: <code>{reset_token}</code></p>
                    </body></html>
                    """
                )
                self.brevo_api.send_transac_email(send_smtp_email)
            except Exception as e:
                print(f"Error sending reset email: {e}")

        return True, "Password reset email sent"

    def reset_password_with_token(self, token: str, new_password: str) -> Tuple[bool, str]:
        result = self._make_request('GET', 'users', params={
            'reset_token': f'eq.{token}',
            'reset_token_expiry': f'gt.{datetime.now().isoformat()}',
            'select': 'id,username'
        })
        if not result or isinstance(result, dict) or len(result) == 0:
            return False, "Invalid or expired reset token"

        user = result[0]
        password_hash = hashlib.sha256(new_password.encode()).hexdigest()

        self._make_request('PATCH', 'users',
                           params={'id': f'eq.{user["id"]}'},
                           data={
                               'password_hash': password_hash,
                               'reset_token': None,
                               'reset_token_expiry': None
                           })

        self._make_request('POST', 'audit_log', data={
            'user_id': user['id'],
            'action_type': 'PASSWORD_RESET_COMPLETED',
            'action_details': 'Password reset completed'
        })

        return True, "Password reset successful"

    def get_user_info(self, user_id: int) -> Optional[Dict]:
        result = self._make_request('GET', 'users', params={
            'id': f'eq.{user_id}',
            'select': 'username,email,profile_photo,created_at,last_login'
        })
        if result and not isinstance(result, dict) and len(result) > 0:
            return result[0]
        return None

    def update_profile_photo(self, user_id: int, photo_path: str) -> bool:
        result = self._make_request('PATCH', 'users',
                                    params={'id': f'eq.{user_id}'},
                                    data={'profile_photo': photo_path})
        return 'error' not in result