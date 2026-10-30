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

## Monitor en vivo y diario de señales

```bash
python -m copytrading monitor                  # revisa BTC, ETH y SOL con la última vela de 4H cerrada
python -m copytrading diario add --coin BTC --side long --entry 77000 --stop 75800 \
       --tp1 79100 --tp2 80400 --nota "EMA 200 diaria + parte baja del canal"
python -m copytrading diario report            # resultados: sistema-A, sistema-B y juan
```

* **SEÑAL** 🚨: se cumplen todas las reglas en la última vela cerrada.
  * `sistema-A` = canal + liquidez + confluencia con la EMA 50/200 diaria.
  * `sistema-B` = canal + liquidez + filtro de la EMA 200 diaria.
* **VIGILAR** 👀: el precio está a menos de 1,5 % de un borde del canal que coincide con una EMA
  diaria o con liquidez fuerte justo detrás.
* Cada señal (y cada lectura manual de Juan) se guarda en `data/diario.jsonl` y su resultado se
  actualiza solo en cada ejecución, con la misma gestión que el backtest (TP1 en el centro del
  canal con stop a la entrada, TP2, stop por cierre). Así, con las semanas, se compara el
  porcentaje de aciertos del sistema con el de las lecturas de Juan.

## Estudio de pools: carga, liquidación, rebote, trampas e imán (30 oct 2026)

Comando: `python -m copytrading pools --coins BTC,ETH,SOL --interval 1h` (o `4h`).

Pool = pico de concentración del mapa estimado (una "franja roja"): ≥ 2,5x la densidad mediana,
ancho máximo ±0,75 %, tamaño ≥ 5 velas de volumen. Liquidado = el precio llega a su centro.
Datos: BTC + ETH + SOL, 1H (7 meses, 399 pools) y 4H (2,3 años, 597 pools).

| Pregunta | 1H | 4H |
|---|---|---|
| Tiempo de carga (edad media de la liquidez al volverse relevante) | mediana 62 h (27–167) | mediana 120 h (83–170) |
| Tiempo hasta la liquidación (mediana) | 62 h | 152 h |
| Pools a < 2 % del precio que se liquidan | 74 % | 87 % |
| Pools a > 4 % que se liquidan | 31 % | 63 % |
| Rebote mediano tras el barrido (24 h / 72 h) | 2,2 % / 3,2 % | 2,2 % / 3,4 % |
| Rebote ≥ 2 % en 24 h | 55 % | 55 % |
| Cuánto se pasa del centro antes de girar (mediana, 24 h) | 2,1 % | 2,4 % |
| Rebote si la vela del barrido **cierra de vuelta** (rechazo) | 2,5 % (59 % ≥ 2 %) | **2,9 % (67 % ≥ 2 %)** |
| Rebote si cierra más allá | 2,0 % (49 %) | 1,2 % (41 %) |
| Toca antes el pool más cercano | 78 % | 74 % |
| Toca antes el pool más grande | 60 % | 61 % |
| **Con un pool ≥ 2x mayor que el otro, va primero al grande** | **66 %** | **88 %** |
| Si el grande está más lejos (sin exigir 2x), va primero al grande | 26 % | 35 % |

Reglas que salen de los datos:

1. **Confirmación por cierre**: el rebote es mucho mejor cuando la vela que barre el pool cierra de
   vuelta (4H: 2,9 % frente a 1,2 %). Entrar solo tras ese cierre.
2. **Stop fuera del pool, no dentro**: el precio se pasa de mediana un 2–2,5 % del centro del pool
   antes de girar. Un stop ajustado dentro de esa distancia se lo lleva el barrido.
3. **El imán funciona cuando un lado domina claramente**: con un pool ≥ 2x mayor, el precio va
   primero a él 2 de cada 3 veces (1H) y 9 de cada 10 (4H). Si los pools son parecidos, manda la
   distancia: va antes al más cercano (~75 %).
4. **Paciencia medida**: un pool tarda de mediana 2,5–5 días en cargarse y otros 2,5–6 días en
   liquidarse. Los cercanos (< 2 %) casi siempre se liquidan; los lejanos (> 4 %), menos de la mitad.
5. **Trampas**: en 1H, el 72 % de los barridos tuvo antes una absorción fuerte al lado contrario y
   esos barridos rebotan algo mejor (2,5 % frente a 2,0 %). Pero la trampa así definida (una vela
   que absorbe liquidez contraria y cierra en contra) **todavía no sirve para anticipar** el barrido:
   pocos casos (7) y no mejora a la base. Falta definirla como la ve Juan: dos o más empujes fuertes
   al lado contrario que fallan (máximos que no continúan) justo antes de ir a por el pool grande.

El monitor ahora indica en cada aviso los pools más cercanos y si hay un imán dominante.

## Alertas al móvil

Las notificaciones de la plataforma (push/correo de las tareas programadas) no llegaban, así que
el monitor envía sus propias alertas con **ntfy** (app gratuita, sin cuenta):

* App ntfy (Philipp Heckel) suscrita al tema privado de Juan (no se publica aquí).
* `python -m copytrading monitor --notify --ntfy-topic <tema>` avisa solo si hay novedades:
  🚨 SEÑAL (prioridad urgente), ✅ operación cerrada, 👀 VIGILAR.
* `python -m copytrading aviso-prueba --ntfy-topic <tema>` envía una prueba.
* La tarea programada corre cada 4 h (00:05, 04:05, … UTC) y requiere `ntfy.sh` en los dominios
  permitidos del entorno. Alternativa: Telegram (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).
* Verificado el 30 oct 2026: la alerta llegó al móvil.

## Billeteras validadas: quién compró el suelo y vendió el techo (30 oct 2026)

Idea de Juan: en vez de fiarse del PnL del mes (en un mes bajista premia a cualquiera que estuviera
corto), marcar suelos y techos reales y buscar las billeteras que compraron en unos y vendieron en
otros. Código: `copytrading/smartwallets.py`. Lista: `data/ballenas.json`.

* Candidatos: 1.500 traders de swing (ganancias históricas, poco volumen respecto a su capital) +
  1.200 de mayor PnL. Hyperliquid solo guarda las 10.000 operaciones más recientes de cada cuenta,
  así que los bots/market makers no tienen historial hasta julio (de todos modos no interesan).
* 281 billeteras operaron BTC/ETH en el periodo; 115 con historial hasta el suelo de julio.
* Suelo 1 jul (57.768) + techo 21 sep–6 oct (87.471): **11 "maestras"** (compraron y vendieron).
  Las 4 más grandes compraron ~11,8M cada una a 58.600–59.600, mantuvieron y vendieron 19–35M a
  86.900–87.400. Dos de ellas son gemelas (mismo operador probable).
* Con 6 giros (3 suelos, 3 techos): nadie acierta más de 3; 11 billeteras aciertan 3, casi todas
  pequeñas. Las grandes aciertan el giro principal (2/6): son de mantener posición, no de cazar
  cada giro.

Posición actual de las maestras grandes: **largos** (BTC 47M @82.098; ETH ~76M @2.420–2.719, en
pérdidas) frente a un **corto** grande (BTC 63M @79.051). Es decir, **no hay consenso bajista**
entre las validadas, al contrario que el "dinero inteligente por PnL del mes" (12:1 corto): el
filtro de Juan elimina ese sesgo.

### Validación con 8 giros y prueba contra el azar (30 oct 2026)

Juan añadió el techo de mayo (6 may, 82.799) y el suelo de junio (5 jun, 59.100). Con 8 giros de
BTC (4 techos y 4 suelos, mayo–octubre) y 211 billeteras de swing (75 con historial hasta mayo):

* **Acierto** = compra neta en suelo / venta neta en techo (≥ 50k USD, cerca del extremo).
  **Error** = lo contrario (vender en suelo o comprar en techo).
* Nadie acierta más de 4 de 8. **11 billeteras** tienen aciertos − errores ≥ 3.
* **Prueba contra el azar**: con 8 fechas aleatorias (200 repeticiones), la mediana es 1 billetera
  con neto ≥ 3 y el máximo 6. Con los giros reales salen 11 → **0 de 200** veces el azar iguala lo
  real: hay habilidad real de timing en este grupo, no solo suerte.
* Son cuentas pequeñas o medianas (30k–1,1M USD): traders de swing con buen timing, no ballenas.
* Posición al 30 oct (BTC 78.300): 4 cortos (5,4M) frente a 3 largos (2,5M), 4 sin posición.
  Los largos entraron cerca del suelo de ayer (76.939 y 78.114, EMA 200 diaria).

Lista en `data/ballenas.json` → `nivel_1_validadas_8_giros` (las del timing) y
`nivel_2_maestras_grandes` (las que compraron el suelo de julio y vendieron el techo con tamaño).

### ETH: 6 giros marcados por Juan (30 oct 2026)

Compras: 6 jun (1.504), 26 jun (1.511), acumulación 25 jul–18 ago (1.821). Ventas: 21–31 ago
(2.566), 3–14 sep (2.666), 18 sep–2 oct (2.810).

* 2 billeteras con neto ≥ 3 en ETH; con fechas al azar, mediana 0 y máximo 3 (26 de 200 veces el
  azar iguala o supera) → en ETH **la evidencia es débil** (pocos giros y pocas billeteras con
  historial suficiente). En BTC sí fue clara.
* Destaca `0x6ea486…`: 4 aciertos y 0 errores en ETH; hoy **corto en ETH 9,4M desde 2.602**
  (vendió cerca del techo y mantiene).
* Combinando BTC + ETH se repiten `0x92ae42…`, `0x6041f8…`, `0xbe4e91…`, `0xf89993…`,
  `0x9a9917…`: la mayoría hoy cortas (en BTC y ETH) o sin posición.
