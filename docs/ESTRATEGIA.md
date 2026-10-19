# Estrategia de copy trading on-chain

## 1. Idea

En una blockchain cualquier wallet es pública: sus entradas, salidas, tamaño y
PnL quedan registrados. La estrategia consiste en:

1. **Descubrir** wallets con rentabilidad consistente y *copiable*.
2. **Validar** con un backtest que la copia sigue siendo rentable tras latencia y comisiones.
3. **Replicar** en tiempo real sus entradas y salidas, escaladas a nuestro capital.
4. **Proteger** el capital con límites de riesgo propios, independientes del líder.

## 2. ¿Por qué Hyperliquid primero?

| Criterio | Hyperliquid (perps L1) | DEX spot en EVM/Solana |
|---|---|---|
| Posiciones y PnL de cualquier wallet | API pública, exactos | Hay que reconstruirlos a partir de swaps |
| Latencia para copiar | ~1 s de bloque, sin mempool pública | Expuesto a MEV y sandwich |
| Entradas **y salidas** claras | Sí (`Open Long`, `Close Long`...) | Ambiguo (transferencias, varias wallets) |
| Long **y** short | Sí | Normalmente solo long |
| Coste | ~4.5 bps taker | Fees del pool + gas + slippage |

La fuente de datos está detrás de la interfaz `copytrading/sources/base.py`, así
que se puede añadir un adaptador para Base, Ethereum o Solana más adelante.

## 3. Selección de traders (`scoring.py`)

El PnL del leaderboard engaña. Muchos "top traders" son:

* **suerte**: un único trade enorme → filtro `max_top_trade_share`;
* **apalancamiento extremo**: ganan mucho hasta que se liquidan → filtro `max_drawdown`;
* **market makers / bots HFT**: ganan con spread y rebates, imposibles de copiar → filtros
  `max_trades_per_day`, `min_avg_hold_minutes` y volumen/equity en el prefiltro;
* **cuentas inactivas**: rentables en el pasado → filtro `max_days_since_last_trade`.

Pasos:

1. **Prefiltro barato** sobre el leaderboard: equity mínima, PnL mensual y total
   positivos, sin caídas fuertes esta semana y sin volumen de market maker.
2. **Análisis profundo** de los fills de los últimos `lookback_days`:
   las operaciones se agrupan en *round trips* (de posición 0 a 0) y se calculan
   win rate, profit factor, Sharpe diario, max drawdown, tiempo medio de holding,
   concentración del PnL y frecuencia.
3. **Puntuación compuesta** (0–1): 35 % Sharpe, 20 % profit factor, 15 % win rate,
   15 % bajo drawdown y 15 % ROI. Prioriza la *consistencia* sobre el PnL bruto.

## 4. Backtest de copia (`backtest.py`)

Para cada líder candidato se reproduce su historial como si lo hubiéramos copiado:

* cada fill del líder se ejecuta `latency_ms` después, con `latency_slippage_bps` de
  precio peor;
* tamaño = posición del líder × (mi equity / equity del líder) × `size_multiplier`;
* comisiones taker, tamaño mínimo de orden y límite por moneda;
* no se copian posiciones que el líder ya tenía abiertas al inicio de la ventana.

Métrica clave: el **capture ratio** = mi rentabilidad / rentabilidad del líder.
Un trader que gana un 50 % pero con capture ratio 0.1 no sirve: su ventaja
desaparece con la latencia. Busca **capture ratio > 0.6**.

## 5. Replicación en vivo (`replicator.py`)

Se replica el **estado** (posición objetivo), no cada fill:

```
objetivo[moneda] = Σ_líderes  posición_líder × (mi_equity × peso_líder / equity_líder) × multiplicador
```

En cada ciclo (`poll_seconds`) se compara el objetivo con mi posición actual y se
envía la diferencia. Así:

* **Entrada**: el líder abre → mi objetivo pasa de 0 a X → compro/vendo X.
* **Salida**: el líder cierra → mi objetivo pasa a 0 → cierre *reduce-only*.
* **Parciales y volteos** (long→short) se gestionan solos.
* Si se pierde un evento por un fallo de red, el siguiente ciclo converge igual.

Protecciones:

| Regla | Parámetro | Para qué |
|---|---|---|
| No entrar en posiciones viejas del líder | `copy_existing_positions = false` | Evita entrar tarde a mal precio |
| No perseguir el precio | `max_entry_deviation_pct` | Si el precio ya se movió >1 % a favor del líder, no se entra |
| Tamaño máximo por moneda | `max_position_pct` | Diversificación |
| Apalancamiento total máximo | `max_leverage` | Limita la exposición bruta |
| Stop-loss propio | `stop_loss_pct` | Si el líder aguanta una pérdida, nosotros no; no se re-entra hasta que él cierre |
| Kill-switch diario | `daily_loss_limit_pct` | Cierra todo y detiene la copia hasta el día siguiente |
| Umbral de rebalanceo | `rebalance_threshold_pct` | Evita comisiones por ajustes mínimos |
| Lista de monedas | `allowed_coins` / `blocked_coins` | Evita memecoins ilíquidas |

## 6. Flujo de trabajo recomendado

```bash
pip install -r requirements.txt
cp config.example.toml config.toml

# 1. Buscar candidatos
python -m copytrading discover --top 50 --select 5 -v

# 2. Validar cada uno (pega las direcciones en config.toml)
python -m copytrading backtest --days 30 --latency-ms 3000

# 3. Paper trading durante 2–4 semanas
python -m copytrading run

# 4. Solo si el paper trading confirma el backtest: real, con poco capital
pip install hyperliquid-python-sdk
export HL_SECRET_KEY=0x...   # clave de una API wallet (no puede retirar fondos)
# en config.toml: mode = "live"; prueba antes con network = "testnet"
python -m copytrading run --live
```

Revisa los líderes cada semana: vuelve a ejecutar `discover` y retira a los que
dejen de cumplir los filtros (la rentabilidad pasada se degrada).

## 7. Riesgos (léelo antes de usar dinero real)

* **Rentabilidad pasada ≠ futura.** Elegir los mejores del leaderboard tiene
  *sesgo de supervivencia*: muchos perdieron después.
* **Latencia y slippage**: siempre entras peor que el líder. En activos ilíquidos
  la diferencia puede comerse toda la ventaja.
* **El líder puede cubrirse en otra wallet o exchange**: puede que veas solo una
  pata de su estrategia. Su "short" puede ser una cobertura, no una apuesta.
* **Front-running inverso**: algunas wallets conocidas saben que se las copia y
  pueden usarlo en tu contra.
* **Riesgo técnico**: bugs, caídas de la API y órdenes parcialmente ejecutadas.
  Empieza siempre en paper/testnet.
* **Liquidación**: con apalancamiento puedes perder todo el margen. Mantén
  `max_leverage` bajo.

Este código es una herramienta de investigación y no es asesoramiento financiero.
No garantiza ganancias.
