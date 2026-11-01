# Guía de usuario: PEMFC ModelLab v0.3.0

## A. Motor 1: de un dispositivo nuevo a su perfil electroquímico

1. **Catálogo.** Al entrar verá «Motor 1 — Gestión e identificación de dispositivos PEMFC» y las tarjetas de sus dispositivos.
   - Puede buscar por nombre, fabricante, modelo o id, filtrar por estado o fabricante, y ordenar.
   - Cada tarjeta separa el **estado administrativo** (insignia de color) de la **calidad científica** del perfil activo.
2. **Crear.** Pulse la tarjeta **«+ Agregar dispositivo»**. Solo el nombre es obligatorio; fabricante y modelo son opcionales. Entrará directamente en su espacio de trabajo.
3. **Flujo guiado 01–06.** El indicador superior muestra el estado de cada etapa: no iniciada, en progreso, completa, requiere atención o bloqueada (el motivo aparece al pasar el cursor). Puede pulsar cualquier etapa accesible para ir a ella. Abajo están **← Anterior · Guardar borrador · Continuar →**; «Continuar» respeta las validaciones de cada etapa.
   - **01 Dispositivo:** tecnología, configuración, número de celdas, área activa (con su origen), datos nominales, datasheet, observaciones y procedencia. Nada se inventa. N_cells y A_active solo se exigen si los datos vienen como corriente total o tensión de stack.
   - **02 Datos experimentales:** CSV, datos pegados, ejemplos documentados o **imagen de una curva**. La imagen abre el digitalizador, con ejes reconocidos automáticamente.
   - **03 Configuración del modelo:** preset recomendado, preset OTEKON o configuración por parámetro.
   - **04 Calibración:** «Ejecutar identificación». Cada ejecución queda registrada como **calibración nueva**; nunca se sobrescribe ninguna.
   - **05 Análisis y validación:** gráficos, residuos, métricas, identificabilidad y validación independiente.
   - **06 Perfil y exportación:** `profile.json` y ZIP del experimento. Cada descarga queda registrada.
4. **Guardado.** Arriba a la derecha se ve el estado («Guardado en este navegador · hora», «Cambios sin guardar», «Guardando…»). El trabajo se guarda solo tras cada cambio relevante; «Guardar borrador» además fija un punto explícito.
5. **Volver más tarde.** Recargue o cierre la página: al volver, el catálogo y el flujo se recuperan en el mismo navegador. Si una calibración ya no está en memoria, la etapa 04 la muestra registrada, en solo lectura.
6. **Historial y perfiles.** Desde el selector superior del dispositivo puede:
   - consultar las calibraciones, en solo lectura con su gráfico observado frente al modelo;
   - **establecer el perfil activo**, una selección administrativa que no lo convierte en validado;
   - comparar calibraciones: RMSE, parámetros, condiciones y dominio;
   - crear una «Nueva identificación a partir de esta»;
   - ver los conjuntos de datos y los perfiles exportados.
7. **Copias de seguridad.** En la pantalla inicial, «Proyectos, copias de seguridad y compatibilidad» permite:
   - exportar todo como `.pmlproj.zip`;
   - importar un proyecto, sin sobrescribir nada;
   - migrar un `profile.json` de v0.1/v0.2 a un dispositivo nuevo.

## B. Digitalizador autónomo: de una figura a una tabla X–Y

1. Pulse **Digitalizador** en la barra superior y cargue un PNG, JPEG o WebP, o use una imagen de ejemplo.
2. **Reconocimiento automático.** Se detectan paneles, ejes, números de las escalas (con OCR local verificado geométricamente), unidades y trazos.
   - Sobre la imagen, cada número reconocido aparece enmarcado: **verde** si es coherente, **rojo** si es atípico, **gris** si está excluido y **azul** si es el título con la unidad. El botón «OCR» los oculta.
   - Cada eje indica **Reconocimiento confiable**, **Pendiente de revisión** (con las razones) o **Insuficiente**.
3. **Corregir si hace falta.**
   - En «Etiquetas reconocidas» puede cambiar un valor o excluir una etiqueta. Si el eje queda en revisión, pulse «Confirmar eje».
   - Las referencias manuales siguen disponibles: escribir un valor es calibración manual.
   - Unidades: en este modo son texto libre.
4. **Varios paneles.** Elija el panel en «Panel». Cada uno conserva su calibración, sus curvas y sus correcciones al cambiar de uno a otro.
5. **Curvas.** Elija el trazo candidato, edítelo si hace falta (mover, añadir, borrar, excluir, ROI, zoom, deshacer) y pulse **«Guardar curva»** con un nombre. Repítalo para cada curva.
6. **Exportar datos.**
   - Pestaña **«Exportar datos»**: elija el alcance (curva actual, una guardada, todas las del panel o todas las de la imagen).
   - Revise la tabla, que puede copiar directamente.
   - Pulse «Preparar archivos» y descargue **CSV, XLSX, JSON, PNG o ZIP**. Los cinco contienen exactamente los mismos valores.
   - Sin calibración confirmada solo puede exportar **píxeles**, de forma explícita, con la marca «SIN CALIBRAR».

## C. Qué hace y qué no hace la aplicación

- Nunca inventa valores de ejes, unidades, N_cells, A_active ni σ_V.
- Una curva digitalizada siempre tiene calidad «digitalizado».
- Un ajuste no es una validación: el estado «validado» solo aparece con datos experimentales independientes.
- El Motor 2 (simulación operacional) no está implementado.
- Los datos se guardan en su navegador. Para conservarlos con independencia de él, exporte el proyecto.
