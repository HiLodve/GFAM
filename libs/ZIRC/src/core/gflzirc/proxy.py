import socket
import select
import re
import json
import threading
import urllib.parse
from .crypto import gf_authcode

# Cross-platform
try:
    import winreg
    import ctypes
    HAS_WINREG = True
except ImportError:
    HAS_WINREG = False

INTERNET_OPTION_REFRESH = 37
INTERNET_OPTION_SETTINGS_CHANGED = 39

def refresh_windows_proxy():
    if not HAS_WINREG:
        return
    try:
        internet_set_option = ctypes.windll.wininet.InternetSetOptionW
        internet_set_option(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
        internet_set_option(0, INTERNET_OPTION_REFRESH, 0, 0)
    except:
        pass

def set_windows_proxy(enable: bool, proxy_addr="127.0.0.1:8080"):
    if not HAS_WINREG:
        return False
    try:
        reg_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        hKey = winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_WRITE)
        
        if enable:
            winreg.SetValueEx(hKey, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(hKey, "ProxyServer", 0, winreg.REG_SZ, proxy_addr)
        else:
            winreg.SetValueEx(hKey, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            
        winreg.CloseKey(hKey)
        refresh_windows_proxy()
        return True
    except Exception:
        return False

class HttpStreamDecoder:
    """
    Robust HTTP Stream Parser.
    Handles Keep-Alive, Content-Length, and Chunked Transfer-Encoding correctly.
    """
    def __init__(self, is_request=False):
        self.buffer = b""
        self.is_request = is_request

    def push(self, data: bytes):
        self.buffer += data

    def get_messages(self):
        """Returns a list of tuples: (headers_str, body_data)"""
        messages = []
        while b'\r\n\r\n' in self.buffer:
            headers_end = self.buffer.find(b'\r\n\r\n')
            headers_part = self.buffer[:headers_end]
            headers_str = headers_part.decode('ascii', errors='ignore')
            headers_lower = headers_str.lower()
            
            body_start = headers_end + 4
            message_complete = False
            consumed = 0
            body_data = b""
            
            # Robust check for chunked encoding using string instead of bytes
            chunked_match = re.search(r'transfer-encoding:\s*([^\r\n]+)', headers_lower)
            is_chunked = chunked_match and 'chunked' in chunked_match.group(1)
            
            if is_chunked:
                idx = body_start
                while True:
                    chunk_head_end = self.buffer.find(b'\r\n', idx)
                    if chunk_head_end == -1:
                        break  # Wait for more data
                        
                    chunk_size_str = self.buffer[idx:chunk_head_end].split(b';')[0].strip()
                    try:
                        chunk_size = int(chunk_size_str, 16)
                    except ValueError:
                        # Clear corrupted buffer to avoid infinite loop
                        self.buffer = b""
                        break
                        
                    if chunk_size == 0:
                        # Scan for the end of optional trailer headers
                        trailer_end = self.buffer.find(b'\r\n\r\n', chunk_head_end)
                        if trailer_end != -1:
                            message_complete = True
                            consumed = trailer_end + 4
                        break
                        
                    chunk_data_end = chunk_head_end + 2 + chunk_size + 2
                    if len(self.buffer) < chunk_data_end:
                        break  # Wait for more data
                        
                    body_data += self.buffer[chunk_head_end+2 : chunk_head_end+2+chunk_size]
                    idx = chunk_data_end
            else:
                m = re.search(r'content-length:\s*(\d+)', headers_lower)
                if m:
                    content_length = int(m.group(1))
                    if len(self.buffer) >= body_start + content_length:
                        body_data = self.buffer[body_start : body_start + content_length]
                        message_complete = True
                        consumed = body_start + content_length
                else:
                    if self.is_request:
                        message_complete = True
                        consumed = body_start
                    else:
                        break  # Wait for socket to close

            if message_complete:
                messages.append((headers_str, body_data))
                self.buffer = self.buffer[consumed:]
            else:
                break
                
        return messages

    def flush(self):
        """Force extract remaining body if connection closed without Content-Length"""
        if b'\r\n\r\n' in self.buffer:
            headers_end = self.buffer.find(b'\r\n\r\n')
            headers_part = self.buffer[:headers_end]
            headers_str = headers_part.decode('ascii', errors='ignore')
            return [(headers_str, self.buffer[headers_end + 4:])]
        return []

class GFLProxy:
    def __init__(self, port: int, static_key: str, on_traffic_callback=None):
        self.port = port
        self.current_key = static_key
        self.on_traffic_callback = on_traffic_callback
        self.stop_event = threading.Event()
        self.server_thread = None

    def _trigger_callback(self, event_type, url, json_obj):
        if self.on_traffic_callback:
            try:
                self.on_traffic_callback(event_type, url, json_obj)
            except Exception:
                pass

    def _process_req_body(self, body, request_url):
        try:
            body_str = body.decode('ascii', errors='ignore')
            parsed_qs = urllib.parse.parse_qs(body_str)
            if 'outdatacode' in parsed_qs:
                encrypted_b64 = parsed_qs['outdatacode'][0]
                decrypted = gf_authcode(encrypted_b64, 'DECODE', self.current_key)
                if decrypted:
                    try:
                        json_data = json.loads(decrypted)
                        self._trigger_callback("C2S", request_url, json_data)
                    except Exception:
                        pass
        except Exception:
            pass

    def _process_res_body(self, body, request_url):
        try:
            match = re.search(b'#([A-Za-z0-9+/=]+)', body)
            if match:
                encrypted_b64 = match.group(1).decode('ascii')
                decrypted = gf_authcode(encrypted_b64, 'DECODE', self.current_key)
                if decrypted:
                    try:
                        json_data = json.loads(decrypted)
                        self._trigger_callback("S2C", request_url, json_data)
                        
                        # Dynamic Key Upgrade Mechanism
                        uid = json_data.get("uid")
                        sign = json_data.get("sign")
                        if uid and sign and str(sign) != self.current_key:
                            self.current_key = str(sign)
                            self._trigger_callback("SYS_KEY_UPGRADE", request_url, {"uid": uid, "sign": sign})
                    except Exception:
                        pass
        except Exception:
            pass

    def _relay_and_analyze(self, src_sock, dst_sock, initial_req_buffer=b"", is_https_tunnel=False):
        sockets = [src_sock, dst_sock]
        req_decoder = HttpStreamDecoder(is_request=True) if not is_https_tunnel else None
        res_decoder = HttpStreamDecoder(is_request=False) if not is_https_tunnel else None
        
        # FIFO queue to map responses to their respective request URLs
        url_queue = []

        def handle_requests(data):
            if not req_decoder: return
            req_decoder.push(data)
            for headers_str, body in req_decoder.get_messages():
                # Extract URL from the start-line
                lines = headers_str.split('\r\n')
                url = ""
                if lines and len(lines[0].split()) >= 2:
                    url = lines[0].split()[1]
                
                url_queue.append(url)
                
                # Only analyze if it targets the game API
                if url and "index.php" in url:
                    self._process_req_body(body, url)

        def handle_responses(data, is_flush=False):
            if not res_decoder: return
            
            msgs = []
            if not is_flush:
                res_decoder.push(data)
                msgs = res_decoder.get_messages()
            else:
                msgs = res_decoder.flush()
                
            for headers_str, body in msgs:
                # Match this response to the earliest pending request URL
                url = url_queue.pop(0) if url_queue else ""
                
                # Only analyze if the corresponding request was targeting the game API
                if url and "index.php" in url:
                    self._process_res_body(body, url)

        if initial_req_buffer:
            handle_requests(initial_req_buffer)
            
        try:
            while not self.stop_event.is_set():
                readable, _, _ = select.select(sockets, [], [], 1.0)
                if not readable:
                    continue
                    
                for sock in readable:
                    data = sock.recv(32768)
                    if not data:
                        # Socket closed: process remaining data
                        if sock is dst_sock:
                            handle_responses(b"", is_flush=True)
                        return 
                        
                    if sock is src_sock:
                        dst_sock.sendall(data)
                        handle_requests(data)
                    else:
                        src_sock.sendall(data)
                        handle_responses(data)
        except Exception:
            pass

    def _handle_client(self, client_socket):
        target_socket = None
        try:
            request_header = b""
            while b"\r\n\r\n" not in request_header:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                request_header += chunk
                
            if not request_header:
                return
                
            header_str = request_header.split(b"\r\n\r\n")[0].decode('ascii', errors='ignore')
            lines = header_str.split('\r\n')
            if not lines: return
            first_line = lines[0].split()
            if len(first_line) < 3: return
                
            method, url, _ = first_line
            host, port = "", 80
            
            for line in lines[1:]:
                if line.lower().startswith("host:"):
                    host_val = line.split(":", 1)[1].strip()
                    if ":" in host_val:
                        host, p = host_val.split(":", 1)
                        port = int(p)
                    else:
                        host = host_val
                        port = 443 if method == "CONNECT" else 80
                    break
                    
            if not host: return

            target_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            target_socket.connect((host, port))
            
            if method == "CONNECT":
                client_socket.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self._relay_and_analyze(client_socket, target_socket, initial_req_buffer=b"", is_https_tunnel=True)
            else:
                target_socket.sendall(request_header)
                self._relay_and_analyze(client_socket, target_socket, initial_req_buffer=request_header, is_https_tunnel=False)

        except Exception:
            pass
        finally:
            if client_socket:
                try: client_socket.close()
                except: pass
            if target_socket:
                try: target_socket.close()
                except: pass

    def _server_loop(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind(("127.0.0.1", self.port))
            server.listen(100)
            server.settimeout(1.0)
            
            while not self.stop_event.is_set():
                try:
                    client_sock, _ = server.accept()
                    t = threading.Thread(target=self._handle_client, args=(client_sock,))
                    t.daemon = True
                    t.start()
                except socket.timeout:
                    continue
        except Exception:
            pass
        finally:
            server.close()

    def start(self):
        self.stop_event.clear()
        self.server_thread = threading.Thread(target=self._server_loop)
        self.server_thread.daemon = True
        self.server_thread.start()

    def stop(self):
        self.stop_event.set()
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2.0)