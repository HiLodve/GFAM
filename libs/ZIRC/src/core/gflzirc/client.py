import json
import time
import os
import random
import requests
from .crypto import gf_authcode

class GFLClient:
    def __init__(self, uid: str, sign_key: str, base_url: str):
        self.uid = uid
        self.sign_key = sign_key
        self.base_url = base_url.rstrip('/')
        # GFAM can run a foreground module and the fairy-auto helper at the same
        # time.  Seed the 5-digit req counter per process to avoid two clients
        # generating the same timestamp+00001 req_id in the same second.
        seed = (os.getpid() * 131 + random.randint(1, 9999)) % 90000
        self.req_idx = max(1, seed)
        self.session = requests.Session()
        
        # Force requests to bypass any residual proxy settings
        self.session.proxies = {
            "http": None,
            "https": None
        }
        
        self.session.headers.update({
            "User-Agent": "UnityPlayer/2018.4.36f1 (UnityWebRequest/1.0, libcurl/7.52.0-DEV)",
            "X-Unity-Version": "2018.4.36f1",
            "Content-Type": "application/x-www-form-urlencoded"
        })

    def _get_req_id(self):
        timestamp = int(time.time())
        counter = int(self.req_idx) % 100000
        req_id = f"{timestamp}{counter:05d}"
        self.req_idx = (int(self.req_idx) + 1) % 100000
        if self.req_idx <= 0:
            self.req_idx = 1
        return req_id

    def send_request(self, endpoint: str, payload: dict, max_retries: int = 3, timeout: int = 15):
        """
        Sends an encrypted request to the GFL server.

        Plaintext responses such as "0" can happen when the server rejects a
        duplicate/timing-sensitive request.  Retrying with a fresh req_id is
        safer than treating the first short plaintext body as a hard failure.
        """
        endpoint = "/" + endpoint.lstrip('/')
        url = f"{self.base_url}{endpoint}"
        last_plaintext = None

        for attempt in range(max_retries):
            try:
                json_str = json.dumps(payload, separators=(',', ':'))
                encrypted = gf_authcode(json_str, 'ENCODE', self.sign_key)
                data = {
                    "uid": self.uid,
                    "req_id": self._get_req_id(),
                    "outdatacode": encrypted
                }

                response = self.session.post(url, data=data, timeout=timeout)
                text = response.text.strip()
                
                if text.startswith("#"):
                    decrypted_str = gf_authcode(text[1:], 'DECODE', self.sign_key)
                    if decrypted_str:
                        try:
                            return json.loads(decrypted_str)
                        except json.JSONDecodeError:
                            return {"error_local": "JSON parse error", "raw": decrypted_str}
                    else:
                        return {"error_local": "Decryption failed.", "raw": text}
                elif text.startswith("{") or text.startswith("["):
                    try:
                        return json.loads(text)
                    except Exception:
                        pass
                elif text.startswith("1"):
                    return {"success": True, "raw": text}

                last_plaintext = text
                if attempt < max_retries - 1:
                    time.sleep(0.35 + 0.15 * attempt)
                    continue

                preview = (text[:200] + "...") if len(text) > 200 else text
                return {
                    "error_local": "Unexpected plaintext response",
                    "raw": text,
                    "raw_preview": preview,
                    "status_code": response.status_code,
                }
                
            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    return {"error_local": f"Network Exception after {max_retries} retries: {str(e)}"}
                time.sleep(2)

        return {"error_local": "Unexpected plaintext response", "raw": last_plaintext or ""}
