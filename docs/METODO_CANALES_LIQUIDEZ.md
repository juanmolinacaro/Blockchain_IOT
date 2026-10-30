# Método de Juan: canales + absorción de liquidez

Método de trading de Juan Molina, tal como lo explicó y aplicó en vivo sobre
BTC/USDT del 28 al 30 de octubre de 2026. Está escrito para poder programarlo y
medirlo con backtest.

## Principios

1. **El precio se mueve dentro de canales.** Se trazan los canales que forma el
   precio (alcistas, bajistas o triángulos) en 4H y 1D. Los extremos del canal son
   las zonas de reacción.
2. **El precio va a buscar la liquidez.** Las zonas de liquidaciones (mapa de
   calor rojo/amarillo/verde) funcionan como imanes. El precio "absorbe" esa
   liquidez antes de girarse.
3. **Una entrada es buena cuando coinciden las dos cosas:** un extremo del canal
   **y** una zona de liquidez. Si además coincide una EMA importante (p. ej. la
   EMA diaria), la zona es todavía más fuerte.
4. **La estructura manda sobre la dirección:** con máximos decrecientes, precio
   por debajo de las EMAs y rechazo en la parte alta del canal, el sesgo es
   bajista hasta que se demuestre lo contrario.
5. **Paciencia:** "solo es cuestión de tiempo". Si la estructura y la liquidez
   apuntan al mismo sitio, el precio termina llegando; no hace falta perseguirlo.

## Proceso

1. Revisar la estructura en 1D y 4H: canal vigente, máximos/mínimos, EMAs.
2. Revisar el mapa de liquidez del día: dónde están las zonas rojas arriba y abajo.
3. Marcar la zona objetivo donde coinciden extremo del canal + liquidez (+ EMA).
4. Operar a favor de la estructura hacia esa zona; buscar el giro en ella.

## Caso real: BTC, 28–30 de octubre de 2026

| Momento | Precio | Lectura de Juan | Resultado |
|---|---|---|---|
| 28 oct | ~80.500 | "Va a barrer los 79.100" (zona roja de longs, estructura bajista) | Rechazó en la EMA de 4H (~81.566) y bajó |
| 29 oct | ~81.000 | Estructura bajista clara desde hace días, imanes de longs abajo | Rompió el triángulo y barrió 79.134 (mínimo 78.548) |
| 29 oct | ~79.000 | Parte baja del canal + liquidez coinciden en ~77.000 | Llegó a **76.968** el 30 oct |
| 29 oct | — | En el diario irá a buscar la EMA (~76.400) para rebotar con fuerza | Pendiente |

Mapa real de Hyperliquid del 30 oct (BTC 77.188): longs en 74.900–75.300 (coincide
con el imán de 75.514 del mapa de TradingDifferent) y shorts nuevos en 78.000–79.100.

## Gestión acordada

- Entradas escalonadas en la zona de confluencia, no todo de golpe.
- Stop por cierre (4H o 1D) fuera de la zona, no por mecha, porque el precio
  suele perforar el canal para absorber la liquidez que hay justo debajo.
- Tomar ganancias por partes en las siguientes zonas de liquidez.

## Próximo paso

Programar el método (detección de canales + mapa de liquidez + confirmación) y
medir con el histórico qué porcentaje de veces funciona y con qué
relación beneficio/riesgo.

## Backtest (primera versión automática, 30 oct 2026)

Código: `copytrading/method/` · Comando: `python -m copytrading metodo --coin BTC --interval 4h`

Cómo se automatizó:

* **Canal**: regresión lineal de las últimas 60 velas de 4H; bordes donde quedan el 90 % de máximos/mínimos.
* **Liquidez**: mapa estimado (apalancamientos 10/25/50/100x proporcionales al volumen), porque
  no existe un histórico de posiciones reales. Un nivel cruzado por el precio cuenta como absorbido.
* **Entrada larga**: el mínimo toca el borde inferior + se absorbe liquidez de longs (≥ 1,5 velas
  de volumen) + la vela cierra dentro del canal. Corto simétrico. Filtro: largos solo con canal
  alcista, cortos solo con canal bajista.
* **Gestión**: stop por **cierre** bajo el mínimo de la vela (emergencia a 2R), mitad en el centro del
  canal y stop a la entrada, resto en el borde opuesto. Comisiones y slippage incluidos.
* Datos: ~2,3 años de velas de 4H de Hyperliquid (jul 2024 – oct 2026). 70 % para ajustar,
  30 % final para validar.

Resultados (expectativa en R por operación; validación = datos no usados para ajustar):

| Moneda | Canal + liquidez (validación) | Solo canal (validación) |
|---|---|---|
| BTC | 18 trades, 44 % aciertos, **−0,51 R** | 73 trades, −0,32 R |
| ETH | 21 trades, 57 % aciertos, **+0,87 R** | 65 trades, +0,12 R |
| SOL | 25 trades, 48 % aciertos, **+0,81 R** | 67 trades, +0,14 R |

Conclusiones:

1. **Añadir la liquidez mejora al canal solo** en casi todas las combinaciones: filtra muchas
   operaciones malas.
2. **El stop por cierre (regla de Juan) es mejor que el stop por mecha** en la mayoría de casos.
3. **Todavía no hay una ventaja estable demostrada**: positiva en ETH y SOL, negativa en BTC en el
   último tramo, y con pocas operaciones (18–25) el resultado tiene mucho ruido.
4. La versión automática no captura todo el método discrecional: canales trazados a mano desde
   pivotes, varias temporalidades a la vez y la EMA diaria como confluencia.

Siguientes pasos: canales por pivotes (como se trazan a mano), confluencia con la EMA diaria y
el mapa real de Hyperliquid, y un diario de las operaciones discrecionales de Juan para medir
su ventaja real con el tiempo.
