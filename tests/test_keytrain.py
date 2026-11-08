"""The key-training tools: label files load, scoring follows MIREX, and the model learns transposition."""
import numpy as np

from tools.keytrain import model as K
from tools.keytrain.get_data import SETS, rows


def test_label_files():
    key, mtg = rows(SETS["key"][0]), rows(SETS["mtg"][0])
    assert len(key) == 604 and len(mtg) == 1159
    assert all(K.parse(k) for _, _, k in mtg)
    assert not {c for c, _, _ in key} & {c for c, _, _ in mtg}          # train and test never overlap


def test_relations():
    c_maj, a_min = (0, False), (9, True)
    assert K.relation(c_maj, c_maj) == "exact"
    assert K.relation((7, False), c_maj) == "fifth"
    assert K.relation(a_min, c_maj) == "relative" and K.relation(c_maj, a_min) == "relative"
    assert K.relation((0, True), c_maj) == "parallel"
    s = K.score([c_maj, (7, False)], [c_maj, c_maj])
    assert s["exact"] == 0.5 and abs(s["weighted"] - 0.75) < 1e-9


def test_model_learns_all_transpositions_from_one():
    rng = np.random.default_rng(0)
    maj = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    mnr = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

    def track(t, minor):
        c = np.roll(mnr if minor else maj, t) + rng.normal(0, 0.4, 12)
        c = np.clip(c, 0.01, None); c /= c.sum()
        return np.stack([c, c, c, np.log(c + 1e-3)])

    train = [(0, False), (0, True)] * 40                                 # only C major and C minor
    F = np.stack([track(*k) for k in train])
    m = K.KeyModel().fit(K.rolled(F), train, epochs=60)
    test = [(t, mi) for t in range(12) for mi in (False, True)]
    pred = m.predict(K.rolled(np.stack([track(*k) for k in test])))
    assert np.mean([p == k for p, k in zip(pred, test)]) > 0.8
