#!/usr/bin/env python3
"""Publish completed skill edits from this checkout to origin/main.

Designed for a scheduled local Codex run. It never touches VPS hosts. Unrelated
repository changes, recent edits, failed checks, or a remote branch change stop
publication without rewriting history.
"""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
QUIET_SECONDS = 600
SKILL_FILES = {'SKILL.md', 'README.md', 'VPS_PAIR_AGENT_GUIDE.md'}
SECRET_PATTERNS = (
    re.compile(r'-----BEGIN (?:OPENSSH|RSA|EC|DSA) PRIVATE KEY-----'),
    re.compile(r'\b\d{8,12}:[A-Za-z0-9_-]{30,}\b'),
    re.compile(r'\bsk-[A-Za-z0-9_-]{20,}\b'),
    re.compile(r'(?i)\b(?:TELEGRAM_BOT_TOKEN|OPENAI_API_KEY|SS2022_KEY)\s*[:=]\s*[^\s#<>]{12,}'),
)


def git(*args, check=True):
    return subprocess.run(['git', *args], cwd=ROOT, check=check, capture_output=True, text=True)


def skill_path(path):
    return path in SKILL_FILES or (path.startswith('references/') and path.endswith('.md'))


def changed_paths():
    result = subprocess.run(
        ['git', 'status', '--porcelain=v1', '-z', '--untracked-files=all'],
        cwd=ROOT, check=True, capture_output=True,
    )
    paths = []
    parts = iter(result.stdout.split(b'\0'))
    for part in parts:
        if not part:
            break
        status = part[:2].decode('ascii')
        path = os.fsdecode(part[3:])
        if 'R' in status or 'C' in status:
            next(parts, None)
        paths.append((status, path))
    return paths


def validate_files(paths):
    for path in paths:
        file = ROOT / path
        if not file.is_file() or file.is_symlink():
            raise ValueError(f'Необычный тип файла: {path}')
        text = file.read_text(encoding='utf-8')
        for number, line in enumerate(text.splitlines(), 1):
            if any(pattern.search(line) for pattern in SECRET_PATTERNS):
                raise ValueError(f'Возможный секрет: {path}:{number}')
        for target in re.findall(r'\]\(([^)]+)\)', text):
            if target.startswith(('https://', 'http://', 'mailto:', '#')):
                continue
            if not (file.parent / target).exists():
                raise ValueError(f'Не найдена ссылка: {path} → {target}')
    skill = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
    if not skill.startswith('---\n') or '\nname: vps-pair-kit\n' not in skill or '\ndescription:' not in skill:
        raise ValueError('Неверные метаданные SKILL.md')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--commit-only', action='store_true', help='commit eligible edits for connector publishing')
    action.add_argument('--publish', action='store_true', help='commit and push with local git credentials')
    args = parser.parse_args()
    if Path(git('rev-parse', '--show-toplevel').stdout.strip()) != ROOT:
        raise ValueError('Ожидался checkout vps-pair-kit')
    if git('branch', '--show-current').stdout.strip() != 'main':
        raise ValueError('Автопубликация разрешена только из main')
    changes = changed_paths()
    unexpected = [path for _, path in changes if not skill_path(path)]
    if unexpected:
        raise ValueError('Есть изменения вне скилла: ' + ', '.join(unexpected))
    if any(status[0] != ' ' and status[0] != '?' for status, _ in changes):
        raise ValueError('В индексе Git уже есть изменения; автоматическая публикация остановлена')
    paths = [path for _, path in changes]
    if paths:
        newest = max((ROOT / path).stat().st_mtime for path in paths)
        if time.time() - newest < QUIET_SECONDS:
            print('Правки ещё идут; повторим позже.')
            return 0
        validate_files(paths)
        subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q'], cwd=ROOT, check=True)
        git('diff', '--check')
    if not (args.publish or args.commit_only):
        print(f'Проверено файлов скилла: {len(paths)}. Публикация отключена.')
        return 0
    git('fetch', 'origin', 'main')
    if git('merge-base', '--is-ancestor', 'origin/main', 'HEAD', check=False).returncode != 0:
        raise ValueError('GitHub содержит новые коммиты; требуется ручное объединение')
    if paths:
        git('add', '--', *paths)
        git('diff', '--cached', '--check')
        git('commit', '-m', 'Update VPS Pair Kit skill')
    if args.commit_only:
        print('Локальный коммит готов к отправке через GitHub connector.')
        return 0
    if git('rev-list', '--count', 'origin/main..HEAD').stdout.strip() != '0':
        git('push', 'origin', 'main')
        print('Изменения скилла опубликованы в GitHub.')
    else:
        print('Новых изменений для GitHub нет.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            print(f'Автопубликация остановлена: команда {exc.cmd[0]} завершилась с ошибкой.', file=sys.stderr)
        else:
            print(f'Автопубликация остановлена: {exc}', file=sys.stderr)
        sys.exit(1)
