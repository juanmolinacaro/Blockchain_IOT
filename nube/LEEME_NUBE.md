# La escucha en la nube, gratis (Oracle Cloud "Always Free")

Para no tener el portátil encendido día y noche: la escucha corre en un servidor de Oracle que es **gratis sin fecha
de fin**, se reinicia sola si se cae, se actualiza sola cada día a las 5:00 y (opcional) sube los datos a GitHub cada
6 horas, así ya no hay que mandar los archivos.

## 1. Crear la cuenta (una vez, ~15 min)

1. Entra a **https://www.oracle.com/cloud/free/** → **Start for free**.
2. **Región de inicio (Home Region): elige una de Latinoamérica** (Bogotá si aparece; si no, São Paulo, Santiago o
   Querétaro). **No elijas EE. UU.**: Binance bloquea las conexiones desde allá. La región no se puede cambiar después.
3. Pide una tarjeta para verificar que eres tú. Lo "Always Free" no se cobra.

## 2. Evitar que Oracle apague el servidor (recomendado)

Oracle puede recuperar servidores gratis que casi no usan el procesador (la escucha consume poco). Para evitarlo:
1. Menú ☰ → **Billing & Cost Management → Upgrade and Manage Payment** → **Upgrade to Pay As You Go**. Lo gratis
   sigue gratis.
2. Menú ☰ → **Billing → Budgets → Create Budget**: monto **1 USD**, alerta al 100 % a tu correo. Si algún día algo
   costara, te avisa.

## 3. Crear el servidor

1. Menú ☰ → **Compute → Instances → Create instance**.
2. **Image**: Ubuntu (22.04 o 24.04).
3. **Shape**: **Ampere → VM.Standard.A1.Flex** con 1 OCPU y 6 GB (dice "Always Free-eligible"). Si sale "Out of
   capacity", usa **AMD → VM.Standard.E2.1.Micro** (también gratis; alcanza).
4. **Add SSH keys → Generate a key pair for me → Save private key** (se descarga un archivo `.key`; guárdalo bien).
5. **Create**. Cuando diga **Running**, copia la **Public IP address**.

## 4. Entrar al servidor e instalar (desde tu PC con Windows)

1. Abre **PowerShell** y escribe (cambia la ruta del archivo y la IP):

       ssh -i "C:\Users\TU_USUARIO\Downloads\ssh-key-XXXX.key" ubuntu@IP_PUBLICA

   La primera vez pregunta "Are you sure…?" → escribe `yes`.
2. Ya dentro, pega esto y Enter (tarda 2–3 minutos):

       curl -fsSL https://raw.githubusercontent.com/juanmolinacaro/Blockchain_IOT/claude/onchain-replication-strategy-8naui6/nube/instalar.sh | sudo bash

3. Debe terminar con **"Listo. La escucha corre 24/7"**. Para ver lo que hace en vivo:

       sudo journalctl -u escucha -f

   (Ctrl+C para salir; la escucha sigue corriendo). En unos minutos llega al móvil el **"💚 Escucha activa"**.
4. **Apaga la escucha del portátil** (cierra la ventana negra y quita el acceso directo del inicio de Windows), para
   que no lleguen los avisos dos veces.

## 5. (Opcional, recomendado) Que los datos lleguen solos

Así ya no hay que mandar los archivos por el chat: el servidor los sube cada 6 horas a la rama `datos-escucha`.
1. En GitHub: tu foto → **Settings → Developer settings → Personal access tokens → Fine-grained tokens →
   Generate new token**.
   * Expiration: 1 año. Repository access: **Only select repositories → Blockchain_IOT**.
   * Permissions → Repository permissions → **Contents: Read and write**. Nada más.
   * **Generate token** y cópialo (no lo pegues en el chat).
2. En el servidor:

       sudo bash /opt/escucha/nube/poner_token.sh

   Pega el token (no se ve al pegarlo) y Enter. Debe decir **"Datos subidos."**

## Comandos útiles (en el servidor)

| Para… | Escribe |
|---|---|
| ver si está corriendo | `systemctl status escucha` |
| ver lo que hace en vivo | `sudo journalctl -u escucha -f` |
| reiniciarla (toma la última versión) | `sudo systemctl restart escucha` |
| pararla | `sudo systemctl stop escucha` |
| subir los datos ya | `sudo bash /opt/escucha/nube/subir_datos.sh` |

Los datos quedan en `/opt/escucha/data` (los mismos archivos que en el PC).
