from copytrading.models import AccountState, Position
from copytrading.walletbias import Bias, compute


class FakeSource:
    def __init__(self, states):
        self.states = states

    def mid_prices(self):
        return {"BTC": 100.0, "ETH": 10.0}

    def account_state(self, a):
        return self.states[a]


def st(a, **pos):
    return AccountState(a, 1, {c: Position(c, sz, 1) for c, sz in pos.items()})


def test_one_vote_per_group_and_labels():
    src = FakeSource({
        "a": st("a", BTC=1.0), "b": st("b", BTC=-2.0), "c": st("c", BTC=-1.0),
        "t1": st("t1", ETH=100.0), "t2": st("t2", ETH=100.0),      # gemelas: un solo voto
        "d": st("d", ETH=-1.0),
    })
    wallets = [{"address": x, "grupo": x} for x in ("a", "b", "c", "d")]
    wallets += [{"address": "t1", "grupo": "gemelas"}, {"address": "t2", "grupo": "gemelas"}]
    res = compute(src, wallets, pause_s=0)
    btc, eth = res["BTC"], res["ETH"]
    assert (btc.longs, btc.shorts) == (1, 2) and btc.label == "MIXTO"
    assert (eth.longs, eth.shorts) == (1, 1) and eth.usd_long == 2000
    assert btc.flat == 2   # d y las gemelas no tienen BTC


def test_labels():
    assert Bias("BTC", longs=3, shorts=0).label == "ALCISTA"
    assert Bias("BTC", longs=1, shorts=4).label == "BAJISTA"
    assert Bias("BTC").label == "SIN POSICIONES"
