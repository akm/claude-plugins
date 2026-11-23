-- 架空の題材「図書館の貸出」のマイグレーション (SQLite)。予約と貸出のテーブルを作る
CREATE TABLE reservations (
  id text PRIMARY KEY NOT NULL,
  book_id text NOT NULL REFERENCES books (id),
  previous_id text REFERENCES reservations (id),
  status text DEFAULT 'waiting' NOT NULL
);

CREATE TABLE loans (
  id text PRIMARY KEY NOT NULL,
  book_id text NOT NULL REFERENCES books (id),
  member_id text NOT NULL REFERENCES members (id),
  reservation_id text REFERENCES reservations (id),
  status text DEFAULT 'on_loan' NOT NULL,
  CONSTRAINT loans_status_check CHECK (status IN ('on_loan', 'returned'))
);
CREATE INDEX loans_member_idx ON loans (member_id);
-- 1 つの予約から作る貸出は 1 つだけ。予約の無い貸出は数えない (部分インデックス)
CREATE UNIQUE INDEX loans_reservation_unique ON loans (reservation_id) WHERE reservation_id IS NOT NULL;
