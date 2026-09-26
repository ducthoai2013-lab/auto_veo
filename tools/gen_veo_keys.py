"""Sinh cặp khóa Ed25519 THẬT cho Auto_veo3 (chạy một lần).

  python tools/gen_veo_keys.py D:\\secrets\\veo

Ghi 2 file:
  veo_private.pem  -> đặt trên VPS (biến VEO_JWT_PRIVATE_KEY_FILE hoặc VEO_JWT_PRIVATE_KEY). TUYỆT ĐỐI không đưa vào repo/chat.
  veo_public.pem   -> chép sang máy nhà cho Gateway (GW_JWT_PUBKEY_FILE). Không phải bí mật.
"""
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

if len(sys.argv) < 2:
    raise SystemExit(__doc__)
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
key = Ed25519PrivateKey.generate()
(out / "veo_private.pem").write_bytes(key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
(out / "veo_public.pem").write_bytes(key.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
print("Da ghi:", out / "veo_private.pem", "(BI MAT) va", out / "veo_public.pem")
