# Contrato científico — PEMFC ModelLab Hito 1

1. Entrada obligatoria: curva de polarización medida/digitalizada y confirmada, V–I o V–j. Datasheet solo complementario.
2. El modelo semiempírico es una representación aproximada; ajustar curvas NO demuestra fidelidad en transitorios, envejecimiento, diferentes condiciones o dispositivos no medidos.
3. Una curva aislada no determina necesariamente todos los parámetros: aplicar fijación/regularización y reportar identifiabilidad.
4. Mantener explícitos los orígenes de parámetros, condiciones y supuestos; evitar atribuir al fabricante inferencias del investigador.
5. No utilizar los mismos puntos para afirmar validación independiente. Reservar validación externa para curvas independientes bajo condiciones distintas o datos no empleados en el ajuste, explicando límites.
6. OTEKON: 4 curvas de tensión (298,15 K, 373,15 K, 1 atm y 5 atm), 16 inicios, TRF. El RMSE histórico 0,0014113700033 V es referencia documental, NO resultado de ejecución nueva.
7. Caso 65 kW: cuatro puntos de stack equivalente (180 A,150 V), (300 A,147 V), (420 A,140 V), (540 A,133 V), 210 celdas, 300 cm², según metadatos del EnergyMultimodel. **No confundir con una curva Horizon**. Horizon 220 celdas y 300 cm² hipotéticos es perfil aproximado con restricciones nominales, NO curva experimental Horizon.
8. No trasladar por defecto el coeficiente de incertidumbre de digitalización OTEKON (0,003 V) a otros datasets.
9. Gráficos deben usar el mismo núcleo de ecuaciones que la optimización.
10. No habilitar el Motor 2 hasta demostrar el hito 1.
