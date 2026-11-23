"""PostgreSQL の実際のスキーマ (モジュール schema_actual の後半) のテスト。

Docker でコンテナ (イメージ postgres:17-alpine) を起動するので、Docker が要る。Docker が使えなければ、テストはスキップせずに
失敗する (検査されていないことに気づけるように)。Docker が無いときの動き (終了コード 3) は、失敗するだけの偽のコマンド docker を
作り、そのディレクトリを環境変数 PATH の先頭に加えて確認する。決めた経緯は Issue #207 のコメントの 2・3・5・11・14。
"""

import os
import stat
import subprocess
import unittest

from doc_structured.config import DatabaseConfig
from doc_structured.impl_diff import ImplementationUnavailable
from doc_structured.schema_actual import CONTAINER_PREFIX, MigrationError, read_schema
from tooltest import CONFIG_RELATIVE_PATH, PYTHON, ProjectTestCase, clean_env

IMAGE = "postgres:17-alpine"

# サンプルのプロジェクトの設計と同じスキーマを作る、PostgreSQL のマイグレーション。型の別名・型変換が付くデフォルト値・
# 部分インデックスの条件・CHECK 制約が、比べ方で吸収されることも確認する
SAMPLE_MIGRATION = """\
CREATE TABLE books (
  id TEXT PRIMARY KEY,
  title text NOT NULL,
  shelf_status text NOT NULL DEFAULT 'shelved',
  call_number text NOT NULL,
  created_at int4 NOT NULL,
  CHECK (shelf_status IN ('shelved', 'on_loan'))
);
CREATE TABLE categories (id text PRIMARY KEY, name text NOT NULL UNIQUE);
CREATE TABLE book_categories (
  book_id text NOT NULL REFERENCES books (id),
  category_id text NOT NULL REFERENCES categories,
  PRIMARY KEY (book_id, category_id)
);
CREATE INDEX book_categories_category_idx ON book_categories (category_id);
CREATE TABLE members (id text PRIMARY KEY, name text NOT NULL);
CREATE TABLE reservations (
  id text PRIMARY KEY,
  book_id text NOT NULL REFERENCES books (id),
  previous_id text REFERENCES reservations (id),
  status text NOT NULL DEFAULT 'waiting'
);
CREATE TABLE loans (
  id text PRIMARY KEY,
  book_id text NOT NULL REFERENCES books (id),
  member_id text NOT NULL REFERENCES members (id),
  reservation_id text REFERENCES reservations (id),
  status text NOT NULL DEFAULT 'on_loan'
);
CREATE INDEX loans_member_idx ON loans (member_id);
CREATE UNIQUE INDEX loans_reservation_unique ON loans (reservation_id) WHERE reservation_id IS NOT NULL;
"""

POSTGRESQL_CONFIG = f"""\
# 図書館の貸出 (架空の題材) の、doc-structured の設定 (PostgreSQL)
version: 0.2.0
paths:
  migrations: db/*.up.sql
database:
  kind: postgresql
  image: {IMAGE}
"""


def postgresql_config(pattern: str = "db/*.up.sql") -> DatabaseConfig:
    return DatabaseConfig(kind="postgresql", image=IMAGE, schema_actual=False, migrations=pattern, migrations_at=(4, 15))


def leftover_containers() -> list[str]:
    result = subprocess.run(
        ["docker", "ps", "--all", "--filter", f"name={CONTAINER_PREFIX}", "--format", "{{.Names}}"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.split()


class PostgresqlTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.before = set(leftover_containers())

    def tearDown(self):
        # どのテストでも、起動したコンテナは残らない
        self.assertEqual(set(leftover_containers()) - self.before, set())
        super().tearDown()

    def test_read_columns_keys_indexes_and_checks(self):
        self.write("db/0001_init.up.sql", """
            CREATE TABLE stores (id serial PRIMARY KEY, code varchar(20) NOT NULL UNIQUE);
            CREATE TABLE visits (
              id bigserial PRIMARY KEY,
              store_id integer NOT NULL REFERENCES stores (id) ON DELETE CASCADE,
              status text NOT NULL DEFAULT 'open',
              email text,
              opened_at timestamptz NOT NULL DEFAULT now(),
              CONSTRAINT visits_status_check CHECK (status IN ('open', 'closed'))
            );
            CREATE UNIQUE INDEX visits_open ON visits (store_id) WHERE status = 'open';
            CREATE INDEX visits_email_lower ON visits (lower(email));
            CREATE TABLE store_visits (store_id integer, visit_id bigint, PRIMARY KEY (visit_id, store_id),
              FOREIGN KEY (store_id) REFERENCES stores (id));
            CREATE VIEW open_visits AS SELECT * FROM visits WHERE status = 'open';
        """)
        self.write("db/0001_init.down.sql", "DROP TABLE visits;")
        schema = read_schema(self.project, postgresql_config())
        self.assertEqual(schema.kind, "postgresql")
        # ビューは読まない
        self.assertEqual(list(schema.tables), ["store_visits", "stores", "visits"])
        stores = schema.tables["stores"]
        self.assertEqual(stores.primary_key, ["id"])
        store_id = stores.column("id")
        self.assertEqual((store_id.type, store_id.not_null, store_id.owned_sequence), ("integer", True, True))
        self.assertEqual(stores.column("code").type, "character varying(20)")
        self.assertEqual([(i.columns, i.unique) for i in stores.indexes], [(["code"], True)])
        visits = schema.tables["visits"]
        self.assertEqual(visits.column("id").type, "bigint")
        self.assertEqual(visits.column("status").default, "'open'::text")
        self.assertFalse(visits.column("email").not_null)
        self.assertEqual(visits.column("opened_at").type, "timestamp with time zone")
        self.assertEqual([(k.columns, k.ref_table, k.ref_columns) for k in visits.foreign_keys], [(["store_id"], "stores", ["id"])])
        indexes = {i.name: i for i in visits.indexes}
        self.assertEqual((indexes["visits_open"].columns, indexes["visits_open"].unique), (["store_id"], True))
        self.assertEqual(indexes["visits_open"].where, "status = 'open'::text")
        self.assertTrue(indexes["visits_email_lower"].has_expression)
        self.assertEqual(indexes["visits_email_lower"].columns, ["lower(email)"])
        self.assertEqual(len(visits.checks), 1)
        self.assertIn("status", visits.checks[0])
        self.assertEqual(schema.tables["store_visits"].primary_key, ["visit_id", "store_id"])

    def test_migration_error_names_file(self):
        self.write("db/0001_init.up.sql", "CREATE TABLE books (id text PRIMARY KEY);")
        self.write("db/0002_broken.up.sql", "ALTER TABLE missing ADD COLUMN x text;")
        with self.assertRaises(MigrationError) as cm:
            read_schema(self.project, postgresql_config())
        self.assertEqual(cm.exception.path, "db/0002_broken.up.sql")
        self.assertIn("missing", str(cm.exception))

    def test_unknown_image(self):
        self.write("db/0001_init.up.sql", "CREATE TABLE books (id text PRIMARY KEY);")
        config = DatabaseConfig("postgresql", "doc-structured-test/no-such-image:0", False, "db/*.up.sql", (4, 15))
        with self.assertRaises(MigrationError) as cm:
            read_schema(self.project, config)
        self.assertIn("PostgreSQL のコンテナを起動できない (イメージ doc-structured-test/no-such-image:0)", str(cm.exception))

    def test_sample_design_matches_postgresql_migration(self):
        self.copy_sample()
        self.disable_schema_actual()
        self.write(str(CONFIG_RELATIVE_PATH), POSTGRESQL_CONFIG)
        self.write("db/0001_init.up.sql", SAMPLE_MIGRATION)
        result = subprocess.run(
            [PYTHON, "-m", "doc_structured", "impl-diff"], cwd=self.project, env=clean_env(), capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "設計と実装に差分は無かった\n")


class WithoutDockerTest(ProjectTestCase):
    """Docker が無いとき、実行できないことと用意の仕方を伝え、終了コード 3 で終了する。"""

    def setUp(self):
        super().setUp()
        self.copy_sample()
        self.disable_schema_actual()
        self.write(str(CONFIG_RELATIVE_PATH), POSTGRESQL_CONFIG.replace("db/*.up.sql", "migrations/*.sql"))
        self.bin = self.tmp / "fake-bin"
        self.bin.mkdir()

    def fake_docker(self) -> None:
        """docker info が失敗する (デーモンに接続できない) 偽のコマンド docker。"""
        path = self.bin / "docker"
        path.write_text(
            "#!/bin/sh\necho 'Cannot connect to the Docker daemon at unix:///var/run/docker.sock.' >&2\nexit 1\n",
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def env_without_docker(self) -> dict[str, str]:
        """PATH から、コマンド docker のあるディレクトリを除き、偽のコマンドのディレクトリを先頭に加えた環境。"""
        directories = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d and not (os.path.isfile(os.path.join(d, "docker")))]
        return clean_env(PATH=os.pathsep.join([str(self.bin), *directories]))

    def run_tool(self, *args: str):
        return subprocess.run(
            [PYTHON, "-m", "doc_structured", *args], cwd=self.project, env=self.env_without_docker(),
            capture_output=True, text=True,
        )

    def test_daemon_not_running(self):
        self.fake_docker()
        for args in (("impl-diff",), ("check", "--heavy"), ("check", "--all")):
            with self.subTest(args=args):
                result = self.run_tool(*args)
                self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
                self.assertIn("Docker のデーモンに接続できない (Cannot connect to the Docker daemon", result.stderr)
                self.assertIn("Docker を起動する", result.stderr)

    def test_generate_all_with_schema_actual(self):
        self.fake_docker()
        config = self.project / CONFIG_RELATIVE_PATH
        config.write_text(config.read_text(encoding="utf-8") + "  schema_actual: true\n", encoding="utf-8")
        result = self.run_tool("generate", "--all")
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("実際のスキーマを読めないので、何も生成しなかった: Docker のデーモンに接続できない", result.stderr)

    def test_docker_command_missing(self):
        result = self.run_tool("impl-diff")
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("コマンド docker が無い", result.stderr)
        self.assertIn("Docker をインストールして起動する", result.stderr)

    def test_read_schema_raises_unavailable(self):
        self.fake_docker()
        old = os.environ["PATH"]
        os.environ["PATH"] = self.env_without_docker()["PATH"]
        self.addCleanup(os.environ.__setitem__, "PATH", old)
        with self.assertRaises(ImplementationUnavailable):
            read_schema(self.project, postgresql_config("migrations/*.sql"))


if __name__ == "__main__":
    unittest.main()
