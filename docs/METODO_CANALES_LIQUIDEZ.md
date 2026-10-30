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
