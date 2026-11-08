"""検査が報告する問題。

出力の形は「<リポジトリのルートからのパス>:<行>:<列>: 検査 <記号>: <メッセージ>」。行と列は 1 から数える。
位置が無い問題 (ディレクトリやファイル全体の問題) は「<パス>: 検査 <記号>: <メッセージ>」。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Problem:
    check: str  # 検査の記号 (a・h・i)
    path: str  # リポジトリのルートからの相対パス
    message: str
    line: int | None = None  # 1 から数える
    column: int | None = None  # 1 から数える
    detail: str = ""  # メッセージの後に続ける複数行 (差分など)

    def format(self) -> str:
        where = self.path
        if self.line is not None:
            where += f":{self.line}"
            if self.column is not None:
                where += f":{self.column}"
        text = f"{where}: 検査 {self.check}: {self.message}"
        if self.detail:
            text += "\n" + self.detail.rstrip("\n")
        return text
