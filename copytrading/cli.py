"""Línea de comandos.

    python -m copytrading discover  --config config.toml
    python -m copytrading backtest  --config config.toml --address 0x...
    python -m copytrading run       --config config.toml [--live]
    python -m copytrading liquidity --coin BTC [--html-dir reportes]
    python -m copytrading metodo    --coin BTC --interval 4h [--stop close --trend channel]
    python -m copytrading monitor   --coins BTC,ETH,SOL [--journal data/diario.jsonl]
    python -m copytrading diario    add --coin BTC --side long --entry 77000 --stop 75800 --tp1 79100 --tp2 80400
    python -m copytrading diario    report
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .backtest import run_backtest
from .config import Config
from .execution.paper import PaperExecutor
from .liquidity import build_heatmap, collect_liquidations, render_html, render_text, wallets_to_scan
from .runner import run
from .scoring import MS_PER_DAY, apply_filters, compute_stats, prefilter_leaderboard, score
from .sources.hyperliquid import HyperliquidSource


def cmd_discover(cfg: Config, args) -> None:
    src = HyperliquidSource(cfg.network)
    end = int(time.time() * 1000)
    start = end - cfg.scoring.lookback_days * MS_PER_DAY
    candidates = prefilter_leaderboard(src.leaderboard(), cfg.scoring, top_n=args.top)
    print(f"{len(candidates)} candidatos tras el prefiltro del leaderboard. Analizando historial...\n")
    results = []
    for c in candidates:
        try:
            fills = src.fills(c.address, start, end)
        except Exception as exc:
            print(f"  {c.address}: error descargando fills ({exc})")
            continue
        st = apply_filters(compute_stats(c.address, fills, c.account_value, start, end), cfg.scoring)
        score(st, cfg.scoring)
        results.append(st)
    results.sort(key=lambda s: (s.eligible, s.score), reverse=True)

    print(f"{'wallet':44} {'score':>5} {'trades':>6} {'win%':>5} {'PF':>5} {'sharpe':>6} "
          f"{'maxDD':>6} {'hold(min)':>9} {'PnL':>12}")
    for s in results:
        flag = "OK " if s.eligible else "-- "
        print(f"{flag}{s.address:42} {s.score:5.2f} {s.n_trades:6d} {s.win_rate:5.0%} "
              f"{min(s.profit_factor, 99):5.2f} {s.sharpe:6.2f} {s.max_drawdown:6.0%} "
              f"{s.avg_hold_minutes:9.0f} {s.total_pnl:12,.0f}")
        if not s.eligible and args.verbose:
            print("     descartado: " + "; ".join(s.rejected_reasons))
    elegibles = [s for s in results if s.eligible][: args.select]
    if elegibles:
        print("\nAñade esto a tu config.toml (después ejecuta `backtest` para cada uno):\n")
        for s in elegibles:
            print(f'[[leaders]]\naddress = "{s.address}"\nweight = {s.score:.2f}\n')


def cmd_backtest(cfg: Config, args) -> None:
    src = HyperliquidSource(cfg.network)
    end = int(time.time() * 1000)
    start = end - args.days * MS_PER_DAY
    addresses = [args.address] if args.address else [l.address for l in cfg.leaders]
    for addr in addresses:
        fills = src.fills(addr, start, end)
        equity = src.account_state(addr).equity
        res = run_backtest(addr, fills, equity, cfg.risk, latency_ms=args.latency_ms,
                           latency_slippage_bps=args.latency_bps, sz_decimals=src.size_decimals())
        print(res.summary() + "\n")


def cmd_run(cfg: Config, args) -> None:
    if not cfg.leaders:
        raise SystemExit("No hay líderes en el config. Ejecuta `discover` y añade [[leaders]].")
    src = HyperliquidSource(cfg.network)
    live = args.live or cfg.mode == "live"
    if live:
        if not args.live:
            raise SystemExit("mode = 'live' en el config requiere además el flag --live")
        from .execution.hyperliquid_live import HyperliquidLiveExecutor
        executor = HyperliquidLiveExecutor(cfg.network)
        logging.warning("MODO REAL en %s: se enviarán órdenes con dinero real", cfg.network)
    else:
        executor = PaperExecutor(cfg.risk.my_equity)
        logging.info("Modo paper trading con $%.2f simulados", cfg.risk.my_equity)
    run(cfg, src, executor, max_iterations=args.iterations)


def cmd_liquidity(cfg: Config, args) -> None:
    src = HyperliquidSource(cfg.network)
    coins = [c.strip().upper() for c in args.coin.split(",")]
    wallets = wallets_to_scan(src, args.wallets)
    print(f"Leyendo posiciones de {len(wallets)} wallets...")
    points = collect_liquidations(src, wallets,
                                  on_progress=lambda i: print(f"  {i}/{len(wallets)}", end="\r"))
    print()
    mids = src.mid_prices()
    now = datetime.now(timezone.utc)
    for coin in coins:
        if coin not in mids:
            print(f"{coin}: moneda no encontrada en Hyperliquid")
            continue
        hm = build_heatmap(points, coin, mids[coin], range_pct=args.range / 100, band_pct=args.band / 100)
        print(render_text(hm) + "\n")
        if args.html_dir:
            out = Path(args.html_dir) / f"liquidez_{coin}_{now:%Y-%m-%d}.html"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(render_html(hm, f"{now:%Y-%m-%d %H:%M} UTC"), encoding="utf-8")
            print(f"Guardado {out}\n")


def cmd_metodo(cfg: Config, args) -> None:
    import dataclasses

    from .method.backtest import MethodConfig, compute_channels, compute_liquidity, run
    from .method.emas import ema_series, parse_spec

    src = HyperliquidSource(cfg.network)
    end = int(time.time() * 1000)
    candles = src.candles(args.coin, args.interval, end - args.days * MS_PER_DAY, end)
    if len(candles) < 200:
        raise SystemExit(f"Muy pocas velas ({len(candles)}) para {args.coin} {args.interval}")
    mc = MethodConfig(lookback=args.lookback, entry=args.entry, stop_mode=args.stop,
                      trend=args.trend, min_sweep=args.sweep, channel=args.channel,
                      pivot_k=args.pivot_k, ema=args.ema if args.ema_mode != "none" else "",
                      ema_mode=args.ema_mode)
    liq = compute_liquidity(candles, mc)
    channels = compute_channels(candles, mc)
    cut = int(len(candles) * 0.7)
    fmt = lambda ts: datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m-%d")
    print(f"{args.coin} {args.interval}: {len(candles)} velas, {fmt(candles[0].t)} -> {fmt(candles[-1].t)}")
    print(f"Entrenamiento hasta {fmt(candles[cut].t)}, validación después.\n")
    print(f"{'variante':16} {'tramo':12} {'trades':>6} {'win':>5} {'expR':>6} {'PF':>5} {'retorno':>8} {'maxDD':>6}")
    for name, c in (("canal+liquidez", mc), ("solo canal", dataclasses.replace(mc, use_liquidity=False))):
        for lab, (a, b) in (("entrenam.", (0, cut)), ("validación", (cut, len(candles))),
                            ("todo", (0, len(candles)))):
            r = run(candles, c, a, b, liq=liq, channels=channels)
            print(f"{name:16} {lab:12} {r.n:6} {r.win_rate:5.0%} {r.expectancy:+6.2f} "
                  f"{min(r.profit_factor, 99):5.2f} {r.total_return:+8.1%} {r.max_drawdown:6.1%}")
    full = run(candles, mc, liq=liq, channels=channels)
    if full.trades:
        print("\nÚltimas operaciones del método:")
        for t in full.trades[-args.last:]:
            print(f"  {fmt(candles[t.entry_i].t)} {t.side:5} entrada {t.entry:,.1f} stop {t.stop:,.1f} "
                  f"TP1 {t.tp1:,.1f} TP2 {t.tp2:,.1f} -> {t.exit_reason} {t.r:+.2f}R")
    i = len(candles) - 1
    ch = channels[i]
    s = liq[i]
    canal = (f"canal {ch.lower(i):,.1f} – {ch.mid(i):,.1f} – {ch.upper(i):,.1f} ({ch.shape()})"
             if ch else "sin canal vigente (líneas rotas)")
    print(f"\nAhora: precio {candles[i].c:,.1f} | {canal}")
    for tf, n in parse_spec(args.ema):
        e = ema_series(candles, tf, n)[i]
        if e:
            print(f"EMA {n} ({tf}): {e:,.1f} ({(candles[i].c / e - 1):+.1%} del precio)")
    print(f"Liquidez estimada (±{mc.liq_range:.0%}): longs abajo {s.long_below:.1f} / shorts arriba "
          f"{s.short_above:.1f} (en velas de volumen); nivel más cargado abajo {s.best_long_px:,.1f}, "
          f"arriba {s.best_short_px:,.1f}")


def _fmt_time(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def cmd_monitor(cfg: Config, args) -> None:
    from .method.monitor import analyze, closed_candles, load_journal, record_signals, save_journal, summary
    from .method.monitor import update_outcome

    src = HyperliquidSource(cfg.network)
    journal = Path(args.journal)
    entries = load_journal(journal)
    now = int(time.time() * 1000)
    alerts = []
    details: list[str] = []
    levels: set[str] = set()
    from .liquidity import whale_zones
    from .method.shortliq import describe as st_describe
    from .method.shortliq import short_term_zones
    coin_list = [c.strip().upper() for c in args.coins.split(",")]
    whales = {}
    if args.whales:
        try:
            mids = src.mid_prices()
            whales = whale_zones(src, coin_list, {c: float(mids.get(c, 0) or 0) for c in coin_list}, top=args.whales)
        except Exception as exc:
            print(f"Ballenas: no se pudieron leer ({exc})")
    layers: dict[str, dict] = {}
    for coin in coin_list:
        candles = closed_candles(src.candles(coin, "4h", now - args.days * MS_PER_DAY, now), "4h", now)
        if len(candles) < 300:
            print(f"{coin}: pocas velas ({len(candles)})")
            continue
        st = analyze(coin, candles)
        icon = {"SEÑAL": "🚨", "VIGILAR": "👀"}.get(st.status, "·")
        print(f"\n{icon} {coin} {st.status} — {st.price:,.1f} (vela {_fmt_time(st.time)})")
        for n in st.notes:
            print(f"   {n}")
        from .method.monitor import trend_state
        tr, _, tr_slope = trend_state(candles)
        print(f"   Tendencia: {tr} (EMA 50 diaria {tr_slope:+.1%} en 6 días) → buscar solo "
              f"{'largos' if tr == 'ALCISTA' else 'cortos' if tr == 'BAJISTA' else '-'}")
        c1h_st = closed_candles(src.candles(coin, "1h", now - 8 * MS_PER_DAY, now), "1h", now)
        st_long, st_short = short_term_zones(c1h_st) if len(c1h_st) > 48 else ([], [])
        for n in st_describe(st_long, st_short):
            print(f"   {n}")
        for z in whales.get(coin, []):
            kind = "largos" if z.side == "long" else "cortos"
            print(f"   🐋 Ballenas Hyperliquid: ${z.usd / 1e6:,.0f}M de {kind} se liquidan en {z.low:,.0f}–{z.high:,.0f}"
                  f" ({z.n} posición{'es' if z.n != 1 else ''})")
        layers[coin] = {"st": st_long + st_short, "whales": whales.get(coin, [])}
        # memoria: patrones medidos activos y casos parecidos; y anota sola los movimientos fuertes
        try:
            from .method.memoria import auto_record, memory_lines
            new_case = auto_record(coin, candles, c1h_st)
            if new_case:
                print(f"   🧠 Memoria: movimiento fuerte anotado como caso ({new_case})")
            mem = memory_lines(coin, candles, c1h_st)
            for n in mem:
                print(f"   🧠 {n}")
            layers[coin]["memory"] = mem
        except Exception as exc:
            print(f"   🧠 memoria: no disponible ({exc})")
        for source, t in st.signals.items():
            print(f"   {source}: {t.side.upper()} entrada {t.entry:,.1f} stop {t.stop:,.1f} "
                  f"TP1 {t.tp1:,.1f} TP2 {t.tp2:,.1f}")
        for e in record_signals(entries, st, "4h"):
            alerts.append(f"{e.coin} {e.side} ({e.source})")
            levels.add("SEÑAL")
        if st.status == "VIGILAR":
            alerts.append(f"{coin} vigilar")
            levels.add("VIGILAR")
        if st.status != "-":
            details.append(f"{icon} {coin} {st.status} {st.price:,.1f}")
            details.extend(f"  {n}" for n in st.notes)
            details.extend(f"  {src_}: {t.side.upper()} entrada {t.entry:,.1f} stop {t.stop:,.1f} "
                           f"TP1 {t.tp1:,.1f} TP2 {t.tp2:,.1f}" for src_, t in st.signals.items())
        for e in entries:
            if e.coin == coin and e.interval == "4h" and e.source != "juan":
                before = e.status
                update_outcome(e, candles)
                if before == "abierta" and e.status == "cerrada":
                    alerts.append(f"{e.coin} {e.source} cerrada {e.r:+.2f}R ({e.exit_reason})")
                    details.append(f"✅ {e.coin} {e.source} cerrada {e.r:+.2f}R ({e.exit_reason})")
                    levels.add("CERRADA")
    # rupturas recientes en 1H: ¿perfil de trampa o real? (estudio docs/METODO: trampas)
    from .method.traps import describe, recent_breakouts
    window_ms = args.alert_hours * 3_600_000
    print("\nRupturas recientes (1H):")
    any_brk = False
    for coin in [c.strip().upper() for c in args.coins.split(",")]:
        c1h = closed_candles(src.candles(coin, "1h", now - 4 * MS_PER_DAY, now), "1h", now)
        for lb in recent_breakouts(c1h, window=int(args.alert_hours) + 1):
            msg = describe(coin, lb)
            print("   " + msg)
            any_brk = True
            when = lb.failed_at or lb.t
            if when >= now - window_ms:
                alerts.append(msg.split(" — ")[0] + " — falló" if lb.failed_at else msg.split(" (")[0])
                details.append(msg)
                levels.add("VIGILAR")
    if not any_brk:
        print("   ninguna")

    # planes y operaciones de Juan: se siguen con velas de su temporalidad (1H o 4H)
    for coin, iv in sorted({(e.coin, e.interval) for e in entries if e.status in ("pendiente", "abierta")
                            and (e.interval in ("1h", "15m") or e.source == "juan")}):
        c1 = closed_candles(src.candles(coin, iv, now - 30 * MS_PER_DAY, now), iv, now)
        for e in entries:
            if e.coin != coin or e.interval != iv or e.status not in ("pendiente", "abierta"):
                continue
            if iv == "4h" and e.source != "juan":
                continue
            before = e.status
            update_outcome(e, c1)
            # solo avisar de cambios recientes: si el diario no se pudo guardar en la ejecución anterior,
            # el cambio se recalcula igual pero no se repite el aviso
            changed_at = {"abierta": e.time, "cerrada": e.exit_time}.get(e.status, now)
            if before != e.status and changed_at >= now - args.alert_hours * 3_600_000:
                msg = {"abierta": f"🎯 {e.coin} plan {e.side} ACTIVADO en {e.entry:,.1f} ({e.note})",
                       "cerrada": f"✅ {e.coin} {e.source} cerrada {e.r:+.2f}R ({e.exit_reason})",
                       "caducada": f"⌛ {e.coin} plan {e.side} caducó sin activarse ({e.note})",
                       "anulada": f"✖ {e.coin} plan {e.side} anulado: {e.exit_reason}"}.get(e.status)
                if msg:
                    alerts.append(msg)
                    details.append(msg)
                    levels.add("CERRADA" if e.status == "cerrada" else ("SEÑAL" if e.status == "abierta" else "VIGILAR"))
    save_journal(journal, entries)
    from .walletbias import report as wallet_report
    from .whalewatch import append_history, describe as whale_describe, episodes, load_watchlist
    for w in load_watchlist():
        try:
            wf = src.fills(w["address"], now - 5 * MS_PER_DAY, now)
            eps = episodes(w["address"], wf)
            append_history(eps)
            pos = src.account_state(w["address"]).positions
        except Exception as exc:
            print(f"\n🐋 {w['alias']}: no se pudo leer ({exc})")
            continue
        print(f"\n🐋 {w['alias']} ({w['address'][:8]}…), en seguimiento (solo información):")
        time.sleep(0.3)                    # varias ballenas seguidas: respetar el límite de la API
        for coin_, p_ in pos.items():
            if coin_ in coin_list and abs(p_.size * (p_.liquidation_px or p_.entry_px or 0)) > 1e6:
                liq_txt = f"liquidación {p_.liquidation_px:,.1f}" if p_.liquidation_px else "sin liquidación cercana"
                print(f"   {coin_}: {'largo' if p_.size > 0 else 'corto'} {abs(p_.size):,.2f} · {liq_txt}")
        for e in eps:
            # solo las monedas que seguimos y movimientos grandes; avisar al móvil solo los muy grandes
            if e.end >= now - args.alert_hours * 3_600_000 and e.coin in coin_list and e.usd >= 5_000_000:
                msg = whale_describe(w["alias"], e)
                print("   " + msg)
                if e.usd >= 10_000_000:
                    alerts.append(f"{e.coin} {msg}")
                    details.append(msg)
                    levels.add("VIGILAR")
    trend_labels: dict = {}
    wallet_lines = wallet_report(src, labels=trend_labels)
    for coin_, lab in trend_labels.items():
        layers.setdefault(coin_, {})["bias"] = lab
    if wallet_lines:
        print("\n" + "\n".join(wallet_lines))
    print("\nDiario (" + str(journal) + "):")
    for line in summary(entries):
        print("   " + line)
    print("\nRESUMEN: " + ("; ".join(alerts) if alerts else "sin novedades"))
    from .method.monitor import trading_allowed
    allowed = trading_allowed(now)
    if not allowed:
        print("📵 Viernes/sábado (o domingo antes de las 13 h Colombia): solo contexto, no se opera")
    if args.notify and alerts:
        from .notify import send_alert
        level = next(lv for lv in ("SEÑAL", "CERRADA", "VIGILAR") if lv in levels)
        icon = {"SEÑAL": "🚨", "CERRADA": "✅", "VIGILAR": "👀"}[level]
        if not allowed and level == "SEÑAL":   # fin de semana: la señal es solo contexto
            level, icon = "VIGILAR", "📵"
        title = f"{icon} {level}{'' if allowed else ' (fin de semana, solo contexto)'}: " + "; ".join(alerts)
        body = "\n".join(details + [""] + wallet_lines + ["", "Diario:"] + summary(entries)
                         + ["", "Información para decidir, no una orden de operar."])
        topic = args.ntfy_topic or os.environ.get("NTFY_TOPIC")
        imaged = _send_images(src, entries, alerts, wallet_lines, level, allowed, now, topic, layers)
        if imaged:
            print(f"AVISO: enviado con imagen ({'; '.join(imaged)})")
        else:
            sent = send_alert(title[:120], body, level, ntfy_topic=args.ntfy_topic)
            print("AVISO: " + (f"enviado por {', '.join(sent)}" if sent else "NO enviado (revisa el canal)"))


COINS_ORDER = ("BTC", "ETH", "SOL")


def _send_images(src, entries, alerts: list[str], wallet_lines: list[str], level: str, allowed: bool,
                 now: int, topic: str | None, layers: dict | None = None) -> list[str]:
    """Un aviso por moneda con novedades (BTC primero): gráfico + 3-5 líneas en lenguaje simple.

    Devuelve las monedas enviadas; lista vacía si no se pudo (entonces se manda el aviso de texto).
    """
    import re
    import tempfile

    from .method.monitor import closed_candles
    from .notify import send_image_alert
    try:
        from .chart import coin_image
    except Exception:
        return []
    by_coin: dict[str, list[str]] = {}
    for a in alerts:
        m = re.search(r"\b(BTC|ETH|SOL|[A-Z]{2,6})\b", a)
        if m:
            by_coin.setdefault(m.group(1), []).append(a)
    coins = sorted(by_coin, key=lambda c: COINS_ORDER.index(c) if c in COINS_ORDER else 99)
    trend = {}
    section = ""
    for ln in wallet_lines:
        if "tendencia" in ln:
            section = "t"
        elif "corto plazo" in ln:
            section = "c"
        m = re.match(r"\s+([A-Z]+): ([A-ZÁÉÍÓÚ ]+?) \(", ln)
        if m and section == "t":
            trend[m.group(1)] = m.group(2).strip()
    sent = []
    icon = {"SEÑAL": "🚨", "CERRADA": "✅", "VIGILAR": "👀"}.get(level, "👀")
    for coin in coins:
        try:
            c4 = closed_candles(src.candles(coin, "4h", now - 830 * MS_PER_DAY, now), "4h", now)
            c1 = src.candles(coin, "1h", now - 4 * MS_PER_DAY, now)
            events = [_plain_event(a) for a in by_coin[coin] if "ACTIVADO" in a or "cerrada" in a
                      or "caducó" in a or "anulado" in a]
            path = os.path.join(tempfile.gettempdir(), f"monitor_{coin.lower()}.png")
            _, sm = coin_image(path, coin, c4, c1, entries, now, events=events, **(layers or {}).get(coin, {}))
            lines = sm.happened[:2] + ["Vigilar: " + w for w in sm.watch[:2]]
            if coin in trend:
                lines.append(f"Billeteras de tendencia: {trend[coin]}")
            if not allowed:
                lines.append("Fin de semana: solo contexto, no se opera")
            title = f"{icon} {coin} {sm.price:,.0f}".replace(",", ".") + f" · {sm.state}"
            channels = send_image_alert(title, "\n".join(lines), path, level, ntfy_topic=topic)
            if channels:
                sent.append(f"{coin}: {', '.join(channels)}")
        except Exception as exc:          # una moneda que falle no debe tumbar el resto
            print(f"   imagen {coin}: no se pudo ({exc})")
    return sent


def _plain_event(a: str) -> str:
    """'🎯 BTC plan short ACTIVADO en 77,077.0 (D: ...)' -> 'Plan D ACTIVADO: venta en 77.077'."""
    import re
    m = re.search(r"plan (long|short) ACTIVADO en ([\d,\.]+) \(([A-Z]\d?):", a)
    if m:
        verb = "venta" if m.group(1) == "short" else "compra"
        px = float(m.group(2).replace(",", ""))
        return f"Plan {m.group(3)} ACTIVADO: {verb} en {px:,.0f}".replace(",", ".")
    m = re.search(r"cerrada ([+-][\d.]+R) \((.*)\)", a)
    if m:
        return f"Operación cerrada: {m.group(1)} ({m.group(2)})"
    return re.sub(r"^\W+\s*", "", a).split(" (")[0]


def cmd_trampas(cfg: Config, args) -> None:
    from .method.traps import find_breakouts, report

    src = HyperliquidSource(cfg.network)
    end = int(time.time() * 1000)
    hours = {"1h": 1, "4h": 4}[args.interval]
    allb = []
    for coin in [c.strip().upper() for c in args.coins.split(",")]:
        cs = src.candles(coin, args.interval, end - args.days * MS_PER_DAY, end)
        allb += find_breakouts(cs, lookback=24 // hours, hold=max(1, 6 // hours), after=24)
    print("\n".join(report(f"{args.coins} {args.interval}", allb)))


def cmd_ballena(cfg: Config, args) -> None:
    """Historial de una ballena seguida: episodios, qué hizo el precio después y si acierta o falla."""
    from datetime import timedelta
    from .whalewatch import append_history, episodes, forward_move, load_watchlist, score

    src = HyperliquidSource(cfg.network)
    now = int(time.time() * 1000)
    targets = [{"address": args.address, "alias": args.address[:10]}] if args.address else load_watchlist()
    cot = timezone(timedelta(hours=-5))
    for w in targets:
        fills = src.fills(w["address"], now - args.days * MS_PER_DAY, now)
        eps = episodes(w["address"], fills)
        added = append_history(eps)
        coins = sorted({e.coin for e in eps})
        cbc = {c: src.candles(c, "1h", now - (args.days + 5) * MS_PER_DAY, now) for c in coins}
        print(f"\n🐋 {w['alias']} — {w['address']}")
        print(f"   PnL realizado {args.days} días: ${sum(f.closed_pnl - f.fee for f in fills) / 1e6:+,.2f}M · "
              f"episodios ≥ $1M: {len(eps)} (nuevos en el historial: {added})")
        for e in eps:
            m24 = forward_move(cbc[e.coin], e.end, 24)
            m72 = forward_move(cbc[e.coin], e.end, 72)
            fmt = lambda m: "  —  " if m is None else f"{m:+.1%}"
            when = datetime.fromtimestamp(e.start / 1000, cot).strftime("%d %b %H:%M")
            print(f"   {when} {e.coin:<5} {e.direction:<11} ${e.usd / 1e6:6.1f}M @ {e.avg_px:>10,.1f} "
                  f"PnL ${e.pnl / 1e6:+6.2f}M | precio después 24h {fmt(m24)} · 72h {fmt(m72)}")
        sc = score(eps, cbc)
        print(f"   Aperturas: {sc['aperturas_acertadas']} a favor / {sc['aperturas_falladas']} en contra (72 h) · "
              f"capitulaciones (cierres en pérdida): {sc['capitulaciones']}, "
              f"{sc['capitulaciones_en_suelo']} justo antes de un rebote")


def cmd_hft(cfg: Config, args) -> None:
    """Radar de alta frecuencia: encuentra y clasifica los robots del ranking de Hyperliquid."""
    import json
    from .hft import as_dict, scan

    src = HyperliquidSource(cfg.network)
    profiles = scan(src, top=args.top)
    print(f"{'cuenta':<12} {'tipo':<19} {'vol. semana':>11} {'PnL semana':>11} {'fills/h':>8} {'maker':>6} "
          f"{'tamaño med.':>11} {'órdenes':>7}  monedas")
    for p in profiles:
        print(f"{p.address[:10]:<12} {p.kind:<19} ${p.week_volume / 1e9:8.1f}B ${p.week_pnl / 1e6:+8.1f}M "
              f"{p.fills_per_hour:8.0f} {p.maker_share:6.0%} ${p.median_usd:10,.0f} {p.open_orders:7}  "
              f"{', '.join(p.top_coins)}")
        if args.detalle:
            falla = [k for k, ok in (p.checks or {}).items() if not ok]
            print(f"{'':12} rotación {p.turnover:6.0f}x · equilibrio {p.net_ratio:.0%} · ida y vuelta "
                  f"{p.round_trip_h:5.1f} h · fills/orden {p.fills_per_order:4.1f} · TWAP {p.twap_share:.0%} · "
                  f"cambio de órdenes {p.order_churn:.0%}" + (f" · no cumple: {'; '.join(falla)}" if falla else ""))
    kinds: dict[str, list] = {}
    for p in profiles:
        kinds.setdefault(p.kind, []).append(p)
    print("\nResumen por tipo:")
    for k, ps in kinds.items():
        print(f"  {k:<19} {len(ps):2} cuentas · PnL semana ${sum(p.week_pnl for p in ps) / 1e6:+.1f}M · "
              f"volumen ${sum(p.week_volume for p in ps) / 1e9:.0f}B")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"actualizado": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                               "cuentas": [as_dict(p) for p in profiles]}, indent=1), encoding="utf-8")
    print(f"\nGuardado en {out}")


def cmd_memoria(cfg: Config, args) -> None:
    """Patrones medidos activos ahora y casos anotados que se parecen al momento actual."""
    from .method.memoria import load_cases, matching_cases, memory_lines, tags
    from .method.monitor import closed_candles

    src = HyperliquidSource(cfg.network)
    now = int(time.time() * 1000)
    for coin in [c.strip().upper() for c in args.coins.split(",")]:
        c4 = closed_candles(src.candles(coin, "4h", now - 830 * MS_PER_DAY, now), "4h", now)
        c1 = closed_candles(src.candles(coin, "1h", now - 10 * MS_PER_DAY, now), "1h", now)
        print(f"\n🧠 {coin} — patrones activos: {', '.join(tags(c4, c1)) or 'ninguno'}")
        for line in memory_lines(coin, c4, c1):
            print(f"   {line}")
    print(f"\nCasos anotados en la memoria: {len(load_cases())} (data/casos.json)")


def cmd_billeteras(cfg: Config, args) -> None:
    from .walletbias import report as wallet_report

    print("\n".join(wallet_report(HyperliquidSource(cfg.network))) or "Sin lista en data/indicador_billeteras.json")


def cmd_aviso_prueba(cfg: Config, args) -> None:
    from .notify import send_alert

    sent = send_alert("🧪 Prueba del monitor de trading",
                      "Si ves esto en el móvil, las alertas de BTC, ETH y SOL te llegarán aquí.",
                      "PRUEBA", ntfy_topic=args.ntfy_topic)
    print(f"Enviado por: {', '.join(sent)}" if sent else "No se pudo enviar por ningún canal")
    if not sent:
        raise SystemExit(1)


def _parse_cot(text: str) -> int:
    from datetime import timedelta
    d = datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone(timedelta(hours=-5)))
    return int(d.timestamp() * 1000)


def cmd_diario(cfg: Config, args) -> None:
    from .method.monitor import load_journal, manual_entry, save_journal, summary

    journal = Path(args.journal)
    entries = load_journal(journal)
    if args.accion == "plan":
        from .method.monitor import manual_plan
        e = manual_plan(args.coin.upper(), args.side, args.trigger, args.trigger_dir, args.stop,
                        args.tp1, args.tp2, args.horas, args.nota, interval=args.intervalo,
                        sweep=args.barrido or 0.0,
                        start_ms=_parse_cot(args.desde) if args.desde else None)
        entries.append(e)
        save_journal(journal, entries)
        tf = args.intervalo.upper()
        cond = {"below": f"cierre {tf} por debajo de", "above": f"cierre {tf} por encima de",
                "touch_below": "el precio baja a", "touch_above": "el precio sube a"}[e.trigger_dir]
        if e.sweep:
            cond = f"barre {e.sweep} y luego {cond}"
        print(f"Plan apuntado: {e.coin} {e.side} si {cond} {e.trigger} | stop {e.stop} TP1 {e.tp1} TP2 {e.tp2} "
              f"| caduca en {args.horas} h")
        return
    if args.accion == "add":
        e = manual_entry(args.coin.upper(), args.side, args.entry, args.stop, args.tp1, args.tp2, args.nota)
        entries.append(e)
        save_journal(journal, entries)
        print(f"Apuntada: {e.coin} {e.side} entrada {e.entry} stop {e.stop} TP1 {e.tp1} TP2 {e.tp2}")
        return
    for e in entries[-args.last:]:
        print(f"{_fmt_time(e.time)} {e.source:10} {e.coin:4} {e.side:5} {e.entry:>10,.1f} stop {e.stop:>10,.1f} "
              f"-> {e.status} {e.r:+.2f}R {e.exit_reason} {e.note}")
    print()
    for line in summary(entries):
        print(line)


def cmd_pools(cfg: Config, args) -> None:
    from .method.pools import config_for, merge, report, study

    src = HyperliquidSource(cfg.network)
    end = int(time.time() * 1000)
    hours = {"1h": 1, "4h": 4}[args.interval]
    sc = config_for(hours)
    results = []
    for coin in [c.strip().upper() for c in args.coins.split(",")]:
        candles = src.candles(coin, args.interval, end - args.days * MS_PER_DAY, end)
        res = study(candles, sc)
        results.append(res)
        print("\n".join(report(f"{coin} {args.interval}", res, sc)) + "\n")
    if len(results) > 1:
        print("\n".join(report(f"TOTAL {args.interval}", merge(results), sc)))


def cmd_rendimiento(cfg: Config, args) -> None:
    from .escucha import load_radar
    from .rendimiento import cohort, last_winners, report, save, scan, select_winners

    addresses, desde = cohort()
    if not addresses:
        print("No hay cohorte (data/hft_cohorte.json) ni datos de la escucha para saber qué cuentas revisar.")
        return
    rows = scan(HyperliquidSource(cfg.network), addresses, args.desde or desde)
    winners = select_winners(rows, last_winners())
    print("\n".join(report(rows, args.desde or desde, load_radar(), winners)))
    if not args.no_guardar:
        save(rows, winners=winners)


def cmd_avisos(cfg: Config, args) -> None:
    from .avisos import load_events, measure, report, typical_move

    events = load_events(Path(args.archivo))
    if not events:
        print("No hay avisos en", args.archivo)
        return
    src = HyperliquidSource(cfg.network)
    start, end = events[0]["t"] - 30 * 60_000, int(time.time() * 1000)
    candles = {c: src.candles(c, "1m", start, end) for c in sorted({e["moneda"] for e in events})}
    typical = {c: typical_move(cs) for c, cs in candles.items()}
    print("\n".join(report(measure(events, candles), typical)))


def cmd_episodios(cfg: Config, args) -> None:
    from .episodios import build, default_files, report

    flows, bins = default_files(Path(args.datos))
    print("\n".join(report(build(flows, bins))))


def cmd_papel(cfg: Config, args) -> None:
    from .semaforo import load, scoreboard

    items = load(Path(args.archivo))
    print("\n".join(scoreboard(items)))
    for p in items[-args.last:]:
        print(f"  {p.id:38} {p.status:10} {p.side:5} entrada {p.entry:,.0f} stop {p.stop:,.0f} {p.r:+.2f}R "
              f"{'🚦' if p.filtro else '  '} {p.exit_reason} {p.note}")


def cmd_pesos(cfg: Config, args) -> None:
    from .pesos import compute, report, save

    d = Path(args.datos)
    flows = sorted(d.glob("hft_flujo*.csv"))
    w = compute(flows, [d / "binance_minuto.csv"], d / "hft_eventos.jsonl")
    print("\n".join(report(w)))
    if args.guardar:
        save(w)


def cmd_causa(cfg: Config, args) -> None:
    from .causa import NQ_FILE, btc_series, episodes, read_series, report

    btc = btc_series()
    nq = read_series(Path(args.nasdaq) if args.nasdaq else NQ_FILE, "indice", "NASDAQ")
    print(f"BTC: {len(btc):,} minutos · Nasdaq: {len(nq):,} minutos\n")
    print("\n".join(report(episodes(btc, nq, args.umbral / 100, args.ventana, args.antes))))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="copytrading", description="Copy trading on-chain")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover", help="buscar y puntuar traders rentables")
    d.add_argument("--top", type=int, default=50, help="candidatos del leaderboard a analizar")
    d.add_argument("--select", type=int, default=5, help="cuántos líderes sugerir")

    b = sub.add_parser("backtest", help="simular la copia de un líder")
    b.add_argument("--address")
    b.add_argument("--days", type=int, default=30)
    b.add_argument("--latency-ms", type=int, default=3_000)
    b.add_argument("--latency-bps", type=float, default=5.0)

    r = sub.add_parser("run", help="copiar en vivo (paper por defecto)")
    r.add_argument("--live", action="store_true", help="enviar órdenes reales")
    r.add_argument("--iterations", type=int, default=None)

    q = sub.add_parser("liquidity", help="mapa de liquidaciones (zonas roja/amarilla/verde)")
    q.add_argument("--coin", default="BTC", help="una o varias, separadas por coma: BTC,ETH,SOL")
    q.add_argument("--wallets", type=int, default=500, help="cuentas más grandes a escanear")
    q.add_argument("--range", type=float, default=15.0, help="rango alrededor del precio, en %%")
    q.add_argument("--band", type=float, default=0.5, help="ancho de cada franja, en %%")
    q.add_argument("--html-dir", help="carpeta donde guardar el reporte HTML del día")

    m = sub.add_parser("metodo", help="backtest del método canales + absorción de liquidez")
    m.add_argument("--coin", default="BTC")
    m.add_argument("--interval", default="4h", help="1h, 4h, 1d...")
    m.add_argument("--days", type=int, default=1200)
    m.add_argument("--lookback", type=int, default=60, help="velas para trazar el canal")
    m.add_argument("--entry", choices=["sweep", "target"], default="sweep")
    m.add_argument("--stop", choices=["close", "wick"], default="close")
    m.add_argument("--trend", choices=["none", "channel"], default="channel")
    m.add_argument("--sweep", type=float, default=1.5, help="liquidez absorbida mínima")
    m.add_argument("--channel", choices=["regression", "pivots"], default="regression")
    m.add_argument("--pivot-k", type=int, default=3, help="velas a cada lado para un pivote")
    m.add_argument("--ema", default="1d:50,1d:200", help="EMAs, p. ej. 1d:50,1d:200")
    m.add_argument("--ema-mode", choices=["none", "confluence", "filter"], default="filter",
                   help="filter: largos sobre la 1ª EMA, cortos bajo ella; confluence: tocar una EMA")
    m.add_argument("--last", type=int, default=10, help="últimas operaciones a mostrar")

    po = sub.add_parser("pools", help="estudio de pools: carga, liquidación, rebotes, trampas, imán")
    po.add_argument("--coins", default="BTC,ETH,SOL")
    po.add_argument("--interval", choices=["1h", "4h"], default="1h")
    po.add_argument("--days", type=int, default=830)

    hf = sub.add_parser("hft", help="radar de alta frecuencia: robots del ranking y su tipo")
    hf.add_argument("--top", type=int, default=25)
    hf.add_argument("--out", default="data/alta_frecuencia.json")
    hf.add_argument("--detalle", action="store_true", help="mostrar cada señal y lo que no cumple")

    me = sub.add_parser("memoria", help="memoria de patrones: qué patrones medidos están activos y casos parecidos")
    me.add_argument("--coins", default="BTC,ETH")

    bw = sub.add_parser("ballena", help="historial de las ballenas seguidas (indicador contrario)")
    bw.add_argument("--address", help="otra dirección (por defecto, las de data/ballenas_seguidas.json)")
    bw.add_argument("--days", type=int, default=60)

    mo = sub.add_parser("monitor", help="revisar el método en vivo y actualizar el diario")
    mo.add_argument("--coins", default="BTC,ETH,SOL")
    mo.add_argument("--journal", default="data/diario.jsonl")
    mo.add_argument("--notify", action="store_true", help="enviar aviso al móvil si hay novedades")
    mo.add_argument("--alert-hours", type=float, default=4.5,
                    help="avisar solo de cambios de planes ocurridos en estas últimas horas")
    mo.add_argument("--ntfy-topic", help="tema de ntfy (o variable NTFY_TOPIC)")
    mo.add_argument("--whales", type=int, default=500,
                    help="cuentas más grandes de Hyperliquid a revisar para liquidaciones reales (0 = no)")
    mo.add_argument("--days", type=int, default=830,
                    help="histórico (la EMA 200 diaria necesita mucho para estabilizarse)")

    tr = sub.add_parser("trampas", help="estudio de rupturas falsas frente a reales")
    tr.add_argument("--coins", default="BTC,ETH,SOL")
    tr.add_argument("--interval", choices=["1h", "4h"], default="1h")
    tr.add_argument("--days", type=int, default=830)

    sub.add_parser("billeteras", help="indicador de billeteras: tendencia y corto plazo")

    rn = sub.add_parser("rendimiento", help="¿las cuentas en estudio ganan o solo mueven dinero? (revisión mensual)")
    rn.add_argument("--desde", help="inicio del estudio AAAA-MM-DD (por defecto, el de la cohorte)")
    rn.add_argument("--no-guardar", action="store_true", help="no añadir la consulta a data/hft_rendimiento.jsonl")

    av = sub.add_parser("avisos", help="¿aciertan los avisos de la escucha? precio 15 y 60 min después")
    av.add_argument("--archivo", default="data/hft_eventos.jsonl")

    ep = sub.add_parser("episodios", help="qué hacen las cuentas antes de caídas, subidas y rupturas de compresión")
    ep.add_argument("--datos", default="data", help="carpeta con los CSV de la escucha (y escucha_pc/)")

    pa = sub.add_parser("papel", help="cuenta de papel del semáforo: resultado por setup, con y sin filtro")
    pa.add_argument("--archivo", default="data/papel.jsonl")
    pa.add_argument("--last", type=int, default=15)

    pw = sub.add_parser("pesos", help="acierto medido de cada voto de la confirmación y su peso")
    pw.add_argument("--datos", default="data", help="carpeta con hft_flujo*.csv, binance_minuto.csv y hft_eventos.jsonl")
    pw.add_argument("--guardar", action="store_true", help="guardar en data/pesos.json")

    ca = sub.add_parser("causa", help="¿la bolsa o la disculpa? movimientos fuertes de BTC frente al Nasdaq")
    ca.add_argument("--umbral", type=float, default=1.5, help="movimiento mínimo de BTC, en %%")
    ca.add_argument("--ventana", type=int, default=60, help="en menos de estos minutos")
    ca.add_argument("--antes", type=int, default=30, help="minutos previos en que se mira el Nasdaq")
    ca.add_argument("--nasdaq", help="CSV del Nasdaq (por defecto data/nasdaq_minuto.csv)")

    ap = sub.add_parser("aviso-prueba", help="enviar una alerta de prueba al móvil")
    ap.add_argument("--ntfy-topic", help="tema de ntfy (o variable NTFY_TOPIC)")

    di = sub.add_parser("diario", help="apuntar lecturas manuales y ver resultados")
    di.add_argument("accion", choices=["add", "plan", "report"])
    di.add_argument("--journal", default="data/diario.jsonl")
    di.add_argument("--coin", default="BTC")
    di.add_argument("--side", choices=["long", "short"])
    di.add_argument("--entry", type=float)
    di.add_argument("--stop", type=float)
    di.add_argument("--tp1", type=float)
    di.add_argument("--tp2", type=float, default=0.0,
                    help="segundo objetivo; 0 (por defecto) = asegurar en TP1 y dejar correr con stop móvil")
    di.add_argument("--nota", default="")
    di.add_argument("--trigger", type=float, help="plan: nivel de activación")
    di.add_argument("--trigger-dir", choices=["below", "above", "touch_below", "touch_above"],
                    help="plan: cierre por debajo/encima, o toque (orden límite)")
    di.add_argument("--horas", type=float, default=48, help="plan: caduca tras estas horas")
    di.add_argument("--intervalo", choices=["15m", "1h", "4h"], default="1h",
                    help="plan: vela que activa el plan (15m si el barrido es rápido)")
    di.add_argument("--barrido", type=float, help="plan: el precio debe tocar antes este nivel (trampa)")
    di.add_argument("--desde", help="plan: válido desde 'AAAA-MM-DD HH:MM' hora Colombia")
    di.add_argument("--last", type=int, default=20)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.load(args.config) if Path(args.config).exists() else Config()
    {"discover": cmd_discover, "backtest": cmd_backtest, "run": cmd_run,
     "liquidity": cmd_liquidity, "metodo": cmd_metodo,
     "monitor": cmd_monitor, "diario": cmd_diario, "pools": cmd_pools,
     "aviso-prueba": cmd_aviso_prueba, "billeteras": cmd_billeteras, "ballena": cmd_ballena, "hft": cmd_hft, "memoria": cmd_memoria,
     "trampas": cmd_trampas, "causa": cmd_causa, "rendimiento": cmd_rendimiento, "avisos": cmd_avisos, "episodios": cmd_episodios, "papel": cmd_papel, "pesos": cmd_pesos}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
