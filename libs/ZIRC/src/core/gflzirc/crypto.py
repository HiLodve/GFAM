import hashlib
import base64
import time
import gzip

def md5(text: str) -> str:
    """Helper function for MD5 hashing"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def gf_authcode(string: str, operation: str = 'ENCODE', key: str = '', expiry: int = 3600) -> str:
    """
    100% Accurate GFL Custom AuthCode Algorithm.
    Handles GZIP decompression for DECODE operation.
    """
    key_hash = md5(key)
    keya = md5(key_hash[0:16])
    keyb = md5(key_hash[16:32])
    
    cryptkey = keyb + md5(keyb)
    key_length = len(cryptkey)
    
    if operation == 'DECODE':
        try:
            b64_str = string.strip()
            b64_str = b64_str + "=" * ((4 - len(b64_str) % 4) % 4)
            string_bytes = base64.b64decode(b64_str)
        except Exception:
            return ""
    else:
        expiry_time = (expiry + int(time.time())) if expiry > 0 else 0
        header = f"{expiry_time:010d}"
        checksum = md5(string + keya)[0:16]
        payload = header + checksum + string
        string_bytes = payload.encode('utf-8')

    string_length = len(string_bytes)
    result = bytearray()
    box = list(range(256))
    rndkey = [ord(cryptkey[i % key_length]) for i in range(256)]
    
    j = 0
    for i in range(256):
        j = (j + box[i] + rndkey[i]) % 256
        box[i], box[j] = box[j], box[i]
        
    a = j = 0
    for i in range(string_length):
        a = (a + 1) % 256
        j = (j + box[a]) % 256
        box[a], box[j] = box[j], box[a]
        result.append(string_bytes[i] ^ box[(box[a] + box[j]) % 256])
        
    if operation == 'DECODE':
        res_str = bytes(result)
        try:
            ext_bytes = res_str[26:]
            if ext_bytes.startswith(b'\x1f\x8b'):
                try:
                    ext_bytes = gzip.decompress(ext_bytes)
                except Exception:
                    pass
            ext_text = ext_bytes.decode('utf-8', errors='ignore').strip('\0')
            return ext_text
        except Exception:
            return ""
    else:
        return base64.b64encode(bytes(result)).decode('utf-8')