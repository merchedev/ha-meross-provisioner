# Meross Provisioner — guía de uso

**Prototipo experimental. No configures dispositivos hasta que el preflight indique que está listo.**

## 1. Antes de iniciar

- Mantén Home Assistant conectado por Ethernet. El proceso interrumpe brevemente `HA-AP` y sus clientes Wi-Fi.
- Usa una sola interfaz Wi-Fi dedicada al add-on de punto de acceso. Si NetworkManager detecta perfiles que puedan autoconectarse a esa interfaz, Provisioner suspende temporalmente su autoconnexión y la restaura al terminar.
- Hass.io Access Point marca `wlan0` como no administrada mientras hostapd la usa. Provisioner utiliza NetworkManager por el D-Bus del host para gestionarla temporalmente; comprueba que NetworkManager vea la interfaz.
- El SSID de destino debe ser visible en 2,4 GHz y usar WPA/WPA2 con una contraseña de 8–63 bytes.
- Configura primero un único dispositivo Meross en modo de emparejamiento y tenlo físicamente cerca.

## 2. Opciones del complemento

En **Configuración** introduce:

- **Interfaz Wi-Fi (`wifi_interface`)**: la interfaz física que usa tu add-on AP. En una Raspberry Pi 5 suele ser `wlan0`; debe coincidir con la interfaz configurada en ese add-on.
- **Slug del add-on AP (`access_point_addon_slug`)**: el ID completo del Supervisor, no el nombre visible “Hass.io Access Point”. El slug base de ese add-on suele ser `hassio-access-point`, pero instalado desde un repositorio puede llevar un prefijo. Inicia Provisioner con este campo vacío si hace falta; la pantalla inicial muestra los slugs instalados. Copia exactamente el de Hass.io Access Point, guarda y reinicia Provisioner.
- **IP del proxy Ingress (`ingress_peer_ip`)**: normalmente `172.30.32.2`. Déjalo así salvo que la red interna del Supervisor tenga otra dirección.

Inicia el complemento y abre **Open Web UI**. El preflight es de solo lectura: verifica Ethernet, interfaz, add-on AP y permisos. Si muestra errores, **no pulses Escanear**. El proyecto no ha sido validado aún con todas las variantes de Hass.io Access Point.

## 3. Configurar un dispositivo

1. Lee la advertencia y marca que aceptas la interrupción temporal de `HA-AP` y que la interfaz está dedicada al AP, sin un perfil Wi-Fi que debas conservar.
2. Pon exactamente un Meross en modo de configuración y pulsa **Detener temporalmente HA-AP y escanear**. Si el móvil sigue conectado al AP del Meross, desconéctalo: el servidor de configuración del dispositivo puede atender una sola conexión.
3. Selecciona el AP Meross correspondiente al dispositivo que acabas de poner en modo de configuración.
4. Introduce el SSID de destino (por ejemplo, `HA-AP`) y la contraseña WPA/WPA2 de esa red. No es la contraseña de Meross.
5. Pulsa **Configurar este dispositivo** y espera a que se restaure el AP. Provisioner reintenta las lecturas iniciales durante unos segundos mientras el servidor HTTP del dispositivo termina de arrancar.
6. Comprueba que el dispositivo recibe una concesión DHCP. La MAC aparece en el resultado; puedes usarla para crear una reserva DHCP en el add-on AP.
7. Añádelo en Home Assistant con **HomeKit Device** si el modelo lo admite. Los modelos sin HomeKit pueden necesitar una clave local u otra configuración de integración que este complemento aún no gestiona.

Si cierras la pantalla durante el escaneo, la sesión caduca y Provisioner intenta restaurar el AP automáticamente. También puedes usar **Cancelar y restaurar HA-AP**.

## Seguridad y limitaciones

- Provisioner no inicia sesión en Meross ni configura `Appliance.Config.Key`. Esto no garantiza que el firmware del dispositivo nunca contacte con la nube después de unirse a la red; compruébalo por modelo/firmware y aplica reglas de salida si necesitas aislamiento.
- El protocolo SoftAP envía la contraseña por HTTP local sin cifrado real. Configura un dispositivo cada vez, cerca de ti, y usa una contraseña exclusiva para la red IoT.
- La app requiere el rol `manager` del Supervisor para escanear redes y detener/iniciar el add-on AP.
- Si el preflight informa de un perfil Wi-Fi existente, el add-on AP no está ejecutándose, no hay Ethernet o las redes se solapan, detente y conserva el mensaje de error para diagnóstico.
