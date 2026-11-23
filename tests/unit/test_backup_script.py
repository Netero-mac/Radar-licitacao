"""scripts/backup.sh com um "docker" falso no PATH (não precisa de Docker nem de banco)."""

import os
import re
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "backup.sh"

FAKE_DOCKER = """#!/bin/sh
echo "$@" > "$FAKE_DOCKER_ARGS"
case "$FAKE_DOCKER_MODE" in
  ok) printf 'PGDMP conteudo do dump' ;;
  empty) ;;
  fail) echo "service db is not running" >&2; exit 1 ;;
esac
"""


def _run(tmp_path: Path, mode: str, **env: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    return subprocess.run(
        ["sh", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "BACKUP_DIR": str(tmp_path / "backups"),
            "FAKE_DOCKER_MODE": mode,
            "FAKE_DOCKER_ARGS": str(tmp_path / "args.txt"),
            **env,
        },
    )


def test_gera_arquivo_com_data_no_nome(tmp_path: Path) -> None:
    result = _run(tmp_path, "ok")

    assert result.returncode == 0, result.stderr
    [dump] = (tmp_path / "backups").iterdir()
    assert re.fullmatch(r"radar_\d{4}-\d{2}-\d{2}_\d{6}\.dump", dump.name)
    assert dump.read_text() == "PGDMP conteudo do dump"
    args = (tmp_path / "args.txt").read_text()
    assert "compose -f docker-compose.prod.yml exec -T db" in args
    assert "pg_dump" in args and "--format=custom" in args


@pytest.mark.parametrize(("mode", "message"), [("fail", "pg_dump falhou"), ("empty", "vazio")])
def test_falha_nao_deixa_backup_pela_metade(tmp_path: Path, mode: str, message: str) -> None:
    result = _run(tmp_path, mode)

    assert result.returncode == 1
    assert message in result.stderr
    assert list((tmp_path / "backups").iterdir()) == []


def test_apaga_backups_antigos(tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    old = backups / "radar_2026-10-01_030000.dump"
    recent = backups / "radar_2026-11-20_030000.dump"
    other = backups / "outro-arquivo.dump"
    for path in (old, recent, other):
        path.write_text("x")
    month_ago = time.time() - 30 * 86_400
    os.utime(old, (month_ago, month_ago))
    os.utime(other, (month_ago, month_ago))

    result = _run(tmp_path, "ok", BACKUP_KEEP_DAYS="14")

    assert result.returncode == 0, result.stderr
    assert not old.exists()
    assert recent.exists()
    assert other.exists()  # só mexe nos arquivos do próprio backup
    assert "Removido (antigo)" in result.stdout
