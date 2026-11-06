"""Creates gym-qr.png. Usage:  python scripts/make_qr.py https://your-app.onrender.com
Reads GYM_QR_KEY from .env so the QR opens  <site>/checkin?k=<key>"""
import os, sys
from dotenv import load_dotenv
import qrcode

load_dotenv()
if len(sys.argv) < 2 or not os.environ.get("GYM_QR_KEY"):
    sys.exit("Usage: python scripts/make_qr.py https://your-site.com   (and set GYM_QR_KEY in .env)")
url = f"{sys.argv[1].rstrip('/')}/checkin?k={os.environ['GYM_QR_KEY']}"
qrcode.make(url, box_size=14, border=3).save("gym-qr.png")
print("Saved gym-qr.png ->", url)
