"""Línea de comandos.

    python -m copytrading discover  --config config.toml
    python -m copytrading backtest  --config config.toml --address 0x...
    python -m copytrading run       --config config.toml [--live]
    python -m copytrading liquidity --coin BTC [--html-dir reportes]
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

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.load(args.config)
    {"discover": cmd_discover, "backtest": cmd_backtest, "run": cmd_run,
     "liquidity": cmd_liquidity}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
