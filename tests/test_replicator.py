from conftest import LEADER, leader_state

from copytrading.config import LeaderConfig, RiskConfig
from copytrading.models import AccountState, Position
from copytrading.replicator import Replicator, round_size

MIDS = {"BTC": 60_000.0, "ETH": 3_000.0}


def make(**risk):
    defaults = dict(my_equity=10_000, max_position_pct=1.0, max_leverage=10.0)
    defaults.update(risk)
    return Replicator([LeaderConfig(LEADER)], RiskConfig(**defaults), sz_decimals={"BTC": 5, "ETH": 4})


def me(equity=10_000.0, **positions):
    return AccountState("me", equity, {c: Position(c, sz, px, upnl)
                                       for c, (sz, px, upnl) in positions.items()})


def test_round_size_truncates_towards_zero():
    assert round_size(1.23456, 2) == 1.23
    assert round_size(-1.23956, 2) == -1.23


def test_copies_new_entry_proportionally():
    r = make()
    r.step({LEADER: leader_state()}, me(), MIDS)              # líder plano al arrancar
    orders = r.step({LEADER: leader_state(BTC=(1.0, 60_000))}, me(), MIDS)
    # líder: 1 BTC con 100k de equity -> yo: 0.1 BTC con 10k
    assert len(orders) == 1
    o = orders[0]
    assert o.coin == "BTC" and o.is_buy and abs(o.sz - 0.1) < 1e-9 and o.reason == "entrada"


def test_ignores_preexisting_positions_until_leader_reenters():
    r = make()
    lead = {LEADER: leader_state(BTC=(1.0, 50_000))}
    assert r.step(lead, me(), MIDS) == []
    assert r.step({LEADER: leader_state()}, me(), MIDS) == []          # el líder cierra
    orders = r.step({LEADER: leader_state(BTC=(-1.0, 60_000))}, me(), MIDS)  # nueva operación
    assert len(orders) == 1 and not orders[0].is_buy


def test_exit_when_leader_closes():
    r = make()
    r.step({LEADER: leader_state()}, me(), MIDS)
    orders = r.step({LEADER: leader_state()}, me(BTC=(0.1, 60_000, 0)), MIDS)
    assert len(orders) == 1
    assert not orders[0].is_buy and orders[0].reduce_only and orders[0].sz == 0.1


def test_partial_exit_and_rebalance_threshold():
    r = make()
    r.step({LEADER: leader_state()}, me(), MIDS)
    # el líder reduce a la mitad -> reducimos a la mitad
    orders = r.step({LEADER: leader_state(BTC=(0.5, 60_000))}, me(BTC=(0.1, 60_000, 0)), MIDS)
    assert orders[0].reduce_only and abs(orders[0].sz - 0.05) < 1e-9
    # cambio pequeño (<10 %) -> no se toca
    assert r.step({LEADER: leader_state(BTC=(0.52, 60_000))}, me(BTC=(0.05, 60_000, 0)), MIDS) == []


def test_flip_closes_then_opens():
    r = make()
    r.step({LEADER: leader_state()}, me(), MIDS)
    orders = r.step({LEADER: leader_state(BTC=(-1.0, 60_000))}, me(BTC=(0.1, 60_000, 0)), MIDS)
    assert [o.reduce_only for o in orders] == [True, False]
    assert not orders[1].is_buy and abs(orders[1].sz - 0.1) < 1e-9


def test_does_not_chase_price():
    r = make(max_entry_deviation_pct=0.01)
    r.step({LEADER: leader_state()}, me(), MIDS)
    # el líder entró a 58k y BTC ya está a 60k (+3.4 %) -> no entramos
    assert r.step({LEADER: leader_state(BTC=(1.0, 58_000))}, me(), MIDS) == []


def test_position_cap():
    r = make(max_position_pct=0.25)
    r.step({LEADER: leader_state()}, me(), MIDS)
    orders = r.step({LEADER: leader_state(equity=10_000, BTC=(1.0, 60_000))}, me(), MIDS)
    assert abs(orders[0].sz * 60_000 - 2_500) < 1


def test_stop_loss_closes_and_blocks_reentry():
    r = make(stop_loss_pct=0.05)
    r.step({LEADER: leader_state()}, me(), MIDS)
    lead = {LEADER: leader_state(BTC=(1.0, 60_000))}
    orders = r.step(lead, me(BTC=(0.1, 66_000, -600)), MIDS)   # -9 % sobre 6.6k
    assert len(orders) == 1 and orders[0].reduce_only
    assert r.step(lead, me(), MIDS) == []                       # sigue bloqueado
    r.step({LEADER: leader_state()}, me(), MIDS)                # el líder sale
    assert r.step(lead, me(), MIDS)                             # se vuelve a copiar


def test_daily_loss_limit_halts_and_closes_everything():
    r = make(daily_loss_limit_pct=0.05)
    lead = {LEADER: leader_state()}
    r.step(lead, me(), MIDS)
    lead = {LEADER: leader_state(BTC=(1.0, 60_000), ETH=(10, 3_000))}
    orders = r.step(lead, me(equity=9_000, BTC=(0.1, 60_000, 0)), MIDS)
    assert r.halted
    assert len(orders) == 1 and orders[0].coin == "BTC" and orders[0].reduce_only


def test_multiple_leaders_are_weighted():
    other = "0xother"
    r = Replicator([LeaderConfig(LEADER, 3), LeaderConfig(other, 1)],
                   RiskConfig(my_equity=10_000, max_position_pct=1, max_leverage=10))
    flat = {LEADER: leader_state(), other: leader_state()}
    r.step(flat, me(), MIDS)
    states = {LEADER: leader_state(ETH=(10, 3_000)), other: leader_state(ETH=(-10, 3_000))}
    targets, _ = r.target_positions(states, 10_000, MIDS)
    # 10 ETH * 7.5k/100k - 10 ETH * 2.5k/100k = 0.5 ETH
    assert abs(targets["ETH"] - 0.5) < 1e-9
