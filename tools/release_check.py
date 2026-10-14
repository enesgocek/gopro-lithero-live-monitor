"""Audit only explicitly approved public source files; never print secret values."""
import argparse
import json
from pathlib import Path
import re
# fixed Git commands, argument lists, no shell.
import subprocess  # nosec B404
import sys

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'release-files.json'
PRIVATE={'backups','artifacts','captures','.venv','.audit-venv','.release-venv','.git','release','dist','__pycache__'}
FORBIDDEN={'.connection.json','.connection.tmp','cohn_db.json','RESTORATION.md','.env'}
SENSITIVE_SUFFIX={'.png','.jpg','.jpeg','.mp4','.mov','.log','.xml','.pem','.key','.p12','.pfx','.zip','.ipynb','.lnk'}

def inspect_text(text,path,known=()):
    findings=[]
    checks={
        'private key':r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        'access token':r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}|sk-[A-Za-z0-9]{20,})\b',
        'personal home path':r'(?i)[A-Z]:[\\/]Users[\\/][A-Za-z0-9_.-]+',
        'camera serial':r'\bC\d{10,}\b',
        'camera network identity':r'(?i)\bGoPro\s+\d{5,}\b',
    }
    for name,pattern in checks.items():
        if re.search(pattern,text):findings.append(name)
    for match in re.finditer(r'(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b',text):
        if match.group().lower() not in ('02:00:00:00:00:01','aa:bb:cc:dd:ee:ff'):findings.append('device address')
    for match in re.finditer(r'''(?i)["']?(?:password|token|secret|api_key)["']?\s*[:=]\s*["']([^"'\n]{8,})["']''',text):
        value=match.group(1)
        if path.startswith('tests/') and (value.startswith(('test-','unit-test-','synthetic-')) or value=='password'):continue
        findings.append('literal credential')
    if any(value and value in text for value in known):findings.append('local camera identity')
    return sorted(set(findings))

def git(*arguments):
    # fixed Git executable/arguments in developer-only tool; no shell.
    result=subprocess.run(['git',*arguments],cwd=ROOT,capture_output=True,check=True,timeout=30)  # nosec B603 B607
    return result.stdout

def valid_path(path):
    parts=Path(path).parts
    return bool(parts) and not Path(path).is_absolute() and '..' not in parts and not PRIVATE.intersection(parts) and Path(path).name not in FORBIDDEN and Path(path).suffix.lower() not in SENSITIVE_SUFFIX

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged',action='store_true')
    parser.add_argument('--history',action='store_true')
    args=parser.parse_args()
    allowed=json.loads(MANIFEST.read_text(encoding='utf8'))['files']
    known=[]
    try:
        local=json.loads((ROOT/'.connection.json').read_text(encoding='utf8'))
        known=[local.get(key,'') for key in ('device','device_name','ssid')]
    except (OSError,ValueError):pass
    problems=[]
    for name in allowed:
        file=ROOT/name
        if not valid_path(name) or file.is_symlink():problems.append(f'{name}: forbidden path');continue
        if not file.is_file():problems.append(f'{name}: missing file');continue
        try:text=file.read_text(encoding='utf8')
        except (UnicodeError,OSError):problems.append(f'{name}: unreadable/binary file');continue
        problems.extend(f'{name}: {reason}' for reason in inspect_text(text,name,known))
    if args.staged:
        entries=git('ls-files','--stage','-z').decode('utf8').split('\0')
        for entry in filter(None,entries):
            metadata,name=entry.split('\t',1)
            if name not in allowed or not valid_path(name) or metadata.startswith('120000'):
                problems.append(f'{name}: unapproved Git entry');continue
            text=git('show',f':{name}').decode('utf8')
            problems.extend(f'{name}: staged {reason}' for reason in inspect_text(text,name,known))
    if args.history:
        for entry in git('rev-list','--objects','--all').decode('utf8').splitlines():
            oid,separator,name=entry.partition(' ')
            if not separator or git('cat-file','-t',oid).strip()!=b'blob':continue
            if name not in allowed or not valid_path(name):problems.append(f'{name}: unapproved historical file');continue
            text=git('cat-file','-p',oid).decode('utf8')
            problems.extend(f'{name}: historical {reason}' for reason in inspect_text(text,name,known))
    if problems:
        print('Publication blocked:\n'+'\n'.join(problems),file=sys.stderr)
        return 1
    print(f'Publication check passed: {len(allowed)} approved source files; no matched secrets or camera identifiers.')
    return 0

if __name__=='__main__':sys.exit(main())
