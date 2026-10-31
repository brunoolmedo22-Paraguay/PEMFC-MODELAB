#!/usr/bin/env python3
"""Herramienta independiente para EVALUAR el resultado de un digitalizador.
No implementa reconocimiento automático; compara curvas ya extraídas con truth sintético.
Uso:
python handoff/verificacion/evaluar_extraccion.py --referencia handoff/fixtures/01_curva_simple_truth.csv --extraido salida.csv --curva "Curva A"
CSV extraído esperado: columnas current_density_A_cm2, voltage_V; otras columnas permitidas.
"""
import argparse
import csv
import math
from pathlib import Path

def load(path, trace=None):
    with open(path, newline='',encoding='utf-8-sig') as f:
        rows=list(csv.DictReader(f))
    out=[]
    for row in rows:
        if trace and 'curve_id' in row and row['curve_id']!=trace: continue
        try: x=float(row['current_density_A_cm2']); y=float(row['voltage_V'])
        except (KeyError,ValueError) as e: raise ValueError(f'{path}: CSV debe tener current_density_A_cm2 y voltage_V; {e}') from e
        if not math.isfinite(x) or not math.isfinite(y): raise ValueError('Non finite points')
        out.append((x,y))
    return sorted(out)

def interpolate(points,x):
    for (x0,y0),(x1,y1) in zip(points,points[1:]):
        if x0<=x<=x1 and x1>x0: return y0+(y1-y0)*(x-x0)/(x1-x0)
    raise ValueError('outside range')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--referencia',required=True)
    parser.add_argument('--extraido',required=True)
    parser.add_argument('--curva',default=None)
    args=parser.parse_args()
    ref=load(args.referencia,args.curva); got=load(args.extraido,args.curva)
    if len(ref)<4 or len(got)<4: raise SystemExit('Insufficient points (< 4)')
    lo=max(ref[0][0],got[0][0]); hi=min(ref[-1][0],got[-1][0]);
    inside=[(x,y) for x,y in ref if lo<=x<=hi]
    if len(inside)<4: raise SystemExit('Less than 4 overlapping reference points')
    residual=[interpolate(got,x)-y for x,y in inside]
    rmse=(sum(r*r for r in residual)/len(residual))**.5
    mae=sum(abs(r) for r in residual)/len(residual)
    coverage=(hi-lo)/(ref[-1][0]-ref[0][0])
    print(f'True points: {len(ref)}; extracted points: {len(got)}; overlap: {len(inside)}')
    print(f'RMSE [V]: {rmse:.7f}; MAE [V]: {mae:.7f}; X coverage: {coverage:.1%}')
    print('These are DIGITALIZATION errors, NOT PEMFC parameter fit errors.')
if __name__=='__main__': main()
