# Escucha 24/7 de la alta frecuencia (Windows)

Programa pequeño que se queda escuchando todas las operaciones de BTC y ETH en Hyperliquid, detecta
lo que hacen los robots (cazadores y creadores de mercado) y te avisa al celular por ntfy. No usa
Claude mientras corre.

## Instalación (una sola vez)

1. **Python**: descárgalo de https://www.python.org/downloads/ e instálalo.
   En la primera pantalla marca la casilla **"Add python.exe to PATH"**.
2. **El programa**: descarga el proyecto en ZIP desde
   https://github.com/juanmolinacaro/Blockchain_IOT/archive/refs/heads/claude/onchain-replication-strategy-8naui6.zip
   y descomprímelo, por ejemplo en `Documentos\Blockchain_IOT`.
3. Entra en la carpeta `windows` y haz **doble clic en `escuchar_hft.bat`**.
   La primera vez tarda un minuto en preparar todo. Si Windows muestra "Windows protegió su PC",
   pulsa "Más información" → "Ejecutar de todas formas".

Verás una ventana negra con la línea `Escuchando BTC, ETH · 25 robots en el radar`. Déjala abierta
(puedes minimizarla). Para parar, ciérrala.

## Que no se duerma el computador

Configuración → Sistema → Inicio/apagado y batería (o Energía) → **Suspender: Nunca** cuando esté
enchufado. La pantalla sí se puede apagar.

## Que arranque solo al encender el computador (opcional)

1. Pulsa `Windows + R`, escribe `shell:startup` y Enter.
2. Crea ahí un acceso directo a `escuchar_hft.bat` (clic derecho en el .bat → Mostrar más opciones →
   Crear acceso directo, y mueve el acceso directo a esa carpeta).

## Qué avisos llegan

* **🤖 Los cazadores COMPRAN / VENDEN agresivo**: el flujo de los robots cazadores en 5 minutos está
  muy por encima de lo normal. Dice hacia qué pool de liquidez va el precio.
* **🏦 Los creadores de mercado retiran compras / ventas**: quitan gran parte de sus órdenes de un
  lado del precio; el camino queda libre hacia ese lado.

Como mucho un aviso de cada tipo cada 30 minutos. Aunque no haya avisos, la ventana escribe cada
15 minutos una línea **"✓ Funcionando"** con cuántas operaciones vio y lo que hacen los robots, y
cada 6 horas llega al móvil un mensaje silencioso **"💚 Escucha activa"**. Es experimental: los umbrales se ajustarán con los
datos que se guarden.

## Dónde se guardan los datos

En la carpeta `data`:

* `hft_flujo.csv`: cada minuto, el flujo agresivo de cazadores, creadores y resto, y la liquidez
  de los creadores a ±1 % del precio.
* `hft_eventos.jsonl`: cada aviso enviado.
* `hft_cuentas_hora.csv`: cada hora, para cada una de las 30 cuentas en estudio: operaciones, volumen,
  cuánto empujó el precio comprando o vendiendo, cuánta liquidez puso, y el precio de BTC y ETH.
* `hft_cohorte.json`: las 30 cuentas que se estudian este mes (se revisan y descartan cada mes).

Para mirar el CSV sin bloquearlo, **cópialo** (Ctrl+C, Ctrl+V) y abre la copia en Excel. Si abres el
original, el programa sigue escuchando y guarda los datos en memoria hasta que cierres Excel.

Cada cierto tiempo pásame esos dos archivos (o súbelos al chat) para medir si los avisos se
adelantan a los barridos.

## Actualizar

Es automático: cada vez que abres `escuchar_hft.bat`, busca la última versión en GitHub y reemplaza
solo el código. Tu carpeta `data` (lo guardado) no se toca. Si no hay internet, arranca con la
versión que ya tienes.
