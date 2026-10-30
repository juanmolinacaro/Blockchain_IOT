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

## Versión 2: canales por pivotes + EMA diaria (30 oct 2026)

* **Las EMAs de Juan**: su línea roja diaria (76.438) es la **EMA 200 diaria** (calculada: 76.437)
  y la verde (~80.400) es la **EMA 50 diaria**.
* **Canales por pivotes** (`--channel pivots`): línea superior por los dos últimos máximos
  confirmados y línea inferior por los dos últimos mínimos (salen canales, triángulos y cuñas);
  un canal deja de valer cuando un cierre queda claramente fuera.
* **EMA**: `confluence` = la vela de entrada además toca la EMA y cierra del lado correcto;
  `filter` = largos solo por encima de la EMA y cortos solo por debajo.

Resultado agregado (BTC + ETH + SOL, entrenamiento + validación = 6 tramos, 4H, stop por cierre):

| Variante | Trades | Expectativa | Tramos positivos |
|---|---|---|---|
| Regresión + liquidez + **confluencia EMA 50d** | 27 | **+0,68 R** | 5/6 |
| Regresión + liquidez + **filtro EMA 200d** | 74 | **+0,33 R** | 4/6 |
| Regresión + liquidez (sin EMA) | 173 | +0,15 R | 4/6 |
| Regresión sin liquidez ni EMA | 618 | −0,14 R | 2/6 |
| Pivotes k3 + liquidez (sin EMA) | 89 | −0,12 R | 2/6 |
| Pivotes k5 sin liquidez | 323 | −0,24 R | 0/6 |

Conclusiones:

1. **La EMA diaria suma**: con liquidez, la confluencia con la EMA 50d o el filtro de la EMA 200d
   mejoran a la versión sin EMA. Las tres capas juntas (canal + liquidez + EMA) dan lo mejor.
2. **Los toques de la EMA 200 diaria son raros**: en 2,3 años de 4H casi no hay casos con canal +
   liquidez + EMA 200 a la vez (2–4), así que el setup actual de BTC no se puede validar con
   estadística; habrá que seguirlo en vivo.
3. **Los pivotes automáticos funcionan peor que la regresión**: los canales que traza Juan a mano
   eligen los giros relevantes en varias temporalidades, y eso el algoritmo aún no lo replica.
4. **Cuidado con el sobreajuste**: se probaron 36 combinaciones; la mejor puede serlo en parte por
   suerte. Las muestras son pequeñas (27–74 trades). El siguiente paso es validarla hacia delante
   (paper trading / diario de señales) antes de usar dinero.
5. BTC sigue siendo la moneda más débil en todas las variantes.
