# Meross Provisioner — guía de uso

**Prototipo experimental. Provisión Wi‑Fi verificada en MSS210 US (firmware 4.2.9), MSS425E, MSS425FC y MSL430. El firmware de los tres últimos no se registró. Otras versiones siguen sin verificar.**

Provisioner configura únicamente la Wi‑Fi del dispositivo. No implementa el control del enchufe, la nube de Meross ni el binding MQTT. Para controlarlo después, usa **HomeKit Device** si el modelo lo admite o **Meross LAN** por HTTP local.

## 1. Antes de empezar

- Mantén Home Assistant conectado por **Ethernet**. El proceso interrumpe temporalmente `HA-AP` y sus clientes Wi‑Fi.
- Usa una sola interfaz Wi‑Fi dedicada al add-on de punto de acceso (`wlan0` en la Raspberry Pi 5). Provisioner suspende temporalmente la autoconnexión de los perfiles que puedan reclamarla y la restaura al terminar.
- `Hass.io Access Point` marca `wlan0` como no administrada mientras hostapd la usa. Provisioner la controla temporalmente con `nmcli` por el D‑Bus del host.
- El SSID de destino debe estar en **2,4 GHz** y usar WPA/WPA2 con una contraseña de 8–63 bytes.
- Ten el dispositivo Meross en **modo AP de configuración**, no solo en emparejamiento Bluetooth. Desconecta el móvil del AP del Meross: algunos modelos solo atienden un cliente de configuración.
- Comprueba que el DHCP de la app AP está activo y que el rango tiene direcciones libres. Una reserva DHCP para la MAC del dispositivo evita cambios de IP.

## 2. Opciones del complemento

- **Interfaz Wi‑Fi (`wifi_interface`)**: la interfaz que usa el add-on AP. En una Raspberry Pi 5 suele ser `wlan0`.
- **Slug del add-on AP (`access_point_addon_slug`)**: el ID completo del Supervisor, no el nombre visible. Si no lo sabes, inicia Provisioner con el campo vacío y copia el slug que muestra la pantalla inicial.
- **IP del proxy Ingress (`ingress_peer_ip`)**: normalmente `172.30.32.2`. No lo cambies salvo que tu Supervisor use otra dirección interna.

## 3. Flujo de provisión

1. Abre la interfaz web del complemento. El **preflight** comprueba Ethernet, interfaz Wi‑Fi, app AP y permisos. Si hay errores, no continúes.
2. Marca las dos confirmaciones y pulsa **Detener temporalmente HA-AP y escanear**.
3. Provisioner detiene el add-on AP, suspende la autoconnexión de perfiles que puedan interferir, activa la radio Wi‑Fi y pone `wlan0` bajo NetworkManager.
4. Escanea las redes y muestra los AP cuyo nombre parece de Meross. Selecciona el que corresponde al dispositivo que acabas de poner en modo configuración.
5. Escribe el **SSID de destino** (por ejemplo `HA-AP`) y su contraseña WPA/WPA2. Puedes usar **Mostrar** para comprobar la contraseña. No uses la contraseña de Meross.
6. Pulsa **Configurar este dispositivo**. Provisioner:
   - Crea un perfil temporal abierto, no autoconectable, ligado a la BSSID del AP de configuración.
   - Se conecta al AP del Meross y obtiene la IP del dispositivo por DHCP.
   - Lee el modelo, el firmware y la lista de redes del dispositivo.
   - Si el destino es el mismo AP que Provisioner va a restaurar, usa el **SSID, canal y visibilidad guardados en la app AP** y la MAC de `wlan0`. Es normal que el Meross no vea `HA-AP` en ese momento: está detenido.
   - Envía solo `Appliance.Config.Wifi` (SSID, contraseña y metadatos de seguridad). No envía claves de Meross ni configura MQTT.
   - Restaura `HA-AP`, elimina solo el perfil temporal y reactiva la autoconnexión suspendida.
7. El dispositivo se reinicia y se conecta a `HA-AP`. Provisioner muestra el modelo, firmware y MAC para que puedas identificarlo.

Si algo falla, el diario de transacción y la recuperación automática intentan restaurar el AP. Si el AP no vuelve, arráncalo manualmente desde Home Assistant.

## 4. Después de provisionar

1. Comprueba que `HA-AP` vuelve a emitir y que Home Assistant sigue accesible por Ethernet.
2. Espera 30–60 segundos y busca una concesión DHCP para la MAC del resultado. La reserva DHCP de la app AP es la forma más cómoda de fijar la IP.
3. Añade el dispositivo a Home Assistant:
   - **HomeKit Device** si el modelo lo admite. Usa el código de la etiqueta; no lo publiques.
   - **Meross LAN** para control local por HTTP: [github.com/krahabb/meross_lan](https://github.com/krahabb/meross_lan). Instálalo desde HACS, reinicia Home Assistant, añade la integración **Meross LAN** (no la integración oficial **Meross**), elige dispositivo manual, introduce la IP y deja la clave **vacía**. Si pones una clave, Meross LAN puede responder que es incorrecta. Si no añade el dispositivo, reinicia primero la app AP, espera a que el Meross se reconecte y vuelve a añadirlo con la clave vacía. Fuerza el protocolo **HTTP** si quieres control local.
   - La integración oficial **Meross** de Home Assistant Core usa la nube y pide cuenta. No es necesaria para control local.

### La luz verde

| Luz | Significado |
| --- | --- |
| Ámbar fijo | Inicializando o actualizando firmware |
| Alternando ámbar/verde | Listo para emparejar |
| Verde parpadeando rápido | Conectando a Wi‑Fi |
| Verde fijo | Conectado a Wi‑Fi / emparejado |
| Verde parpadeando tras provisionar | Conectado a Wi‑Fi pero sin binding con Meross/MQTT |
| Rojo fijo | Sin conexión a internet |
| Apagada | Sin alimentación o LED desactivado |

Provisioner no configura `Appliance.Config.Key` ni completa el binding de Meross. Por eso el enchufe puede quedarse parpadeando en verde aunque Meross LAN lo controle por HTTP. No es un fallo de la provisión. El comportamiento depende del modelo/firmware: en la prueba realizada, el MSS210 US siguió parpadeando; el MSS425FC y las MSL430 no se quedaron parpadeando. No uses solo el LED para decidir si la provisión funcionó: comprueba la concesión DHCP y el control local.

Meross LAN suele exponer una entidad **DND/LED** que apaga el LED. En Meross LAN la lógica está invertida respecto a la app de Meross, así que prueba ambas posiciones. Apagar el LED también elimina la señal visual de encendido.

Si quieres que el LED vuelva a comportarse como un dispositivo emparejado sin usar la nube, hay que vincularlo a un broker MQTT local. Es un proceso avanzado, opcional y no implementado por Provisioner; puedes leer los pasos generales en [docs/post-provisioning.md](https://github.com/merchedev/ha-meross-provisioner/blob/main/docs/post-provisioning.md).

## 5. Preguntas frecuentes

### ¿Necesito la app o una cuenta de Meross?

No para provisionar. Provisioner usa el AP local del dispositivo y HTTP local. Para controlarlo, usa HomeKit Device si el modelo lo admite o Meross LAN por HTTP. La cuenta de Meross solo hace falta para la nube o para recuperar una clave gestionada por la nube; este proyecto no la necesita.

### ¿Provisioner controla el enchufe después?

No. Solo configura la Wi‑Fi. El control, las entidades y las automatizaciones los gestiona HomeKit Device o Meross LAN.

### ¿HA-AP vuelve después de provisionar?

Sí. El flujo restaura la app AP en su paso de recuperación, incluso si hay un error o un timeout. Si no ves el SSID, abre la app AP en Home Assistant y arráncala.

### ¿El AP de destino tiene que ser visible durante la provisión?

No si el destino es el mismo AP que Provisioner detiene. Lee su SSID, canal y visibilidad antes de pararlo y usa esos datos. El AP debe volver a estar visible cuando el dispositivo se reinicia e intenta unirse.

### ¿Puedo usar el SSID de mi router en vez de HA-AP?

Sí, siempre que el Meross lo vea en su propio escaneo y sea una red 2,4 GHz WPA/WPA2 compatible. En ese caso se usan los metadatos que devuelve el dispositivo.

### No encuentra el AP del Meross

Comprueba que el dispositivo está en modo AP, no solo en emparejamiento Bluetooth; que el móvil no está conectado a su AP; que está cerca; y que emite en 2,4 GHz. El mensaje de error muestra las redes que sí se han visto para distinguir “no veo ninguna” de “la red tiene otro nombre”.

### La interfaz aparece como unavailable

Tras parar hostapd, `wlan0` puede quedar administrativamente apagada. Provisioner activa la radio y la pone bajo NetworkManager. Si persiste, revisa el estado real en el mensaje de error y prueba a reiniciar el add-on AP o Home Assistant OS.

### Error de perfil incompatible o WEP

En versiones anteriores el perfil temporal incluía una sección de seguridad vacía que NetworkManager interpretaba como WEP. Desde 0.1.12 el perfil es una red abierta real, sin sección de seguridad. Actualiza.

### “Home Assistant could not reach the Meross setup AP”

La conexión temporal se activó, pero la petición HTTP al dispositivo falló. Desde 0.1.13 se reintentan las lecturas iniciales y el mensaje incluye el tipo de error y el errno. Un `ClientConnectorError` con errno 101/113 indica un problema de ruta; un timeout indica que el dispositivo no respondió a tiempo; `ServerDisconnectedError` apunta a una diferencia de firmware/protocolo.

### “The device returned an empty or invalid SSID”

La lista del dispositivo contenía una red oculta o una codificación especial. Desde 0.1.14 se saltan las entradas ocultas o mal formadas y se aceptan SSID en Base64, texto plano o con relleno NUL, además de BSSID con guiones.

### “The Meross device cannot see the target SSID”

Es normal si el destino es `HA-AP`, porque Provisioner lo detiene durante la configuración. Desde 0.1.15 se usan el SSID, canal y visibilidad guardados en la app AP. Si el mensaje persiste, comprueba que el SSID coincide exactamente, que el AP es visible (no oculto) y que está en 2,4 GHz.

### “Provisioner could not read the AP app's channel and MAC”

Desde 0.1.16 se intentan varias fuentes para la MAC y el canal. Si aun así faltan, se envía un perfil mínimo con SSID, contraseña y seguridad WPA2, y se avisa en el resultado. Si el dispositivo no se une, revisa que la app AP exponga `ssid`, `channel` y `hide_ssid`, y que la MAC de la interfaz sea visible para NetworkManager.

### El dispositivo acepta la configuración pero se desconecta o reinicia

Revisa en este orden: DHCP activo y con direcciones libres; errores WPA/4‑way handshake en el log del AP; canal 12/13 (mejor 1, 6 u 11); y el binding de Meross. Si el handshake WPA se completa, la contraseña es correcta.

### Meross LAN me pide una clave o dice que es incorrecta

Deja el campo **Device key vacío**. En la prueba realizada, poner cualquier clave hacía que Meross LAN respondiera que era incorrecta; con la clave vacía funcionó el modo local. La contraseña de la cuenta de Meross no es la clave del dispositivo.

### Meross LAN no añade el dispositivo después de provisionar

Reinicia primero la app **Hass.io Access Point**, espera a que el Meross se reconecte y obtenga su concesión DHCP, y vuelve a añadirlo con Meross LAN usando la IP y la clave vacía. Ese orden fue necesario en la prueba realizada.

### Meross LAN solo me deja añadir hubs y me pide cuenta

Estás usando la integración oficial **Meross** o la opción cloud/MQTT hub. Instala **Meross LAN** desde HACS y elige el dispositivo manual por IP. Deja la clave vacía y fuerza HTTP.

### La entidad DND apaga el LED y pierdo la señal de encendido

Es el comportamiento del dispositivo: hay un único LED de estado, no un modo “solo encendido, sin estado de conexión”. Sin binding cloud/MQTT las opciones son parpadeo o LED apagado. Para tener el LED normal sin nube hace falta el binding MQTT local, que es avanzado y opcional.

## 6. Seguridad y limitaciones

- El protocolo SoftAP envía la contraseña por HTTP local sin cifrado real. Configura un dispositivo cada vez, cerca de ti, y usa una contraseña exclusiva para la red IoT.
- Para configurar el dispositivo mientras `HA-AP` está detenido, Provisioner lee de la app AP su SSID, canal y visibilidad, y la MAC de la interfaz. No guarda, muestra ni envía la contraseña de la app AP.
- La app requiere el rol `manager` del Supervisor para escanear redes y detener/iniciar el add-on AP.
- Provisioner no configura la nube ni MQTT. No se garantiza que el firmware no contacte con Meross después de unirse a la Wi‑Fi; aplica reglas de salida si necesitas aislamiento.
- La provisión Wi‑Fi está verificada con MSS210 US (firmware 4.2.9), MSS425E, MSS425FC y MSL430. El firmware de los tres últimos no se registró.
- El LED tras provisionar depende del modelo/firmware: el MSS210 US siguió parpadeando; el MSS425FC y las MSL430 no.
- El control del dispositivo no forma parte de este proyecto. Usa HomeKit Device o Meross LAN.

## 7. Más información

- [Después de provisionar](https://github.com/merchedev/ha-meross-provisioner/blob/main/docs/post-provisioning.md)
- [Solución de problemas y FAQ](https://github.com/merchedev/ha-meross-provisioner/blob/main/docs/troubleshooting.md)
- [Arquitectura](https://github.com/merchedev/ha-meross-provisioner/blob/main/docs/architecture.md)
- [Protocolo Meross](https://github.com/merchedev/ha-meross-provisioner/blob/main/docs/meross-protocol.md)
- [Soporte de hardware](https://github.com/merchedev/ha-meross-provisioner/blob/main/docs/platform-support.md)
