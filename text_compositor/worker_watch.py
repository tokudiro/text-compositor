"""常駐ワーカーの、ファイルの変更検知（#284）。

Viewerが開いている文書（`doc`）の原稿・参照ファイルと、名前つきのファイル（`watch`。プロジェクトの設定ファイル）を、
更新時刻とサイズで比べて、変更を知らせる。スレッドも時計も持たない（判定だけ）。呼び出し側が、一定の間隔で`poll`を呼ぶ。

- 方式は、CLIの`--watch`と同じ（`changes._watch_snapshot`）。更新時刻とサイズの比較なので、エディタの原子的な保存
  （一時ファイルへ書いて名前を付け替える）も、まだ無かった参照先が後から作られる場合も、検知できる。
- 保存が複数の書き込みに分かれても、変化が`settle`秒止まるのを待って、1回にまとめる。
- 先頭のファイル（原稿・設定ファイル）が、一時的に無いときは、現れるまで知らせない（原子的な保存の途中）。
- 基準は、変換を始める時点（`begin`）の状態。変換の最中の保存は、基準との差として、次の`poll`で見つかる（#424）。
  自動更新が無効の間も基準は動かさないので、有効に戻したとき、無効の間の変更も見つかる。
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Hashable, List, Optional, Tuple

from text_compositor.changes import _watch_snapshot

Snapshot = Dict[str, Tuple[int, int]]


def _stat_snapshot(files: List[str]) -> Snapshot:
    return _watch_snapshot([], [], files)


class _Entry:
    def __init__(self, files: List[str], baseline: Snapshot) -> None:
        self.files = files
        self.baseline = baseline
        self.seen: Optional[Snapshot] = None   # 直近の`poll`で見た、基準と違う状態
        self.changed_at = 0.0
        self.fired = False   # 知らせた後、呼び出し側が`begin`するまで、重ねて知らせない


class WatchState:
    """監視する対象の集まり。キーは、`("doc", 文書の識別子)`・`("watch", 名前)`など、呼び出し側が決める。"""

    def __init__(self, snapshot: Callable[[List[str]], Snapshot] = _stat_snapshot,
                 clock: Callable[[], float] = time.monotonic, settle: float = 0.3) -> None:
        self._snapshot = snapshot
        self._clock = clock
        self._settle = settle
        self._lock = threading.Lock()
        self._entries: Dict[Hashable, _Entry] = {}
        self.enabled = False   # 自動更新。無効の間は、`poll`は何も知らせない

    def begin(self, key: Hashable, files: List[str]) -> None:
        """変換を始める。`files`（先頭が原稿）を対象にして、いまの状態を基準にする。"""
        with self._lock:
            self._entries[key] = _Entry(list(files), self._snapshot(list(files)))

    def finish(self, key: Hashable, files: List[str]) -> None:
        """変換が終わった。対象を`files`に置き換える。増えた参照先の基準は、いまの状態にする。"""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            added = [f for f in files if f not in entry.files]
            entry.files = list(files)
            if added:
                entry.baseline.update(self._snapshot(added))
            entry.baseline = {p: v for p, v in entry.baseline.items() if p in entry.files}

    def remove(self, key: Hashable) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def has(self, key: Hashable) -> bool:
        with self._lock:
            return key in self._entries

    def poll(self) -> List[Tuple[Hashable, List[str]]]:
        """変更が確定した対象を、(キー, 変わったパスの一覧)で返す。無効の間は、空。"""
        fired: List[Tuple[Hashable, List[str]]] = []
        with self._lock:
            if not self.enabled:
                return fired
            now = self._clock()
            for key, entry in self._entries.items():
                if entry.fired or not entry.files:
                    continue
                current = self._snapshot(entry.files)
                if current == entry.baseline:
                    entry.seen = None
                    continue
                if entry.files[0] not in current:
                    entry.seen = None   # 原稿が無い。現れるまで待つ
                    continue
                if current != entry.seen:
                    entry.seen = current
                    entry.changed_at = now
                    continue
                if now - entry.changed_at >= self._settle:
                    entry.fired = True
                    fired.append((key, sorted(p for p in set(current) | set(entry.baseline)
                                              if current.get(p) != entry.baseline.get(p))))
        return fired
