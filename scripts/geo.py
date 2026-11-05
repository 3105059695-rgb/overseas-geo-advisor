"""GEO entry: query the public GitHub snapshot unless local or legacy MCP is explicit."""
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
    explicit_local = False
    remote = False
    while argv and argv[0] in {'--config', '--remote', '--local'}:
        if argv[0] == '--config':
            if len(argv) < 2:
                return emit({'status': 'error', 'error': '--config 缺少配置文件路径'}, 2)
            cfg_path = Path(argv[1]).expanduser().resolve()
            explicit_local = True
            argv = argv[2:]
        else:
            remote = remote or argv[0] == '--remote'
            explicit_local = explicit_local or argv[0] == '--local'
            argv = argv[1:]
    if remote and explicit_local:
        return emit({'status': 'error', 'error': '--remote 不能与 --local 或 --config 同时使用'}, 2)
    if not argv:
        mode = 'local' if explicit_local else 'legacy_mcp' if remote else 'github_snapshot'
        return emit({'status': 'ready', 'default': mode,
                     'commands': ['status', 'ask', 'search', 'read', 'browse', 'check', 'workflow'],
                     'help': 'ask --question "海外信源怎么分？"；默认直接读取公开 GitHub 快照，无需账号、导入资料或本地库。维护本地资料使用 --local 或 --config；--remote 兼容旧 MCP。'})
    command, extra = argv[0], argv[1:]
    scripts = Path(__file__).resolve().parent
    if command == 'workflow':
        from geo_workflow import main as workflow_main
        return workflow_main(extra)
    if command == 'remote-config':
        if extra:
            return emit({'status': 'error', 'error': 'remote-config 不接受其他参数；替换地址可设置 GEO_MCP_URL。'}, 2)
        from geo_remote import remote_config
        return emit(remote_config())
    if not explicit_local:
        from geo_remote import DEFAULT_URL, main as remote_main
        if command in {'setup', 'build', 'review'}:
            return emit({'status': 'error', 'error': '公开快照只读；本地资料管理请显式使用 --local 或 --config。'}, 2)
        if remote:
            return remote_main(['--transport', 'mcp', command, *extra])
        # Select the author's snapshot explicitly. Existing local configs and a
        # stale/custom GEO_MCP_URL must not redirect or block ordinary users.
        return remote_main(['--transport', 'github', '--url', DEFAULT_URL, command, *extra])
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
