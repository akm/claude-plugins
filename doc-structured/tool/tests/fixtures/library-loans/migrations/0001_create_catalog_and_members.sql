-- 架空の題材「図書館の貸出」のマイグレーション (SQLite)。蔵書と利用者のテーブルを作る
CREATE TABLE books (
  id text PRIMARY KEY NOT NULL,
  title text NOT NULL,
  shelf_status text DEFAULT 'shelved' NOT NULL,
  call_number text NOT NULL,
  created_at integer NOT NULL,
  CHECK (shelf_status IN ('shelved', 'on_loan'))
);

CREATE TABLE categories (
  id text PRIMARY KEY NOT NULL,
  name text NOT NULL UNIQUE
);

CREATE TABLE book_categories (
  book_id text NOT NULL REFERENCES books (id),
  category_id text NOT NULL REFERENCES categories (id),
  PRIMARY KEY (book_id, category_id)
);
CREATE INDEX book_categories_category_idx ON book_categories (category_id);

CREATE TABLE members (
  id text PRIMARY KEY NOT NULL,
  name text NOT NULL
);
