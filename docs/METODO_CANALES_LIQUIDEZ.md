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

### ETH 2025: 5 giros más (30 oct 2026)

Compras: 9 abr 2025 (1.382), may–jun 2025 (2.317), 22 jun 2025 (2.113). Ventas: 28 jul 2025
(3.946), ago–sep 2025 (4.960). 77 de las billeteras actuales tienen historial de 2025, pero **no hay
evidencia de habilidad** en esos giros (1 billetera con neto ≥ 2, igual que con fechas al azar): la
mayoría de las validadas en 2026 no operaba ETH entonces. Ranking total de 19 giros en
`data/ballenas.json` → `ranking_19_giros`. Destaca `0xdbd1ba…` (acierta en 2025 y 2026; hoy corto
en ETH desde 3.031).

Conclusión del filtro de billeteras: el núcleo fiable sigue siendo el grupo validado en BTC 2026
(prueba contra el azar clara); ETH aporta poco por sí solo.

### Giros automáticos en temporalidades bajas (30 oct 2026)

Propuesta de Juan: bajar de temporalidad para tener más giros. `swing_events()` detecta techos y
suelos con un zigzag en velas de 1H (BTC y ETH, 28 abr–12 oct 2026), ventana ±8 h, precio a menos
de un 2 % del extremo.

* Giros de 6 % (38 giros): 2 billeteras con aciertos − errores ≥ 5 (`0x585f4f…` 6/1,
  `0x63d417…` 5/0); desplazando los giros al azar, mediana 0 y máximo 2 → **señal moderada**.
* Giros de 4 % (130 giros): aparecen más aciertos pero también más errores; nadie supera
  claramente al azar. **Cuanto más pequeño el giro, más ruido**: el timing fiable está en giros
  medianos y grandes.
* Repiten en varios análisis: `0x8f8d2d…` (10/4 en giros de 4 % y acertó el corto ene–feb),
  `0x0423b4…`, `0x63d417…`.

## Indicador de billeteras (30 oct 2026)

Regla de Juan: las billeteras de **largo plazo** son un indicador de fondo; las de **corto plazo**
solo sirven para ver el movimiento inmediato.

* `data/indicador_billeteras.json`: `tendencia` (validadas en 8 giros de BTC, maestras grandes y
  las mejores en ETH; 17 grupos) y `corto_plazo` (giros del 6 % en 1H).
* Un voto por grupo (las gemelas cuentan como una). ALCISTA si (largos − cortos)/(con posición)
  ≥ +0,34; BAJISTA si ≤ −0,34; si no, MIXTO.
* Uso: **tendencia ALCISTA** → confirma estructura alcista y buscar largos a largo plazo;
  **BAJISTA** → los rebotes son tácticos; **MIXTO** → sin confirmación. El corto plazo no genera
  señales.
* Sale en cada ejecución del monitor y en cada aviso; `python -m copytrading billeteras` lo muestra
  a demanda.

## Fin de semana en BTC (30 oct 2026)

Intuición de Juan: el fin de semana (mercado tradicional cerrado) BTC hace rango o arma una
estructura para engañar. Medido con 119 fines de semana (velas de 4H, jul 2024 – oct 2026);
viernes = 00:00–20:00 UTC, fin de semana = viernes 20:00 – domingo 24:00 UTC.

| Dato | Valor |
|---|---|
| Rango mediano del viernes (20 h) | 3,45 % |
| Rango mediano de todo el fin de semana (52 h) | **2,98 %** (más comprimido) |
| Fines de semana que se quedan dentro del rango del viernes | 18 % |
| Rompen solo por arriba / solo por abajo / ambos | 47 / 45 / 6 |
| Rompe arriba y el lunes cierra de vuelta bajo el máximo del viernes (trampa) | **45 %** |
| Rompe abajo y el lunes cierra de vuelta sobre el mínimo del viernes (trampa) | **49 %** |
| El lunes revierte el movimiento del fin de semana | 56 % |
| Si el fin de semana se movió > 2 %, el lunes lo revierte | **60 %** |

Lectura: el fin de semana se mueve menos (rango), casi siempre rompe un lado del viernes, pero
**la mitad de esas rupturas son trampas** y los movimientos grandes del fin de semana se revierten
el lunes 6 de cada 10 veces. Regla: no perseguir rupturas de fin de semana; esperar el lunes o
operar el regreso al rango del viernes.

### Regla: BTC primero · horario del fin de semana (30 oct 2026)

* **Revisar siempre BTC antes que cualquier altcoin**: BTC mueve el mercado cripto (regla de Juan).
* Rango mediano de una vela de 4H de BTC (2,3 años): media 1,09 %. **Sábado: 0,54–0,68 %**
  (acumulación). **Domingo 20–24 h UTC (15–19 h Colombia): 1,42 %**, el tramo más volátil del fin
  de semana, seguido de lunes 00–04 h UTC (1,55 %).
* El pequeño rango del sábado se rompe ya el domingo antes de las 16 h UTC en el 85 % de los casos;
  el movimiento fuerte llega el domingo por la tarde/noche (apertura de los mercados tradicionales).
* Regla: no operar el ruido del sábado; esperar el cierre de la vela de 4H del domingo
  (00 h UTC, 19 h Colombia) para confirmar dirección, recordando que el lunes revierte el 60 % de
  los movimientos de fin de semana > 2 %.

## Reglas operativas (30 oct 2026)

1. **No perseguir el precio.** Se entra solo en las zonas preparadas (canal + liquidez + EMA) y con
   confirmación por cierre.
2. **BTC primero**: se revisa BTC antes que cualquier altcoin.
3. **Viernes y sábado no se opera.** Se sigue el mercado para tener contexto de cómo abrirá la
   semana. El monitor marca sus avisos como "📵 solo contexto".
4. **Domingo desde las 13:00 (Colombia)** se buscan operaciones: el tramo más volátil del fin de
   semana es de 15 a 19 h, cuando se mueve el precio antes de abrir los mercados tradicionales.
5. Las billeteras de tendencia confirman la dirección de fondo; las de corto plazo solo dan contexto.
6. Toda idea se apunta en el diario **antes** de que ocurra (nivel, dirección, stop, objetivos).

## Consolidación tras un movimiento fuerte (31 oct 2026)

Enseñanza de Juan: tras una caída o subida grande, el precio a veces consolida, en triángulo
(se comprime) o en canal. Medido en BTC + ETH + SOL (4H, 2,3 años): impulso = movimiento ≥ 6 % en
24 h; consolidación = las 36 h siguientes en un rango ≤ 60 % del impulso sin devolver más del 61,8 %;
ruptura = primer cierre de 4H fuera de ese rango en las 72 h siguientes.

| Dato | Valor |
|---|---|
| Impulsos ≥ 6 % en 24 h | 264 |
| Seguidos de consolidación estrecha | 42 (16 %): "no siempre, pero algunas veces" |
| La consolidación rompe **a favor del impulso** | **61 %** (sin consolidación, solo 43 %) |
| Triángulo (se comprime) | 83 % a favor (solo 6 casos) |
| Canal / rango | 57 % a favor (36 casos) |
| Recorrido mediano tras la ruptura (48 h) | 2,9 % ≈ 39 % del impulso |

Lectura: cuando tras un impulso el precio consolida en vez de devolverlo, lo más probable es que
siga en la dirección del impulso (continuación). El objetivo típico tras la ruptura es ~40 % del
impulso. Muestras pequeñas en triángulos y en caídas: tomarlo como inclinación, no como certeza.

## Trampas: rupturas falsas frente a reales (31 oct 2026)

Objetivo de Juan: descubrir las trampas del precio. Ruptura = cierre fuera del rango de las últimas
24 h; trampa = vuelve a cerrar dentro en las 6 h (1H) / 12 h (4H) siguientes. BTC + ETH + SOL.
Comando: `python -m copytrading trampas --interval 1h` (o `4h`).

| Rasgo de la vela de ruptura | 1H (679 rupturas) | 4H (1.874 rupturas) |
|---|---|---|
| **Todas** | 56 % trampas | 47 % trampas |
| Cierra **apenas fuera** (< 0,2 % del nivel) | **76 %** | **69 %** |
| Cierra **claramente fuera** (> 0,6 %) | **29 %** | **33 %** |
| Volumen bajo (tercio inferior) | 68 % | 55 % |
| Volumen alto (tercio superior) | 43 % | 33 % |
| Mecha larga en contra (> 40 % de la vela) | 66 % | 56 % |
| Cierre en el extremo de la vela (mecha < 15 %) | 47 % | 40 % |
| Fin de semana / entre semana | 50 % / 59 % | 51 % / 45 % |
| **Combinación trampa**: volumen bajo + mecha en contra > 30 % | **74 %** | **59 %** |
| **Combinación real**: volumen alto + cierre en el extremo + a favor de la EMA 50d | **32 %** | **27 %** |
| Tras una trampa, llega al otro extremo del rango | 20 % (24 h) | 44 % (4 días) |
| Recorrido mediano de una ruptura real | 2,0 % (24 h) | 3,8 % (4 días) |

Reglas para detectar trampas:

1. **La señal más fuerte es cuánto cierra fuera**: si la vela cierra apenas por encima/debajo del
   nivel (< 0,2 %), es trampa 7 de cada 10 veces. Exigir un cierre claro (≥ 0,5–0,6 %) más allá.
2. **Volumen**: ruptura con volumen bajo → sospechosa; con volumen alto → mucho más fiable.
3. **Mecha en contra**: si la vela de ruptura deja mecha larga de vuelta hacia el rango, es rechazo.
4. Con las tres señales malas a la vez, 3 de cada 4 rupturas fallan; con las buenas, 3 de cada 4
   aguantan.
5. **Operar la trampa**: cuando una ruptura de 4H falla y vuelve dentro, el precio cruza hasta el
   otro extremo del rango el 44 % de las veces: es una operación en sí misma.

Aplicación: los niveles de activación de los planes ya se colocan claramente fuera del rango (p. ej.
78.000 frente al techo del triángulo en ~77.300, +0,9 %), lo que filtra las rupturas débiles.

### Calificación de rupturas en vivo (1 nov 2026)

El monitor revisa en cada ejecución las rupturas del rango de 24 h (velas de 1H) de BTC, ETH y SOL y
las califica con las señales del estudio (validado sobre el histórico):

* 🪤 **Perfil de trampa** (cierre apenas fuera — señal doble —, volumen bajo, mecha en contra):
  76 % de las históricas fallaron.
* ✅ **Perfil real** (cierre claro fuera, volumen alto, cierre en el extremo, a favor de la EMA 50d,
  sin señales de trampa): 26 % fallaron.
* ⚖️ **Dudosa** (el resto): 52 % fallaron.
* 🪤 **Falló**: una ruptura reciente volvió a cerrar dentro del rango. No implica giro inmediato
  (solo ~20 % llega al otro extremo en 24 h en 1H; 44 % en 4H).

Volumen relativo de la vela de ruptura frente a la media de las 24 h previas: bajo < 1,73x,
alto > 3,13x (tercios del estudio). Los avisos entran en la notificación de ntfy; el fin de semana
llegan como "solo contexto".

### Hueco del CME el fin de semana (1 nov 2026)

El CME cierra el viernes (17:00 hora de Nueva York) y reabre el domingo (18:00 hora de Nueva York;
en invierno, 18:00 en Colombia). Si cripto se movió durante el fin de semana, queda un "hueco" entre
el cierre del viernes y la apertura. Medición en BTC 1H (Hyperliquid como referencia, últimos ~7
meses, fines de semana con hueco > 0,3 %; 23 casos):

| Se cierra el hueco (el precio vuelve al cierre del viernes) | BTC | Base: cualquier nivel a ~1,1 % |
|---|---|---|
| En 24 h | 61 % (hueco al alza: 65 %) | 48 % |
| En 3 días | 87 % (hueco al alza: 88 %) | 73 % |

Hay algo de ventaja sobre lo normal, pero con pocos casos: sirve como imán de contexto, no como
señal sola. En ETH el efecto es más débil (54 % en 24 h, 71 % en 3 días).

### ¿Se puede operar el rebote tras liquidar un pool? (2 nov 2026)

Idea de Juan: después de que el precio liquida el pool inferior, rebota más de un 2 % (ejemplo:
BTC 76.385 → 78.566, +2,86 % en 16 velas de 4H). Se probó como operación con reglas fijas, en BTC,
ETH y SOL, sin operar de viernes a domingo antes de las 13:00 (COT), comparando cada resultado con
entradas al azar del mismo tamaño de stop y objetivo.

| Regla | Ops | Aciertos | Media por op. | PF | 1.ª mitad / 2.ª mitad | Azar |
|---|---|---|---|---|---|---|
| 1H, entrar al cierre de la vela que barre (con rechazo), stop bajo la mecha, objetivo +2 % | 60 | 40 % | +0,13R | 1,22 | +0,09 / +0,18 | +0,03 |
| 4H, lo mismo | 144 | 44 % | −0,03R | 0,95 | −0,01 / −0,04 | −0,05 |
| 1H, esperar cierre por encima del máximo de la vela del barrido (≤ 24 h), objetivo +2 % | 50 | 54 % | −0,03R | 0,94 | −0,22 / +0,17 | −0,02 |
| **4H, esperar cierre por encima del máximo de la vela del barrido (≤ 48 h), stop bajo el mínimo del barrido, objetivo 2R** | **81** | **52 %** | **+0,13R** | **1,35** | **+0,15 / +0,12** | +0,03 |

Conclusiones:

* El rebote existe (mediana 2,2 % en 24 h), pero **ese 2 % se mide desde el fondo, y el fondo solo
  se conoce después**: antes de girar, el precio suele pasarse otro ~2 % del centro del pool. Entrar
  en la misma vela del barrido apenas deja ventaja.
* La versión que aguanta en las dos mitades del histórico es la **confirmada en 4H**: tras el
  barrido, esperar a que una vela de 4H cierre por encima del máximo de la vela que barrió (hasta
  48 h), entrar en ese cierre, stop por debajo del mínimo del barrido (−0,3 %) y objetivo 2R.
  Ventaja modesta (+0,13R por operación, ~3 al mes entre las tres monedas), no un sistema solo.
* En 1H el ruido se come la ventaja: mejor como alerta temprana que como gatillo.

### Aviso con imagen (2 nov 2026)

Pedido de Juan: el aviso de texto traía demasiados datos y porcentajes; sin ver el gráfico confunde.
Ahora, cuando hay novedades, llega **un aviso por moneda (BTC primero) con una imagen**:

* Arriba, un **semáforo**: ENTRADA (azul), VIGILAR (amarillo), CALMA (gris) o FIN DE SEMANA.
* **Qué pasó** (1–2 frases): "Rompió hacia abajo (77.231): parece TRAMPA", "Plan D ACTIVADO: venta
  en 77.077".
* **Qué vigilar**: los planes del diario en palabras ("Plan D en curso: stop 78.100 · objetivo
  74.800") y hacia dónde tira la liquidez.
* El **gráfico de 4H** (7 días) con el canal, la EMA 50 y 200 diaria, las zonas de más liquidez
  estimada (morado) y los niveles de los planes (amarillo = entrada, rojo = stop, verde = objetivo).

Canales: ntfy (imagen adjunta) y Telegram (foto con el texto; en iPhone muestra el banner). Si la
imagen falla, se manda el aviso de texto de antes. El servidor gratuito de ntfy.sh limita los
mensajes diarios por conexión; Telegram no tiene ese problema.

### El imán de 2x: ¿se puede operar? (3 nov 2026)

Pregunta de Juan: si con un pool ≥ 2 veces mayor que el del otro lado el precio va primero al
grande, ¿cómo usarlo a favor? Prueba: cada vez que los dos pools más cercanos (uno arriba, uno
abajo) cumplen la condición, entrar hacia el grande con objetivo en su centro. BTC + ETH + SOL, sin
solapar operaciones.

| 4H (2,3 años) | Ops | Aciertos | Media por op. | 1.ª mitad / 2.ª mitad |
|---|---|---|---|---|
| **Hacia el pool grande (≥ 2x), stop en el pool pequeño** | 25 | **80 %** | +0,27R | +0,30 / +0,25 |
| Hacia el pool grande (≥ 2x), stop a la mitad de la distancia al objetivo (2R) | 25 | 72 % | **+1,02R** | +1,22 / +0,83 |
| Hacia el pool pequeño (en contra del imán) | 11 | 36 % | −0,34R | −0,71 / −0,04 |
| Pools parecidos (< 1,5x), hacia el mayor | 154 | 55–57 % | +0,07 a +0,23R | flojo |

En 1H el efecto es más débil y solo aparece con pools ≥ 3x (20 ops, +0,30R con stop en el pool
pequeño).

Cómo usarlo:

1. **Filtro de dirección**: con un imán ≥ 2x en 4H, operar solo hacia él. Ir en contra perdió.
2. **Objetivo natural**: el centro del pool grande es el objetivo (TP).
3. **Es poco frecuente** (~25 veces en 2,3 años entre las tres monedas, aprox. una al mes): cuando
   aparece, la imagen del monitor lo marca como "IMÁN FUERTE" y el semáforo pasa a VIGILAR.
4. Muestra pequeña: 25 casos. Tomarlo como ventaja a confirmar con el diario, no como certeza.

### Capas nuevas del mapa (3 nov 2026)

* **Corto plazo (lila)**: posiciones de 25x–100x abiertas en los últimos días (velas de 1H, vida
  media de 24 h). Captura los cortos/largos apalancados recientes que el mapa de 4H no ve.
  Validación: marcó cortos en 78.114 / 78.309 frente a 78.137 / 78.353 de La Ruta del Precio, y
  largos en 75.431–76.188 frente a su bloque 75.000–76.270.
* **Ballenas (naranja)**: liquidaciones REALES de las 500 cuentas más grandes de Hyperliquid (cada
  posición publica su precio de liquidación). El 3 nov: una ballena con $40M de largos que se
  liquida en ~75.800 (dentro del bloque grande de BTC) y otra con $33M en ~2.149 en ETH (el imán
  de abajo de ETH). La mayoría de las ballenas opera con poco apalancamiento, así que pocas tienen
  la liquidación cerca del precio: cuando una aparece, es un nivel a vigilar.

Los planes del diario se dibujan como la herramienta **Posición larga/corta** de TradingView: caja
verde de la entrada al objetivo, caja roja de la entrada al stop, con el porcentaje de cada lado y el
R/R. Los planes pendientes salen más tenues, con su condición ("si cierra 4H < 77.250").

## 4 nov 2026: "El Promediador" en seguimiento y por qué no aflojar las entradas

### Ballenas en seguimiento (con alias)

La "ballena de $40M" de BTC y la de $33M de ETH resultaron ser **la misma cuenta**
(`0xf081…e39e`, margen cruzado). Perfil: solo largos, promedia a la baja y vende en pérdidas
cuando el margen aprieta. PnL realizado desde el 16 oct: **−$6,3M**.

* 3 nov 01:07: vendió $74,6M de BTC a 76.489 con −$4,4M (mínimo de la noche: 76.342; después el
  precio subió a 78.046).
* 3 nov 07:16: volvió a comprar $36M a 77.238.
* 3 nov 22:09: vendió $27,4M a 75.852 con −$0,5M, dentro de su zona de liquidación (mínimo 75.687).
  Le quedan 155 BTC (liquidación 74.685) y 14.583 ETH (liquidación 2.152).

**Solo seguimiento, no se usa como señal para operar** (decisión de Juan). Alias: **El Promediador**.
Todas las billeteras seguidas tienen ahora un alias (Águila, Lobo, Oso…; corto plazo: Colibrí,
Liebre…) y el indicador de billeteras dice cuáles están largas y cuáles cortas.

Medición hasta hoy (episodios ≥ $1M, 72 h después): aperturas **8 a favor / 7 en contra** (aún no
falla de forma clara); capitulaciones (cierres en pérdida) **2 de 2 justo antes de un rebote**.
Muestra mínima: se sigue midiendo. `python -m copytrading ballena` muestra el historial y lo guarda
en `data/ballenas_historial.jsonl`; el monitor avisa cuando abre o cierra algo grande.

### ¿Aflojar el barrido para no perder entradas por poco?

El 3 nov el plan E no se activó: el precio llegó a 78.046 y el barrido pedía 78.150 (además, el
plan empezaba el miércoles por las elecciones). Se probó en BTC + ETH + SOL (1H, 7 meses) vender
tras barrer los cortos de 25-100x y volver a cerrar dentro, objetivo 2R:

| Barrido exigido | Ops | Media por op. | 1.ª / 2.ª mitad |
|---|---|---|---|
| Exacto (tocar la zona) | 282 | +0,07R | +0,12 / +0,02 |
| A 0,2 % de la zona | 326 | −0,01R | +0,07 / −0,08 |
| A 0,5 % | 388 | +0,02R | +0,09 / −0,05 |
| **Exacto + imán a favor (≥ 1,5x más liquidez abajo)** | 115 | **+0,11R** | **+0,12 / +0,11** |
| Exacto + imán, a 0,2 % | 139 | 0,00R | −0,01 / +0,01 |
| Acercarse a la zona + cierre bajo la EMA 50 de 1H | 124–180 | −0,14 a −0,18R | negativo |

Lectura: **aflojar el barrido no ayuda**; mete más operaciones malas. Lo que sí mejora es operar
solo a favor del imán. Comprar tras barrer los largos de 100x (el espejo) fue negativo: cuando se
barren, el precio suele seguir hacia el pool grande. Ajustes aplicados:

1. Barrido **exacto**, pero solo **a favor del imán**.
2. La imagen marca **"⚠ CONTRA EL IMÁN"** en cualquier plan que vaya contra la liquidez dominante
   (el largo del 30 oct salía así y terminó en stop).
3. Las restricciones de horario (elecciones, fin de semana) cuestan entradas: decidirlas plan por plan.

### Billeteras de tendencia + pools y canales (4 nov 2026)

Se reconstruyó la posición histórica de las billeteras de tendencia a partir de sus fills (≈ 12
meses; se pierde lo anterior a sus 10.000 fills más recientes) y se cruzó con la estrategia:

| BTC | Resultado |
|---|---|
| Rendimiento de las 72 h siguientes con billeteras **BAJISTA** | −0,79 % (sube 43 % de las veces) |
| … con billeteras **ALCISTA** / **MIXTO** | −0,16 % / +0,02 % |
| Imán de pools (≥ 1,5x, objetivo 2R) **a favor** de las billeteras | +0,07R (23 ops) |
| Imán de pools **en contra** de las billeteras | **−0,32R** (12 ops) |
| Imán de pools con billeteras MIXTO | +0,13R (39 ops) |

En ETH no hay señal útil (las billeteras se validaron con giros de BTC y casi siempre salen
BAJISTA). En el método de canales hay muy pocas operaciones para concluir.

Cuidado: las billeteras se eligieron con giros de este mismo periodo (sesgo de selección); la
prueba real será su comportamiento de aquí en adelante.

Uso: las billeteras de tendencia funcionan como **veto**, no como gatillo. En BTC, evitar operar el
imán o un canal **en contra** de ellas; la imagen lo marca como "⚠ CONTRA LAS BILLETERAS". Los
nombres de las billeteras no se muestran en el aviso; se guardan sus cambios de posición en
`data/billeteras_actividad.jsonl` para ver en unos meses cuáles son las más activas.

### Regla de tendencia: solo operar a favor (4 nov 2026)

Regla de Juan: con tendencia de corto plazo bajista, buscar solo cortos; con alcista, solo largos.
Se probó con la regla de rebote tras barrer un pool (4H, confirmación, objetivo 2R; BTC + ETH +
SOL, 2,3 años):

| Cómo medir la tendencia | A favor | En contra |
|---|---|---|
| **Pendiente de la EMA 50 diaria (6 días)** | **+0,43R (68 %, 38 ops)** | −0,10R (39 %, 76 ops) |
| Precio por encima/debajo de la EMA 50 diaria | +0,42R (68 %, 28 ops) | −0,04R (43 %, 87 ops) |
| Precio frente a la EMA 50 y 200 diarias | +0,41R (70 %, 20 ops) | **−0,34R** (30 %, 47 ops) |
| Estructura de 4H (máximos/mínimos de 5 días) | −0,62R (5 ops) | +0,13R (92 ops) |

La pendiente de la EMA 50 diaria separa mejor: a favor gana, en contra pierde. La estructura de 4H
de pocos días no sirve (tras un barrido el precio suele ir contra la estructura reciente). El
monitor muestra la tendencia de cada moneda ("buscar solo cortos/largos") y marca **"⚠ CONTRA LA
TENDENCIA"** en cualquier plan que vaya en contra. 4 nov: BTC, ETH y SOL en tendencia BAJISTA.

### Quién ganó la semana (4 nov 2026)

Ranking semanal de Hyperliquid (48.542 cuentas): las 15 cuentas de alta frecuencia (> $1.000M de
volumen) ganaron +$31,9M sobre $72.000M de volumen (~0,1 % por operación); el HLP (liquidador de
Hyperliquid) solo +$0,15M. Las ballenas que más ganaron con poco volumen estaban **cortas a favor de
la tendencia**. Se añadieron 5 al seguimiento (solo información): **El Gran Corto**, **Bobby**,
**El Francotirador**, **El Martillo** y **Cuervo**. El monitor muestra sus posiciones en BTC/ETH/SOL
y sus movimientos ≥ $5M; al móvil solo llegan los ≥ $10M.

### Radar de alta frecuencia (5 nov 2026)

`python -m copytrading hft` busca en el ranking las cuentas con volumen semanal ≥ $1.000M (o que
mueven ≥ 50 veces su capital), lee sus ~2.000 fills más recientes y sus órdenes abiertas, y las
clasifica:

* **Cazador**: ≤ 35 % maker (cruza el precio), muchos fills por hora, tamaños pequeños.
* **Creador de mercado**: ≥ 70 % maker y, a menudo, cientos de órdenes abiertas.
* **Ejecutor**: tamaño casi fijo y ritmo regular (una ballena troceando una orden).

Primera pasada (semana al 4 nov, 25 cuentas): 14 creadores de mercado (+$21,5M, $43.000M de
volumen), 5 cazadores (+$13,0M; uno solo, `0xf5d8…`, +$14,2M con ~12.000 fills por hora y 17 %
maker) y 6 mixtos (−$0,8M). Se guarda en `data/alta_frecuencia.json`.

Siguiente paso: cada operación pública de Hyperliquid trae las dos direcciones (comprador y
vendedor), así que con el canal en vivo se puede medir **hacia dónde empujan los cazadores** y
**si los creadores de mercado retiran órdenes** cerca de un pool, antes del barrido.

**Escucha 24/7 (5 nov 2026):** `copytrading/escucha.py` (en Windows, `windows/escuchar_hft.bat`;
instrucciones en `windows/LEEME_ESCUCHA.md`) se conecta al canal en vivo de Hyperliquid, clasifica
al agresor de cada operación de BTC/ETH (cazador, creador de mercado u otros), guarda el flujo por
minuto y la liquidez de los creadores a ±1 %, y avisa por ntfy cuando los cazadores empujan muy por
encima de lo normal (≥ 3σ y ≥ $300k en 5 min) o los creadores retiran > 60 % de un lado del libro.
Probado en vivo: el volumen captado por minuto coincide con el de Hyperliquid.

**Radar afinado (5 nov 2026).** Para no etiquetar mal, una cuenta solo se marca como alta frecuencia
si cumple todas las señales: rotación ≥ 20x su capital en la semana, compra ≈ vende (desequilibrio
≤ 35 %), vuelve a quedar sin posición en ≤ 2 h, no usa el TWAP de Hyperliquid y sus fills cuadran
con su volumen semanal. Creador de mercado: además ≥ 70 % maker y ≤ 3 fills por orden. Cazador:
≤ 35 % taker-maker, ≥ 100 fills/h, tamaño mediano ≤ $5.000 y rotación ≥ 50x. Ejecutor: TWAP o todo
en un sentido. El resto queda "sin confirmar" y la escucha no lo usa. Pasada del 5 nov (30 cuentas):
4 cazadores, 3 creadores de mercado y 1 ejecutor confirmados; 22 sin confirmar. `hft --detalle`
muestra qué señal falla en cada cuenta.

Límites que no se pueden eliminar: solo se ven los ~2.000 fills más recientes de cada cuenta y las
órdenes abiertas en el momento (no cada cancelación); algunas cuentas operan por subcuentas o
bóvedas y sus datos no cuadran con su volumen (se descartan).

**Horarios de los robots (5 nov 2026).** Con el historial disponible (últimos 10.000 fills):
los robots más rápidos (el cazador principal y 3 creadores de mercado) solo dejan ver 1,6–6,4 h, y
estaban activos a las 20:46 hora Colombia (fuera del horario de EE. UU.). Cazador `0x4b62…`: activo
los 7 días y casi todas las horas, con picos a las 20:00 (13 %) y 18:00 (9 %). Cazador `0xa4de…`:
7 días pero mucho menos el fin de semana, quieto de 2 a 5 am, pico a las 8 am (14 %). Ejecutor
`0x4e23…`: solo de 9 am a 5 pm (opera acciones; sigue la bolsa de EE. UU.). La escucha guarda desde
ahora `data/hft_horario.csv` (operaciones por robot y hora) para completar el horario de los rápidos.

**Cohorte de 30 cuentas (decisión de Juan, 5 nov 2026).** Más datos es mejor: la escucha estudia
durante un mes las 30 cuentas de más volumen (confirmadas o no), fijas en `data/hft_cohorte.json`.
Cada hora guarda por cuenta: operaciones, volumen, cuánto empujó comprando/vendiendo (taker),
cuánta liquidez puso (maker) y el precio (`data/hft_cuentas_hora.csv`). Cada mes se revisa quién es
más activo y quién mueve el precio, y se descarta a las que no aportan. El flujo por minuto y los
avisos siguen usando solo las confirmadas.

**Binance en la escucha (5 nov 2026).** Binance no publica quién es quién ni los precios de
liquidación (los mapas de liquidez con datos de Binance son estimaciones), pero sí datos agregados.
La escucha del computador de Juan guarda cada minuto en `data/binance_minuto.csv`, para BTC y ETH:
volumen, compra/venta agresiva, interés abierto, funding, liquidaciones reales de largos y cortos
(canal `forceOrder`; Binance publica como mucho una por segundo, así que es un mínimo) y proporción
largos/cortos de los top traders y de todas las cuentas. Aviso "💥" si en un minuto se liquidan
≥ $5M (BTC) o ≥ $2M (ETH) de un lado: barrido confirmado. Desde los servidores de la nube Binance
está bloqueado ("ubicación restringida"); si no responde, la escucha de Hyperliquid sigue igual.

### Gestión de Juan: asegurar y dejar correr (5 nov 2026)

"Esa operación es para tomar ganancia, asegurar la operación y dejarla correr." Desde ahora, un plan
sin segundo objetivo (`--tp2` vacío) se gestiona así: **mitad en TP1, stop a la entrada, y la otra
mitad corre con stop móvil** sobre el máximo (corto) o mínimo (largo) de las últimas 6 velas de 1H
(planes de 1H) o 3 de 4H (planes de 4H). Sale por el stop móvil o por tiempo. El plan J (5 nov) se
apuntó con un solo objetivo y queda registrado así (+0,36R); la nueva gestión se aplica a los planes
nuevos para no medir con lo que ya se sabe.

### Primera revisión de la escucha: caída del 5 nov 2026

Datos del PC de Juan (`data/escucha_pc/2026-11-05/`). Cobertura: 4 nov 21:01–23:41 y 5 nov
09:51–11:09 (el equipo se suspendió de madrugada: se perdió la ruptura de las 7 am).

* **Binance**: el volumen por minuto de BTC pasó de ~$3M a $100–220M; el interés abierto cayó de
  95.800 a 91.200 BTC (−4,8 %, ~$350M en posiciones cerradas). La proporción largos/cortos de
  **todas las cuentas** subió de 1,38 a 2,37 mientras caía: el público compró la caída (combustible
  para más bajada), los top traders apenas cambiaron (1,93 → 2,05).
* **Hyperliquid, cuentas en estudio (hora 10–11 am)**: vendedores netos agresivos `0xfc66…` (−$19M;
  ya vendía en la hora anterior), `0xecb6…` (−$13M), `0x4e23…` (−$6,6M); compradores netos que
  absorbieron la caída `0xb1ec…` (+$20M), `0xbf73…` (+$7,6M), `0xf71a…` (+$6,8M). El cazador
  principal `0xf5d8…` movió $52M pero equilibrado (compra ≈ vende): ruido para la dirección.
* El flujo de "otros" (no robots) fue mucho mayor que el de los robots: la caída la movieron cuentas
  normales y liquidaciones, no la alta frecuencia.
* Avisos: 🤖 "cazadores venden" a las 11:01 (tarde, cerca del mínimo). La mayoría de avisos 🏦 de
  "retiro" fueron **falsos**: la API devolvía error en plena caída y el programa lo tomaba como
  liquidez cero (corregido: un fallo ya no cuenta como cero).

Errores corregidos tras la revisión: velas de Binance repetidas (se pide la vela exacta del minuto
cerrado), liquidaciones de Binance en cero (canal de todo el mercado con dirección alternativa y
contador de mensajes), avisos falsos de retiro, y el equipo ya no se suspende solo mientras corre la
escucha (no evita la suspensión al cerrar la tapa).

## Memoria de patrones (6 nov 2026)

Idea de Juan: el mercado repite comportamientos humanos; lo que falla es la memoria.

**Lo que NO funcionó (medido):** buscar "el momento del pasado más parecido" combinando a la vez
tendencia, EMAs, canal, imán, movimiento, volumen y rupturas (BTC + ETH + SOL, 4H, 2,3 años; cada
consulta solo con datos anteriores). La dirección de las 72 h siguientes acertó un 48–51 % frente a
un 49 % de base, y los casos "muy claros" acertaron menos. El parecido general no predice.

**Lo que sí hace la memoria** (`python -m copytrading memoria`, y en el monitor y la imagen con 🧠):

1. **Patrones medidos activos ahora**, con su número: tendencia (a favor +0,43R / en contra
   −0,10R), trampa reciente, imán ≥ 2x (8 de cada 10), pérdida o recuperación de la EMA 200 diaria,
   movimiento ≥ 4 % en 24 h (no perseguir).
2. **Casos anotados** (`data/casos.json`): momentos reales con lo que pasó. Si el momento actual
   comparte ≥ 2 patrones con un caso de hace más de 3 días, aparece "Se parece a …".
3. **Se llena sola:** cada movimiento ≥ 4 % en 24 h se anota como caso con los patrones que había
   justo antes. Con los meses, cada patrón acumula sus casos y se podrá decir cuántas veces se repitió.

Casos iniciales: 2 nov (falsa ruptura en la apertura del CME), 3 nov (barrido de la ballena y
rebote +7,3 %), 5 nov (trampa alcista en la línea de tendencia y caída −6 %), 4–5 nov ETH y SOL.

**Segunda revisión (datos del 5 nov, 16:00–21:23, sin huecos).** El barrido de las 6 pm se ve en
las cuentas: `0xf71a…` vendió agresivo $22M entre las 5 y las 6 pm (precio ~75.700) y `0x4b62…`
otros $13M; el precio barrió hasta 75.189 (debajo del mínimo anterior y de los largos de 100x) y en
la hora siguiente `0xf71a…` **compró** $11M y `0xfc66…` $2,5M en el mínimo: vender para tumbar el
precio hasta los stops y comprar abajo, la conducta de "cazador" que describió Juan.

**Corrección (7 nov, con sus operaciones reales de Hyperliquid):** `0xf71a…` **no** cazó stops. Había
comprado la caída de la mañana (~100 BTC entre 77.250 y 78.730) y a las 17:39 **cerró esos largos a
mercado en ~75.800 perdiendo ~$336k**: los $22M de "venta agresiva" fueron su capitulación, que ayudó a
empujar el barrido. Luego abrió un corto en 75.850 y lo cerró en 75.200–75.430 (+$22k): esa es la
"compra en el mínimo". Semana (31 oct–6 nov): **−$1,17M realizado** (−$1,37M contando lo abierto),
con −$766k solo el jueves; histórico −$1,49M sobre $1.580M de volumen. Lección: el radar mide
**cómo** opera una cuenta (agresiva, mucha rotación), no si gana. Volumen agresivo ≠ dinero listo. Binance no
guardó filas desde las 11:09: los datos por minuto dependían de que el canal de liquidaciones en vivo
estuviera conectado; ahora van por separado.

## ¿La bolsa o la disculpa? (6 nov 2026)

Idea de Juan: siempre que hay una caída la culpa es "de las noticias" (la del 5 nov se achacó al
desplome de las tecnológicas), pero parece más una disculpa. Para medirlo en vez de opinar, la escucha
guarda desde ahora el futuro del Nasdaq 100 minuto a minuto (`data/nasdaq_minuto.csv`) y
`python -m copytrading causa` compara cada movimiento fuerte de BTC (≥ 1,5 % en menos de 60 min)
con lo que hizo el Nasdaq:

* **la bolsa se movió primero**: el Nasdaq ya iba en la misma dirección ≥ 0,3 % en los 30 min previos;
* **a la vez**: el Nasdaq se movió ≥ 0,4 % en la misma dirección durante el movimiento;
* **solo cripto**: el Nasdaq no acompañó (si culpan a la bolsa, es disculpa);
* **bolsa sin datos**: el futuro no cotizaba o faltan datos.

Marca además si la bolsa de Nueva York estaba en sesión (9:30–16:00 hora de NY; en Colombia 9:30 en
invierno y 8:30 en verano) y si el movimiento empezó antes de que la escucha grabara.

Con los datos del 5 nov (sin Nasdaq todavía): la caída grabada (−6,15 % desde las 9:51) **empezó antes
de grabar** (el equipo se despertó a las 9:51), así que no se sabe si arrancó antes o después de la
apertura de Nueva York. El barrido de las 5–6 pm (−1,1 %) y el rebote (+1,4 %) fueron con la bolsa ya
cerrada. Umbrales a revisar con un mes de datos.
