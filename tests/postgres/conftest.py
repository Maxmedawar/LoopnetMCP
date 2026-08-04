from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest


def _required_program(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        pytest.skip(f"native PostgreSQL program is unavailable: {name}")
    return path


def _unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


@dataclass
class DisposablePostgres:
    data_dir: Path
    socket_dir: Path
    port: int
    pg_ctl: str
    psql: str
    running: bool = True

    def dsn(self, database: str = "postgres", user: str = "postgres") -> str:
        return (
            f"host={self.socket_dir} port={self.port} "
            f"dbname={database} user={user}"
        )

    def sql(self, statement: str, *, database: str = "postgres") -> None:
        subprocess.run(
            [
                self.psql,
                "--no-psqlrc",
                "--set=ON_ERROR_STOP=1",
                "--dbname",
                self.dsn(database),
                "--command",
                statement,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def create_database(self, prefix: str = "phase2") -> tuple[str, str, str]:
        name = f"{prefix}_{uuid4().hex[:12]}"
        self.sql(f'CREATE DATABASE "{name}" OWNER medawarcre_migration')
        return (
            self.dsn(name, "postgres"),
            self.dsn(name, "medawarcre_test_migration"),
            self.dsn(name, "medawarcre_test_app"),
        )

    def create_admin_database(self, prefix: str = "phase2") -> str:
        name = f"{prefix}_{uuid4().hex[:12]}"
        self.sql(f'CREATE DATABASE "{name}" OWNER medawarcre_migration')
        return self.dsn(name, "postgres")

    def stop(self, mode: str = "fast") -> None:
        if not self.running:
            return
        subprocess.run(
            [self.pg_ctl, "-D", str(self.data_dir), "-m", mode, "-w", "stop"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.running = False

    def start(self) -> None:
        if self.running:
            return
        subprocess.run(
            [
                self.pg_ctl,
                "-D",
                str(self.data_dir),
                "-o",
                (
                    f"-F -k {self.socket_dir} -p {self.port} "
                    "-c listen_addresses=''"
                ),
                "-l",
                str(self.data_dir / "server.log"),
                "-w",
                "start",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.running = True


def _initialize_cluster(
    root: Path,
    *,
    include_test_logins: bool,
) -> DisposablePostgres:
    initdb = _required_program("initdb")
    pg_ctl = _required_program("pg_ctl")
    psql = _required_program("psql")
    data_dir = root / "data"
    socket_dir = Path(tempfile.mkdtemp(prefix="mcre-pg-sock-", dir="/tmp"))
    socket_dir.chmod(0o700)
    subprocess.run(
        [
            initdb,
            "-D",
            str(data_dir),
            "--auth=trust",
            "--username=postgres",
            "--encoding=UTF8",
            "--no-locale",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    cluster = DisposablePostgres(
        data_dir=data_dir,
        socket_dir=socket_dir,
        port=_unused_port(),
        pg_ctl=pg_ctl,
        psql=psql,
        running=False,
    )
    cluster.start()
    bootstrap = Path(__file__).parents[2] / "deploy" / "postgres" / "bootstrap_roles.sql"
    subprocess.run(
        [
            psql,
            "--no-psqlrc",
            "--set=ON_ERROR_STOP=1",
            "--dbname",
            cluster.dsn(),
            "--file",
            str(bootstrap),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    if include_test_logins:
        cluster.sql(
            "CREATE ROLE medawarcre_test_migration LOGIN NOINHERIT; "
            "GRANT medawarcre_migration TO medawarcre_test_migration "
            "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE; "
            "CREATE ROLE medawarcre_test_app LOGIN; "
            "GRANT medawarcre_app TO medawarcre_test_app "
            "WITH ADMIN FALSE, INHERIT TRUE, SET TRUE; "
            "CREATE ROLE medawarcre_test_admin LOGIN; "
            "GRANT medawarcre_admin TO medawarcre_test_admin "
            "WITH ADMIN FALSE, INHERIT TRUE, SET TRUE; "
            "CREATE ROLE medawarcre_test_backup LOGIN; "
            "GRANT medawarcre_backup TO medawarcre_test_backup "
            "WITH ADMIN FALSE, INHERIT TRUE, SET TRUE; "
            "CREATE ROLE medawarcre_test_admission LOGIN NOINHERIT; "
            "GRANT medawarcre_admission TO medawarcre_test_admission "
            "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE; "
            "CREATE ROLE medawarcre_test_oauth LOGIN NOINHERIT; "
            "GRANT medawarcre_oauth TO medawarcre_test_oauth "
            "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE; "
            "CREATE ROLE medawarcre_test_provider_ingress LOGIN NOINHERIT; "
            "GRANT medawarcre_provider_ingress TO medawarcre_test_provider_ingress "
            "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE; "
            "CREATE ROLE medawarcre_test_provider_reconcile LOGIN NOINHERIT; "
            "GRANT medawarcre_provider_reconcile TO medawarcre_test_provider_reconcile "
            "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE; "
            "CREATE ROLE medawarcre_test_worker LOGIN NOINHERIT; "
            "GRANT medawarcre_worker TO medawarcre_test_worker "
            "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE; "
            "CREATE ROLE medawarcre_test_scheduler LOGIN NOINHERIT; "
            "GRANT medawarcre_scheduler TO medawarcre_test_scheduler "
            "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;"
        )
    return cluster


@pytest.fixture(scope="session")
def postgres_cluster(tmp_path_factory: pytest.TempPathFactory) -> DisposablePostgres:
    root = tmp_path_factory.mktemp("medawarcre-postgres")
    cluster = _initialize_cluster(root, include_test_logins=True)
    try:
        yield cluster
    finally:
        cluster.stop("immediate")
        shutil.rmtree(cluster.socket_dir)


@pytest.fixture
def distinct_postgres_cluster(tmp_path: Path) -> Iterator[DisposablePostgres]:
    """A second server bootstrapped only from the committed role contract."""
    root = tmp_path / "distinct-postgres"
    root.mkdir()
    cluster = _initialize_cluster(root, include_test_logins=False)
    try:
        yield cluster
    finally:
        cluster.stop("immediate")
        shutil.rmtree(cluster.socket_dir)


@pytest.fixture
def postgres_database(postgres_cluster: DisposablePostgres) -> tuple[str, str, str]:
    return postgres_cluster.create_database()


@pytest.fixture(autouse=True)
def no_cloud_database_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DATABASE_URL",
        "MEDAWARCRE_DATABASE_URL",
        "PGPASSWORD",
        "PGSERVICE",
    ):
        monkeypatch.delenv(name, raising=False)
    os.environ.pop("PGPASSFILE", None)
