"""worker_watch（#284）: 時計と、ファイルの状態を差し替えて、判定だけを確かめる。"""
from text_compositor.worker_watch import WatchState


class Fake:
    """ファイルの状態（{パス: (更新時刻, サイズ)}）と、時計。"""

    def __init__(self):
        self.files = {}
        self.now = 0.0

    def snapshot(self, files):
        return {f: self.files[f] for f in files if f in self.files}

    def clock(self):
        return self.now

    def state(self, settle=0.3):
        state = WatchState(self.snapshot, self.clock, settle)
        state.enabled = True
        return state


def settle_poll(fake, state, step=0.5):
    """`poll`を、確定するまでの間隔で、2回呼ぶ（1回目で変化を見つけ、2回目で止まったことを確かめる）。"""
    first = state.poll()
    fake.now += step
    return first + state.poll()


def test_nothing_changed_nothing_fires():
    fake = Fake()
    fake.files["a.md"] = (1, 10)
    state = fake.state()
    state.begin("a", ["a.md"])
    assert settle_poll(fake, state) == []


def test_a_change_fires_once_after_it_settles():
    fake = Fake()
    fake.files["a.md"] = (1, 10)
    state = fake.state()
    state.begin("a", ["a.md"])
    fake.files["a.md"] = (2, 12)
    assert state.poll() == []   # 変化を見つけただけ。まだ、止まったかは分からない
    fake.now += 0.5
    assert state.poll() == [("a", ["a.md"])]
    fake.now += 0.5
    assert state.poll() == []   # 重ねて知らせない


def test_changes_that_keep_coming_wait_until_they_stop():
    fake = Fake()
    fake.files["a.md"] = (1, 10)
    state = fake.state()
    state.begin("a", ["a.md"])
    fake.files["a.md"] = (2, 12)
    state.poll()
    fake.now += 0.2
    fake.files["a.md"] = (3, 14)   # 保存が、複数の書き込みに分かれた
    assert state.poll() == []
    fake.now += 0.2
    assert state.poll() == []   # まだ0.3秒たっていない
    fake.now += 0.2
    assert state.poll() == [("a", ["a.md"])]


def test_begin_resets_the_baseline_so_the_same_change_is_not_reported_again():
    fake = Fake()
    fake.files["a.md"] = (1, 10)
    state = fake.state()
    state.begin("a", ["a.md"])
    fake.files["a.md"] = (2, 12)
    state.poll()
    fake.now += 0.5
    assert state.poll() == [("a", ["a.md"])]
    state.begin("a", ["a.md"])   # 再変換を始めた
    fake.now += 0.5
    assert settle_poll(fake, state) == []


def test_a_save_during_the_conversion_is_found_afterwards():
    fake = Fake()
    fake.files["a.md"] = (1, 10)
    state = fake.state()
    state.begin("a", ["a.md"])
    fake.files["a.md"] = (2, 12)   # 変換の最中の保存（#424）
    state.finish("a", ["a.md"])
    state.poll()
    fake.now += 0.5
    assert state.poll() == [("a", ["a.md"])]


def test_a_dependency_is_watched_after_finish():
    fake = Fake()
    fake.files["a.md"] = (1, 10)
    fake.files["img.png"] = (1, 100)
    state = fake.state()
    state.begin("a", ["a.md"])
    state.finish("a", ["a.md", "img.png"])
    fake.files["img.png"] = (2, 100)
    state.poll()
    fake.now += 0.5
    assert state.poll() == [("a", ["img.png"])]


def test_a_dependency_that_appears_later_is_a_change():
    fake = Fake()
    fake.files["a.md"] = (1, 10)
    state = fake.state()
    state.begin("a", ["a.md"])
    state.finish("a", ["a.md", "later.png"])   # まだ無い参照先
    fake.files["later.png"] = (1, 50)
    state.poll()
    fake.now += 0.5
    assert state.poll() == [("a", ["later.png"])]


def test_a_missing_document_is_held_until_it_comes_back():
    fake = Fake()
    fake.files["a.md"] = (1, 10)
    state = fake.state()
    state.begin("a", ["a.md"])
    del fake.files["a.md"]   # 原子的な保存の途中
    for _ in range(5):
        fake.now += 0.5
        assert state.poll() == []
    fake.files["a.md"] = (2, 10)
    state.poll()
    fake.now += 0.5
    assert state.poll() == [("a", ["a.md"])]


def test_disabled_reports_nothing_but_remembers_changes():
    fake = Fake()
    fake.files["a.md"] = (1, 10)
    state = fake.state()
    state.begin("a", ["a.md"])
    state.enabled = False
    fake.files["a.md"] = (2, 12)
    assert settle_poll(fake, state) == []
    state.enabled = True   # 無効の間の変更も、有効に戻したとき、見つかる
    state.poll()
    fake.now += 0.5
    assert state.poll() == [("a", ["a.md"])]


def test_removed_keys_are_forgotten():
    fake = Fake()
    fake.files["a.md"] = (1, 10)
    state = fake.state()
    state.begin("a", ["a.md"])
    state.remove("a")
    fake.files["a.md"] = (2, 12)
    assert settle_poll(fake, state) == [] and not state.has("a")


def test_keys_are_independent():
    fake = Fake()
    fake.files["a.md"] = (1, 10)
    fake.files["b.md"] = (1, 10)
    state = fake.state()
    state.begin("a", ["a.md"])
    state.begin("b", ["b.md"])
    fake.files["b.md"] = (2, 10)
    state.poll()
    fake.now += 0.5
    assert state.poll() == [("b", ["b.md"])]
