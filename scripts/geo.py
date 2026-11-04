"""Local convenience entry; no network, no package installation, no MCP global edits."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def config_path() -> Path:
    custom = os.environ.get('GEO_ADVISOR_CONFIG')
    if custom:
        return Path(custom).expanduser().resolve()
    base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local' / 'share')))
    return base / 'OverseasGeoAdvisor' / 'config.json'


def emit(obj: dict, code: int = 0) -> int:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    return code


def load_config(path: Path) -> dict:
    if os.environ.get('GEO_KB_DB'):
        return {'db': str(Path(os.environ['GEO_KB_DB']).expanduser().resolve())}
    if not path.is_file():
        raise ValueError('尚未连接本地知识库。先运行 setup，或设置 GEO_KB_DB。')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('db'), str):
        raise ValueError('配置缺少有效 db 路径。')
    return data


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cfg_path = config_path()
    if len(argv) >= 2 and argv[0] == '--config':
        cfg_path = Path(argv[1]).expanduser().resolve()
        argv = argv[2:]
    if not argv:
        return emit({'status': 'needs_configuration', 'commands': ['setup', 'status', 'ask', 'search', 'read', 'review', 'browse', 'check', 'mcp-config'], 'help': 'setup --help; other commands pass through to geo_kb.py'}, 2)
    command, extra = argv[0], argv[1:]
    scripts = Path(__file__).resolve().parent
    if command == 'setup':
        parser = argparse.ArgumentParser(description='Connect authorized local Markdown; source folder is read-only.')
        parser.add_argument('--vault', required=True)
        parser.add_argument('--manifest')
        parser.add_argument('--data-dir')
        parser.add_argument('--replace-config', action='store_true')
        args = parser.parse_args(extra)
        vault = Path(args.vault).expanduser().resolve()
        if not vault.is_dir():
            return emit({'status': 'unavailable', 'error': '资料目录不存在'}, 2)
        runtime = Path(args.data_dir).expanduser().resolve() if args.data_dir else cfg_path.parent / 'data'
        proposed = {'schema_version': 1, 'vault': str(vault), 'db': str(runtime / 'knowledge.sqlite3'), 'manifest': str(Path(args.manifest).expanduser().resolve()) if args.manifest else None}
        if cfg_path.exists() and not args.replace_config:
            old = json.loads(cfg_path.read_text(encoding='utf-8'))
            if any(old.get(k) != proposed.get(k) for k in ('vault', 'db', 'manifest')):
                return emit({'status': 'needs_configuration', 'error': '已有不同配置；请使用独立 --config 路径，或明确指定 --replace-config。'}, 2)
        runtime.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, '-B', '-X', 'utf8', str(scripts / 'geo_kb.py'), '--db', proposed['db'], 'build', '--vault', str(vault)]
        if proposed['manifest']:
            cmd += ['--manifest', proposed['manifest']]
        completed = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        if completed.returncode:
            sys.stdout.write(completed.stdout)
            sys.stderr.write(completed.stderr)
            return completed.returncode
        try:
            report = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return emit({'status': 'unavailable', 'error': '索引命令没有返回有效JSON，配置尚未保存。'}, 2)
        if report.get('status') in ('error', 'unavailable'):
            return emit(report, 2)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cfg_path.with_suffix('.pending')
        temporary.write_text(json.dumps(proposed, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(cfg_path)
        return emit({'status': 'configured', 'config_path': str(cfg_path), 'db': proposed['db'], 'build': report})
    try:
        config = load_config(cfg_path)
    except (ValueError, OSError) as exc:
        return emit({'status': 'unavailable', 'error': str(exc)}, 2)
    if command == 'mcp-config':
        cmd = [sys.executable, '-B', '-X', 'utf8', str(scripts / 'geo_mcp.py'), '--db', config['db'], '--print-config']
    else:
        target = 'browse' if command == 'status' else command
        if target not in {'build', 'ask', 'search', 'read', 'review', 'browse', 'check'}:
            return emit({'status': 'error', 'error': '未知命令'}, 2)
        cmd = [sys.executable, '-B', '-X', 'utf8', str(scripts / 'geo_kb.py'), '--db', config['db'], target, *extra]
    return subprocess.run(cmd).returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        raise SystemExit(emit({'status': 'unavailable', 'error': str(exc)}, 2))
