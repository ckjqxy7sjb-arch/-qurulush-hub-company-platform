#!/usr/bin/env python3
"""Render concrete systemd, nginx, and acceptance files for a VPS deployment."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PLACEHOLDER_DOMAINS = {"company.example", "example.com", "localhost"}


def validate_domain(domain: str) -> str:
    value = domain.strip().lower()
    if value in PLACEHOLDER_DOMAINS or value.endswith(".example") or "://" in value:
        raise ValueError("domain must be a real DNS name without scheme")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+", value):
        raise ValueError("domain must be a valid DNS name")
    return value


def render_service(
    *,
    app_root: Path,
    runtime_root: Path,
    env_file: Path,
    service_user: str,
    service_group: str,
    python: str,
    host: str,
    port: int,
    cert: Path,
    key: Path,
) -> str:
    db = runtime_root / "company.sqlite3"
    uploads = runtime_root / "uploads"
    backups = runtime_root / "backups"
    return f"""[Unit]
Description=Qurulush Hub company platform
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={service_user}
Group={service_group}
WorkingDirectory={app_root}
EnvironmentFile={env_file}
ExecStartPre={python} {app_root}/company_platform_server.py --preflight --require-production --db {db} --uploads {uploads} --backups {backups} --tls-cert {cert} --tls-key {key}
ExecStart={python} {app_root}/company_platform_server.py --host {host} --port {port} --db {db} --uploads {uploads} --backups {backups} --tls-cert {cert} --tls-key {key} --require-production
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths={runtime_root}

[Install]
WantedBy=multi-user.target
"""


def render_nginx(*, domain: str, host: str, port: int, cert: Path, key: Path, client_max_body_size: str) -> str:
    return f"""server {{
    listen 80;
    server_name {domain};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl http2;
    server_name {domain};

    ssl_certificate {cert};
    ssl_certificate_key {key};

    client_max_body_size {client_max_body_size};

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    location / {{
        proxy_pass https://{host}:{port};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 60s;
    }}
}}
"""


def render_go_no_go_command(*, app_root: Path, runtime_root: Path, env_file: Path, domain: str, email: str) -> str:
    release = app_root / "dist/qurulush-hub-company-platform-current.zip"
    return f"""#!/bin/sh
set -eu
cd {app_root}
python3 ops/go_no_go_check.py \\
  --release {release} \\
  --deployment-root {app_root} \\
  --env {env_file} \\
  --base-url https://{domain}/ \\
  --email {email} \\
  --password "$QH_GO_NO_GO_PASSWORD" \\
  --backups {runtime_root}/backups \\
  --require-production-config \\
  --hook-contract-smoke \\
  --require-production
"""


def render_deployment_files(
    *,
    domain: str,
    output_dir: Path,
    app_root: Path,
    runtime_root: Path,
    env_file: Path,
    admin_email: str,
    service_user: str = "qurulush",
    service_group: str = "qurulush",
    python: str = "/usr/bin/python3",
    host: str = "127.0.0.1",
    port: int = 8781,
    cert_dir: Path | None = None,
    client_max_body_size: str = "12m",
) -> dict[str, Any]:
    domain = validate_domain(domain)
    cert_dir = cert_dir or Path("/etc/letsencrypt/live") / domain
    cert = cert_dir / "fullchain.pem"
    key = cert_dir / "privkey.pem"
    output_dir.mkdir(parents=True, exist_ok=True)

    service = output_dir / "qurulush-hub.service"
    nginx = output_dir / "nginx-qurulush-hub.conf"
    go_no_go = output_dir / "go-no-go-command.sh"
    summary = output_dir / "DEPLOYMENT_SUMMARY.json"

    service.write_text(
        render_service(
            app_root=app_root,
            runtime_root=runtime_root,
            env_file=env_file,
            service_user=service_user,
            service_group=service_group,
            python=python,
            host=host,
            port=port,
            cert=cert,
            key=key,
        ),
        encoding="utf-8",
    )
    nginx.write_text(render_nginx(domain=domain, host=host, port=port, cert=cert, key=key, client_max_body_size=client_max_body_size), encoding="utf-8")
    go_no_go.write_text(render_go_no_go_command(app_root=app_root, runtime_root=runtime_root, env_file=env_file, domain=domain, email=admin_email), encoding="utf-8")
    go_no_go.chmod(0o700)

    result = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "domain": domain,
        "files": {
            "systemd": str(service),
            "nginx": str(nginx),
            "go_no_go": str(go_no_go),
            "summary": str(summary),
        },
        "install_targets": {
            "systemd": "/etc/systemd/system/qurulush-hub.service",
            "nginx": "/etc/nginx/sites-available/qurulush-hub.conf",
            "env": str(env_file),
            "runtime_root": str(runtime_root),
        },
        "checks": ["domain validated", "systemd rendered", "nginx rendered", "go-no-go rendered"],
    }
    summary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render Qurulush Hub VPS deployment files")
    parser.add_argument("--domain", required=True, help="Real public DNS name, for example cabinet.builder.kg")
    parser.add_argument("--output-dir", type=Path, default=Path("dist/deployment-files"))
    parser.add_argument("--app-root", type=Path, default=Path("/opt/qurulush-hub"))
    parser.add_argument("--runtime-root", type=Path, default=Path("/var/lib/qurulush-hub"))
    parser.add_argument("--env-file", type=Path, default=Path("/etc/qurulush-hub/company-platform.env"))
    parser.add_argument("--admin-email", default="owner@builder.kg")
    parser.add_argument("--service-user", default="qurulush")
    parser.add_argument("--service-group", default="qurulush")
    parser.add_argument("--python", default="/usr/bin/python3")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8781)
    parser.add_argument("--cert-dir", type=Path, default=None)
    parser.add_argument("--client-max-body-size", default="12m")
    args = parser.parse_args(argv)

    result = render_deployment_files(
        domain=args.domain,
        output_dir=args.output_dir,
        app_root=args.app_root,
        runtime_root=args.runtime_root,
        env_file=args.env_file,
        admin_email=args.admin_email,
        service_user=args.service_user,
        service_group=args.service_group,
        python=args.python,
        host=args.host,
        port=args.port,
        cert_dir=args.cert_dir,
        client_max_body_size=args.client_max_body_size,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
