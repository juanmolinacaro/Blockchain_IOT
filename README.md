# Blockchain_IOT

Formulario

## Copy trading on-chain (`copytrading/`)

Sigue a traders rentables usando datos on-chain y replica sus entradas y salidas
de forma automática. La primera fuente de datos es Hyperliquid.

* **discover**: busca y puntúa wallets rentables, consistentes y copiables.
* **backtest**: simula cuánto habrías ganado copiándolas (con latencia y comisiones).
* **run**: replica sus posiciones en tiempo real (paper trading por defecto).
* **liquidity**: mapa de liquidaciones real (zonas roja/amarilla/verde) para decidir entradas, stops y objetivos.

```bash
pip install -r requirements.txt
cp config.example.toml config.toml
python -m copytrading discover -v
python -m copytrading backtest --address 0x...
python -m copytrading run
python -m copytrading liquidity --coin BTC,ETH --html-dir reportes
```

Estrategia completa, parámetros y riesgos: [docs/ESTRATEGIA.md](docs/ESTRATEGIA.md).

Tests: `pip install pytest && python -m pytest`
