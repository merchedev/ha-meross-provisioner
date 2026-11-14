# Meross Provisioner para Home Assistant

**Estado: prototipo experimental. Aún no se ha verificado la configuración física en una Raspberry Pi 5 con Home Assistant OS.**

Meross Provisioner es una app de Home Assistant cuyo objetivo es conectar un dispositivo Meross en modo de configuración a la Wi‑Fi elegida, sin usar la app ni la nube de Meross. La conexión de configuración es local; después, el Supervisor de Home Assistant intenta restaurar el punto de acceso.

El primer objetivo es una instalación de Home Assistant OS conectada por cable, con una interfaz Wi‑Fi dedicada a un add-on compatible de punto de acceso. Durante la configuración ese AP se interrumpe temporalmente. La conexión por cable mantiene accesible la interfaz de Home Assistant.

> Es un proyecto comunitario independiente, no afiliado a Meross. No controla los dispositivos: tras configurarlos, usa HomeKit Device de Home Assistant o una integración local Meross compatible.

## Limitaciones importantes

- Las credenciales Wi‑Fi se envían por HTTP local al AP de configuración Meross. Base64 **no es cifrado**. Usa una contraseña exclusiva para la red IoT y configura los dispositivos estando presente.
- La app no hace peticiones a la nube Meross ni envía `Appliance.Config.Key`. Eso no demuestra que el firmware del dispositivo nunca contacte con servidores del fabricante después de conectarse; hay que verificar cada firmware y aplicar reglas de salida en el router/AP si se necesita aislamiento total.
- La app solo configura el Wi‑Fi; no controla los dispositivos. Tras configurarlos, usa HomeKit Device o una integración local compatible. Los modelos sin HomeKit podrían requerir una clave local adicional, todavía fuera del alcance del prototipo.
- La app necesita el rol `manager` del Supervisor para detener/iniciar el AP y acceso al D-Bus del host para controlar NetworkManager. Son permisos potentes; revisa la documentación de seguridad.
- El preflight se detiene si NetworkManager tiene perfiles Wi-Fi guardados que puedan conectarse automáticamente.
- El código actual es un prototipo. No lo uses en un sistema cuya interfaz Wi‑Fi tenga un perfil persistente que quieras conservar. El prototipo debe fallar de forma segura si no puede garantizar la recuperación.
- Se espera que la Wi‑Fi integrada de la Pi 5 pueda usarse como cliente tras parar el AP, pero hay que probar la interacción entre Home Assistant OS, NetworkManager y el add-on concreto. No se presupone que AP y cliente funcionen a la vez.
- Todavía no se ha probado con MSS210, MSS425FC ni MSL430. Consulta la matriz de compatibilidad.

Consulta también el [README en inglés](README.md), la [guía de Raspberry Pi 5](docs/haos-rpi5.md) y la [documentación técnica](docs/).
