"""Embed the fixed local Toolkit logo once, keeping the trusted UI self-contained."""
from pathlib import Path
import base64
import re

ROOT = Path(__file__).resolve().parents[1]
logo = (ROOT / 'assets/toolkit-logo.png').read_bytes()
if not logo.startswith(b'\x89PNG\r\n\x1a\n'):
    raise ValueError('assets/toolkit-logo.png must be a PNG')
page = ROOT / 'ui.html'
text = page.read_text(encoding='utf-8')
uri = 'data:image/png;base64,' + base64.b64encode(logo).decode('ascii')
updated, count = re.subn(r'--ns-toolkit-image:url\("[^"\r\n]*"\)',
                         '--ns-toolkit-image:url("' + uri + '")', text)
if count != 1:
    raise ValueError('Expected one Toolkit logo CSS binding')
page.write_text(updated, encoding='utf-8', newline='\r\n')
print('Embedded one local Toolkit PNG; HTTP/CSP policy unchanged.')
