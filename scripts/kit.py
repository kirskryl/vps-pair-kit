#!/usr/bin/env python3
"""Local-only configuration helper. Never source .env or print its values."""
import argparse
import base64
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {'HOME_IP', 'EGRESS_IP', 'HOME_ADMIN', 'EGRESS_ADMIN', 'HOME_SSH_KEY', 'EGRESS_SSH_KEY', 'HOME_SSH_PORT', 'EGRESS_SSH_PORT', 'SS_PORT', 'PROXY_PORT', 'SS2022_KEY'}

class Invalid(Exception):
    pass

def private_file(path):
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
        raise Invalid('private file permissions required')

def write_private(path, value):
    # Exclusive create prevents symlink following and accidental overwrite.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        out.write(value)

def init(root, open_editor=False):
    path = root / '.env'
    content = (root / '.env.example').read_text().replace('SS2022_KEY=', 'SS2022_KEY=' + base64.b64encode(secrets.token_bytes(32)).decode(), 1)
    if not path.exists():
        write_private(path, content)
    private_file(path)
    if open_editor:
        editor = os.environ.get('VISUAL') or os.environ.get('EDITOR')
        argv = shlex.split(editor) if editor else (['open', '-W', '-t'] if sys.platform == 'darwin' else ['vi'])
        subprocess.run(argv + [str(path)], check=True, shell=False)
        private_file(path)

def validate(root):
    path = root / '.env'
    private_file(path)
    data = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        k, sep, v = line.partition('=')
        if not sep or k not in FIELDS or k in data:
            raise Invalid('invalid or duplicate field')
        data[k] = v
    errors = sorted(FIELDS - data.keys())
    for key in sorted(FIELDS & data.keys()):
        value = data[key]
        try:
            if not value or any(c in value for c in '\x00\r\n'):
                raise ValueError()
            if key.endswith('_IP'):
                addr = ipaddress.ip_address(value)
                if addr.version != 4 or addr.is_unspecified or addr.is_loopback or addr.is_multicast:
                    raise ValueError()
            elif key.endswith('_ADMIN'):
                if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', value) or value == 'root':
                    raise ValueError()
            elif key.endswith('_PORT'):
                if not re.fullmatch(r'[0-9]+', value) or not (1 if key.endswith('_SSH_PORT') else 1024) <= int(value) <= 65535:
                    raise ValueError()
            elif key.endswith('_SSH_KEY'):
                p = Path(value)
                if not p.is_absolute() or any(c in value for c in '\"\t'):
                    raise ValueError()
                private_file(p)
            elif key == 'SS2022_KEY':
                raw = base64.b64decode(value, validate=True)
                if len(raw) != 32 or base64.b64encode(raw).decode() != value:
                    raise ValueError()
        except (ValueError, OSError, Invalid):
            errors.append(key)
    if data.get('HOME_SSH_KEY') == data.get('EGRESS_SSH_KEY'):
        errors.extend(['HOME_SSH_KEY', 'EGRESS_SSH_KEY'])
    if data.get('HOME_IP') == data.get('EGRESS_IP'):
        errors.extend(['HOME_IP', 'EGRESS_IP'])
    if errors:
        raise Invalid('check fields: ' + ', '.join(sorted(set(errors))))
    return data

def policy(home, egress):
    try:
        inbound = home['inbounds'][0]
        outbound = home['outbounds'][0]
        server = egress['inbounds'][0]
        if (len(home['inbounds']) != 1 or inbound['type'] != 'mixed'
            or inbound['listen'] != '127.0.0.1'
            or len(home['outbounds']) != 1 or outbound['type'] != 'shadowsocks'
            or home['route'] != {'final': 'egress-ss'}
            or outbound['tag'] != 'egress-ss'
            or outbound['method'] != '2022-blake3-aes-256-gcm'
            or outbound['network'] != 'tcp'
            or len(egress['inbounds']) != 1 or server['type'] != 'shadowsocks'
            or server['method'] != outbound['method'] or server['network'] != 'tcp'
            or server['password'] != outbound['password']
            or server['listen_port'] != outbound['server_port']
            or server['listen'] != outbound['server']
            or egress['outbounds'] != [{'type': 'direct', 'tag': 'internet'}]
            or egress['route'] != {'final': 'internet'}):
            raise Invalid('baseline policy failed')
    except (KeyError, IndexError, TypeError):
        raise Invalid('baseline policy failed')

def render(root):
    d = validate(root)
    template_dir = root / 'vps-pair/templates'
    values = {**d, 'SS_PORT': int(d['SS_PORT']), 'PROXY_PORT': int(d['PROXY_PORT'])}
    configs = []
    for name in ('home', 'egress'):
        text = (template_dir / (name + '.sing-box.json.template')).read_text()
        for k, v in values.items():
            text = text.replace('"__' + k + '__"', json.dumps(v))
        obj = json.loads(text)
        if '__' in text:
            raise Invalid('unresolved template')
        configs.append(obj)
    policy(*configs)
    # A new directory per render; no partial replacement of a known-good generation.
    import tempfile
    parent = root / '.rendered'
    if not parent.exists():
        parent.mkdir(mode=0o700)
    st = parent.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
        raise Invalid('private output directory required')
    out = Path(tempfile.mkdtemp(prefix='generation-', dir=parent))
    for name, cfg in zip(('home', 'egress'), configs):
        write_private(out / (name + '.json'), json.dumps(cfg, indent=2) + '\n')
    proxy = f"http://127.0.0.1:{d['PROXY_PORT']}"
    write_private(out / 'proxy.env', '\n'.join(k + '=' + proxy for k in ('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy')) + '\nNO_PROXY=localhost,127.0.0.1,::1\nno_proxy=localhost,127.0.0.1,::1\n')
    ssh = ''
    for role in ('HOME', 'EGRESS'):
        ssh += f"Host pair-{role.lower()}\n    HostName {d[role+'_IP']}\n    User {d[role+'_ADMIN']}\n    Port {d[role+'_SSH_PORT']}\n    IdentityFile \"{d[role+'_SSH_KEY']}\"\n    IdentitiesOnly yes\n    StrictHostKeyChecking yes\n    ForwardAgent no\n\n"
    write_private(out / 'ssh-config', ssh)
    return out

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init','check','validate','render'])
    parser.add_argument('--open', action='store_true', help='explicitly open local editor (init only)')
    args = parser.parse_args()
    try:
        if args.open and args.command != 'init':
            raise Invalid('--open is init only')
        if args.command == 'init':
            init(ROOT, args.open)
            print('Local .env ready; fill fields in your local editor. Values are never displayed.')
        elif args.command in ('check','validate'):
            validate(ROOT)
            print('Validation passed.')
        else:
            out = render(ROOT)
            print('Rendered private generation: ' + str(out.relative_to(ROOT)))
    except (Invalid, OSError, ValueError, subprocess.SubprocessError) as error:
        # Never propagate parser/file/editor errors, which may contain secret values.
        print(str(error) if isinstance(error, Invalid) else 'Local operation failed; check file permissions and field names.', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
