"""Set the panel password: writes PANEL_PASSWORD_HASH into .env (and a new PANEL_SECRET if it is empty).

    python3 tools/passwd.py                — asks for the password twice and updates .env
    python3 tools/passwd.py --new-secret   — the same and also a new PANEL_SECRET (logs everyone out)
    python3 tools/passwd.py --print        — only prints the two lines, .env is not touched

The password itself is not stored anywhere: .env keeps only its scrypt hash.
(python3 app.py --init does the same with a random password.)
Restart the panel afterwards: sudo systemctl restart hl-panel
"""
import getpass
import os
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from passwords import hash_password  # noqa: E402

ENV = Path(os.environ.get('PANEL_ENV') or ROOT / '.env')


def set_key(text, key, value):
    line = '%s=%s' % (key, value)
    pattern = re.compile(r'^%s=.*$' % re.escape(key), re.M)
    if pattern.search(text):
        return pattern.sub(lambda _m: line, text, count=1)
    return text.rstrip('\n') + '\n' + line + '\n'


def current(text, key):
    m = re.search(r'^%s=(.*)$' % re.escape(key), text, re.M)
    return re.sub(r'\s+#.*$', '', m.group(1)).strip() if m else ''


def main():
    while True:
        first = getpass.getpass('New panel password: ')
        if len(first) < 8:
            print('At least 8 characters, please.')
            continue
        if getpass.getpass('Repeat it: ') != first:
            print('The passwords differ, try again.')
            continue
        break
    pw_hash = hash_password(first)
    if '--print' in sys.argv[1:]:
        print('PANEL_PASSWORD_HASH=%s\nPANEL_SECRET=%s' % (pw_hash, secrets.token_hex(32)))
        return
    if not ENV.exists():
        sys.exit('%s not found: copy .env.example to .env first.' % ENV)
    text = ENV.read_text(encoding='utf-8')
    text = set_key(text, 'PANEL_PASSWORD_HASH', pw_hash)
    if '--new-secret' in sys.argv[1:] or not current(text, 'PANEL_SECRET'):
        text = set_key(text, 'PANEL_SECRET', secrets.token_hex(32))
    ENV.write_text(text, encoding='utf-8')
    os.chmod(ENV, 0o600)
    print('Saved to %s. Restart the panel: sudo systemctl restart hl-panel' % ENV)


if __name__ == '__main__':
    main()
