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
    for coin in [c.strip().upper() for c in args.coins.split(",")]:
        candles = closed_candles(src.candles(coin, "4h", now - args.days * MS_PER_DAY, now), "4h", now)
        if len(candles) < 300:
            print(f"{coin}: pocas velas ({len(candles)})")
            continue
        st = analyze(coin, candles)
        icon = {"SEÑAL": "🚨", "VIGILAR": "👀"}.get(st.status, "·")
        print(f"\n{icon} {coin} {st.status} — {st.price:,.1f} (vela {_fmt_time(st.time)})")
        for n in st.notes:
            print(f"   {n}")
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
            if e.coin == coin and e.interval == "4h":
                before = e.status
                update_outcome(e, candles)
                if before == "abierta" and e.status == "cerrada":
                    alerts.append(f"{e.coin} {e.source} cerrada {e.r:+.2f}R ({e.exit_reason})")
                    details.append(f"✅ {e.coin} {e.source} cerrada {e.r:+.2f}R ({e.exit_reason})")
                    levels.add("CERRADA")
    # planes y operaciones en 1H (lecturas de Juan): se siguen con velas de 1H
    for coin in sorted({e.coin for e in entries if e.interval == "1h" and e.status in ("pendiente", "abierta")}):
        c1 = closed_candles(src.candles(coin, "1h", now - 30 * MS_PER_DAY, now), "1h", now)
        for e in entries:
            if e.coin != coin or e.interval != "1h" or e.status not in ("pendiente", "abierta"):
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
    print("\nDiario (" + str(journal) + "):")
    for line in summary(entries):
        print("   " + line)
    print("\nRESUMEN: " + ("; ".join(alerts) if alerts else "sin novedades"))
    if args.notify and alerts:
        from .notify import send_alert
        level = next(lv for lv in ("SEÑAL", "CERRADA", "VIGILAR") if lv in levels)
        icon = {"SEÑAL": "🚨", "CERRADA": "✅", "VIGILAR": "👀"}[level]
        title = f"{icon} {level}: " + "; ".join(alerts)
        body = "\n".join(details + ["", "Diario:"] + summary(entries)
                         + ["", "Información para decidir, no una orden de operar."])
        sent = send_alert(title[:120], body, level, ntfy_topic=args.ntfy_topic)
        print("AVISO: " + (f"enviado por {', '.join(sent)}" if sent else "NO enviado (revisa el canal)"))


def cmd_aviso_prueba(cfg: Config, args) -> None:
    from .notify import send_alert

    sent = send_alert("🧪 Prueba del monitor de trading",
                      "Si ves esto en el móvil, las alertas de BTC, ETH y SOL te llegarán aquí.",
                      "PRUEBA", ntfy_topic=args.ntfy_topic)
    print(f"Enviado por: {', '.join(sent)}" if sent else "No se pudo enviar por ningún canal")
    if not sent:
        raise SystemExit(1)


def cmd_diario(cfg: Config, args) -> None:
    from .method.monitor import load_journal, manual_entry, save_journal, summary

    journal = Path(args.journal)
    entries = load_journal(journal)
    if args.accion == "plan":
        from .method.monitor import manual_plan
        e = manual_plan(args.coin.upper(), args.side, args.trigger, args.trigger_dir, args.stop,
                        args.tp1, args.tp2, args.horas, args.nota)
        entries.append(e)
        save_journal(journal, entries)
        cond = {"below": "cierre 1H por debajo de", "above": "cierre 1H por encima de",
                "touch_below": "el precio baja a", "touch_above": "el precio sube a"}[e.trigger_dir]
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

    mo = sub.add_parser("monitor", help="revisar el método en vivo y actualizar el diario")
    mo.add_argument("--coins", default="BTC,ETH,SOL")
    mo.add_argument("--journal", default="data/diario.jsonl")
    mo.add_argument("--notify", action="store_true", help="enviar aviso al móvil si hay novedades")
    mo.add_argument("--alert-hours", type=float, default=4.5,
                    help="avisar solo de cambios de planes ocurridos en estas últimas horas")
    mo.add_argument("--ntfy-topic", help="tema de ntfy (o variable NTFY_TOPIC)")
    mo.add_argument("--days", type=int, default=830,
                    help="histórico (la EMA 200 diaria necesita mucho para estabilizarse)")

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
    di.add_argument("--tp2", type=float)
    di.add_argument("--nota", default="")
    di.add_argument("--trigger", type=float, help="plan: nivel de activación")
    di.add_argument("--trigger-dir", choices=["below", "above", "touch_below", "touch_above"],
                    help="plan: cierre por debajo/encima, o toque (orden límite)")
    di.add_argument("--horas", type=float, default=48, help="plan: caduca tras estas horas")
    di.add_argument("--last", type=int, default=20)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.load(args.config) if Path(args.config).exists() else Config()
    {"discover": cmd_discover, "backtest": cmd_backtest, "run": cmd_run,
     "liquidity": cmd_liquidity, "metodo": cmd_metodo,
     "monitor": cmd_monitor, "diario": cmd_diario, "pools": cmd_pools,
     "aviso-prueba": cmd_aviso_prueba}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
