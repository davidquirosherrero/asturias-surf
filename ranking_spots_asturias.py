#!/usr/bin/env python3
"""
Piloto: ranking en vivo de spots de surf en Asturias.

FUENTES DE DATOS
-----------------
1) Oleaje de fondo: boya de Cabo de Peñas (Puertos del Estado / AEMET),
   station=2242, code=3080042. Endpoint descubierto inspeccionando el JS
   del widget oficial (predChart.js -> getVerificationURL). Sin API key.

   Convención de dirección: MeanDir180 no usa la convención meteorológica
   estándar ("de dónde viene"). Deducido por lógica geográfica (la boya
   está en mar abierto al norte de la costa; un valor en cuadrante Sur
   sería físicamente imposible como procedencia) que MeanDir180 reporta
   "hacia dónde va". Se corrige sumando 180 grados.

2) Viento local: AEMET OpenData, endpoint "observación convencional /
   todas" (https://opendata.aemet.es/opendata/api/observacion/
   convencional/todas). Devuelve TODAS las estaciones de España en una
   sola llamada; se filtra por idema. Aquí la dirección (dv) SÍ es la
   convención meteorológica estándar ("de dónde viene"), no hace falta
   corregirla.

   REQUIERE API KEY GRATUITA. Registro en:
   https://opendata.aemet.es/centrodedescargas/altaUsuario
   Pega la clave en la variable de entorno AEMET_API_KEY, o en la
   constante AEMET_API_KEY de abajo.

DECISIONES TOMADAS SIN CONSULTAR (a revisar cuando vuelvas):
- Cada spot se ha asociado a la estación AEMET terrestre más cercana en
  línea recta, no necesariamente la más representativa del viento real
  en la rompiente (el viento en costa puede diferir del de una estación
  1-2 km tierra adentro). Es una aproximación de piloto, no un dato
  validado.
- El "viento offshore ideal" de cada spot se ha calculado como la
  dirección opuesta a la dirección de swell óptima (asunción geométrica
  simple: playa recta perpendicular al swell). Para Tapia se ha
  sobreescrito con NE, según lo descrito explícitamente en las guías de
  surf (la orientación de la costa occidental hace que el NE entre de
  lado/terral ahí, al revés que en el resto de Asturias).
- Si no hay AEMET_API_KEY configurada, el script sigue funcionando SOLO
  con oleaje (como el piloto original), sin viento, y lo avisa.
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------
AEMET_API_KEY = os.environ.get("AEMET_API_KEY", "")  # <-- pega tu clave aquí o via env var

BUOYS = {
    "cabo_penas": {"station": 2242, "nombre": "Cabo de Peñas"},
    "estaca_bares": {"station": 2244, "nombre": "Estaca de Bares"},
    "bilbao_vizcaya": {"station": 2136, "nombre": "Bilbao-Vizcaya"},
}
BUOY_URL = (
    "https://poem.puertos.es/portus/StationData"
    "?code={station}&params=Hm0,Tp,MeanDir180&from={dfrom}@0000&to={dto}@2359"
)
AEMET_TODAS_URL = "https://opendata.aemet.es/opendata/api/observacion/convencional/todas"

# ---------------------------------------------------------------------
# TABLA DE SPOTS
# idema = estación AEMET más cercana (ver lista completa de Asturias:
#   Cabo Peñas=1210X, Avilés=1212E, Gijón Musel=1208H, Cabo Busto=1283U,
#   Castropol=1331A, Colunga=1203D, Llanes=1183X)
# ---------------------------------------------------------------------
SPOTS = [
    {"name": "Tapia de Casariego", "boya": "estaca_bares", "lat": 43.5667, "lon": -6.942, "dir_optima": 315, "tolerancia": 60,
     "idema": "1331A", "viento_offshore": 45,
     "nota": "Orientación occidental: el NE es offshore/lateral aquí, al revés que en el resto de Asturias"},
    {"name": "Frejulfe", "boya": "estaca_bares", "lat": 43.5590, "lon": -6.687, "dir_optima": 315, "tolerancia": 30,
     "idema": "1283U", "viento_offshore": 135,
     "nota": "Mejor a 4-6 pies con NW"},
    {"name": "Playa de Otur", "boya": "estaca_bares", "lat": 43.553, "lon": -6.597, "dir_optima": 315, "tolerancia": 50,
     "idema": "1283U", "viento_offshore": 180,
     "nota": "\"Brutal Beach\": surfable con cualquier marea, muy consistente todo el año"},
    {"name": "Playa de Cueva", "boya": "estaca_bares", "lat": 43.550, "lon": -6.469, "dir_optima": 315, "tolerancia": 25,
     "idema": "1283U", "viento_offshore": 135,
     "nota": "Desembocadura del Esva, corrientes fuertes; solo funciona de vez en cuando"},
    {"name": "Playa de Aguilar", "boya": "estaca_bares", "lat": 43.5480, "lon": -6.098, "dir_optima": 315, "tolerancia": 45,
     "idema": "1212E", "viento_offshore": 135,
     "nota": "Olas nobles, buena para iniciación"},
    {"name": "Salinas / Espartal", "boya": "cabo_penas", "lat": 43.5870, "lon": -5.993, "dir_optima": 315, "tolerancia": 60,
     "idema": "1212E", "viento_offshore": 135,
     "nota": "Muy consistente, funciona con poco mar"},
    {"name": "Playón de Bayas", "boya": "cabo_penas", "lat": 43.5910, "lon": -6.035, "dir_optima": 315, "tolerancia": 45,
     "idema": "1212E", "viento_offshore": 135,
     "nota": "Funciona incluso en meses pequeños de verano"},
    {"name": "Bañugues", "boya": "cabo_penas", "lat": 43.6060, "lon": -5.766, "dir_optima": 315, "tolerancia": 35,
     "idema": "1210X", "viento_offshore": 135,
     "nota": "Condiciones particulares, exige NW limpio"},
    {"name": "Xagó", "boya": "cabo_penas", "lat": 43.6050, "lon": -5.798, "dir_optima": 315, "tolerancia": 30,
     "idema": "1210X", "viento_offshore": 135,
     "nota": "Potente, mejor en marea media-alta"},
    {"name": "San Lorenzo", "boya": "cabo_penas", "lat": 43.5450, "lon": -5.642, "dir_optima": 315, "tolerancia": 40,
     "idema": "1208H", "viento_offshore": 135,
     "nota": "Urbana, accesible, moderada"},
    {"name": "Rodiles", "boya": "bilbao_vizcaya", "lat": 43.5320, "lon": -5.381, "dir_optima": 315, "tolerancia": 25,
     "idema": "1204X", "viento_offshore": 135,
     "nota": "Desembocadura, marea baja-media subiendo, muy técnico"},
    {"name": "Vega", "boya": "bilbao_vizcaya", "lat": 43.4600, "lon": -5.043, "dir_optima": 315, "tolerancia": 50,
     "idema": "1204X", "viento_offshore": 135,
     "nota": "Extensa y muy abierta al Cantábrico, aguanta bien"},
    {"name": "Santa Marina", "boya": "bilbao_vizcaya", "lat": 43.4650, "lon": -5.057, "dir_optima": 10, "tolerancia": 40,
     "idema": "1204X", "viento_offshore": 190,
     "nota": "Orientada NE, abrigada de todo salvo viento Norte"},
    {"name": "Torimbia", "boya": "bilbao_vizcaya", "lat": 43.4630, "lon": -4.845, "dir_optima": 315, "tolerancia": 40,
     "idema": "1183X", "viento_offshore": 135,
     "nota": "Cala más resguardada, mejor con mar moderada"},
    {"name": "San Antolín", "boya": "bilbao_vizcaya", "lat": 43.4300, "lon": -4.79, "dir_optima": 315, "tolerancia": 45,
     "idema": "1183X", "viento_offshore": 135,
     "nota": "Muy abierta, aguanta mucha mar"},
]


def fetch_buoy_data(station, hours_back=30):
    now = datetime.now(timezone.utc)
    dfrom = (now - timedelta(hours=hours_back)).strftime("%Y%m%d")
    dto = now.strftime("%Y%m%d")
    url = BUOY_URL.format(station=station, dfrom=dfrom, dto=dto)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    readings = data[1]
    if not readings:
        raise RuntimeError("La boya no ha devuelto lecturas en ese rango.")
    return readings


def latest_reading(readings):
    ts, hm0, tp, mean_dir_180 = readings[-1]
    procedencia = (mean_dir_180[0] + 180) % 360
    return {
        "timestamp": datetime.fromtimestamp(ts, timezone.utc),
        "hm0": hm0[0],
        "tp": tp[0],
        "dir_procedencia": procedencia,
    }


def fetch_all_buoys():
    """
    Devuelve dict {boya_key: reading_dict} con la última lectura de cada
    una de las 3 boyas en BUOYS. Si una boya falla, se omite (no rompe
    el resto) y se avisa por stdout.
    """
    readings_by_buoy = {}
    for key, info in BUOYS.items():
        try:
            readings = fetch_buoy_data(info["station"])
            readings_by_buoy[key] = latest_reading(readings)
        except (urllib.error.URLError, RuntimeError, json.JSONDecodeError) as e:
            print(f"AVISO: fallo al leer la boya {info['nombre']} ({e}). Se omite.")
    if not readings_by_buoy:
        raise RuntimeError("Ninguna de las 3 boyas ha respondido.")
    return readings_by_buoy


def fetch_aemet_wind(api_key):
    """
    Devuelve dict {idema: {"vv": m/s, "dv": grados}} con la última
    observación de TODAS las estaciones de España. None si falla o no
    hay api_key.
    """
    if not api_key:
        return None
    try:
        step1_url = f"{AEMET_TODAS_URL}?api_key={api_key}"
        req1 = urllib.request.Request(step1_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req1, timeout=15) as resp:
            meta = json.loads(resp.read().decode("utf-8"))
        if "datos" not in meta:
            print(f"AVISO: AEMET no devolvió 'datos'. Respuesta: {meta}")
            return None
        req2 = urllib.request.Request(meta["datos"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req2, timeout=15) as resp:
            raw = resp.read().decode("latin-1")  # AEMET suele venir en latin-1
        estaciones = json.loads(raw)
    except (urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
        print(f"AVISO: no se pudo obtener viento de AEMET ({e}). Sigo solo con oleaje.")
        return None

    # El endpoint "todas" trae ~12 registros históricos por estación, no 1.
    # Nos quedamos con el de fecha (fint) más reciente por idema.
    wind_by_idema = {}
    for est in estaciones:
        idema = est.get("idema")
        if idema and "vv" in est and "dv" in est and "fint" in est:
            actual = wind_by_idema.get(idema)
            if actual is None or est["fint"] > actual["fint"]:
                wind_by_idema[idema] = {
                    "vv": est["vv"],
                    "dv": est["dv"],
                    "fint": est["fint"],
                    "ta": est.get("ta"),      # temperatura del aire, °C
                    "vmax": est.get("vmax"),  # ráfaga máxima, m/s
                }
    return wind_by_idema


def angular_diff(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def reading_for_spot(spot, readings_by_buoy):
    """Lectura de la boya asignada al spot; si esa boya falló, usa cualquier
    otra disponible (preferentemente Cabo de Peñas, por ser la más central).
    Devuelve (reading, boya_key_realmente_usada, es_fallback)."""
    r = readings_by_buoy.get(spot["boya"])
    if r is not None:
        return r, spot["boya"], False
    if "cabo_penas" in readings_by_buoy:
        return readings_by_buoy["cabo_penas"], "cabo_penas", True
    fallback_key = next(iter(readings_by_buoy))
    return readings_by_buoy[fallback_key], fallback_key, True


def score_spot(spot, reading, wind_by_idema):
    diff = angular_diff(reading["dir_procedencia"], spot["dir_optima"])
    dir_score = max(0, 100 - (diff / spot["tolerancia"]) * 100)

    h = reading["hm0"]
    if h < 0.3:
        height_score = 20
    elif h <= 2.0:
        height_score = 60 + (h - 0.3) / 1.7 * 40
    elif h <= 3.0:
        height_score = 100 - (h - 2.0) * 30
    else:
        height_score = 40

    tp = reading["tp"]
    period_score = min(100, max(0, (tp - 4) / 8 * 100))

    wind_info = wind_by_idema.get(spot["idema"]) if wind_by_idema else None

    if wind_info is None:
        # Sin viento disponible: repartimos su peso entre dirección/altura/periodo
        total = dir_score * 0.55 + height_score * 0.25 + period_score * 0.20
        return round(total, 1), None

    wind_diff = angular_diff(wind_info["dv"], spot["viento_offshore"])
    wind_dir_score = max(0, 100 - (wind_diff / 60) * 100)
    # Penalización por viento fuerte, independientemente de la dirección
    vv_kmh = wind_info["vv"] * 3.6
    if vv_kmh > 35:
        wind_dir_score *= 0.4
    elif vv_kmh > 25:
        wind_dir_score *= 0.7

    total = (dir_score * 0.40 + height_score * 0.20 + period_score * 0.15
             + wind_dir_score * 0.25)
    return round(total, 1), {
        "vv_kmh": round(vv_kmh, 1),
        "dv": wind_info["dv"],
        "ta": wind_info.get("ta"),
        "vmax_kmh": round(wind_info["vmax"] * 3.6, 1) if wind_info.get("vmax") is not None else None,
    }


def build_json_output(readings_by_buoy, wind_by_idema):
    """Construye la estructura que consume ranking_spots_asturias.html vía fetch()."""
    spots_out = []
    for spot in SPOTS:
        r, boya_usada, es_fallback = reading_for_spot(spot, readings_by_buoy)
        score, wind = score_spot(spot, r, wind_by_idema)
        nombre_boya = BUOYS[boya_usada]["nombre"] + (" (fallback)" if es_fallback else "")
        spots_out.append({
            "name": spot["name"],
            "lat": spot["lat"],
            "lon": spot["lon"],
            "score": score,
            "boya": nombre_boya,
            "hm0": r["hm0"],
            "tp": r["tp"],
            "swell_dir": round(r["dir_procedencia"]),
            "wind_kmh": wind["vv_kmh"] if wind else None,
            "wind_dir": wind["dv"] if wind else None,
            "wind_gust_kmh": wind["vmax_kmh"] if wind else None,
            "temp_c": wind["ta"] if wind else None,
            "nota": spot["nota"],
        })
    return {
        "buoys": {
            key: {
                "nombre": BUOYS[key]["nombre"],
                "hm0": r["hm0"],
                "tp": r["tp"],
                "dir": round(r["dir_procedencia"]),
                "ts": r["timestamp"].isoformat(),
            }
            for key, r in readings_by_buoy.items()
        },
        "spots": spots_out,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    readings_by_buoy = fetch_all_buoys()
    wind_by_idema = fetch_aemet_wind(AEMET_API_KEY)

    print(f"\nBoyas leídas: {', '.join(BUOYS[k]['nombre'] for k in readings_by_buoy)}")
    for key, r in readings_by_buoy.items():
        print(f"  {BUOYS[key]['nombre']:<16} Hm0={r['hm0']} m | Tp={r['tp']} s | "
              f"dir={r['dir_procedencia']:.0f}° | {r['timestamp']} UTC")
    if wind_by_idema is None:
        print("(Sin datos de viento AEMET -- configura AEMET_API_KEY para incluirlo)\n")
    else:
        print(f"(Viento AEMET incorporado, {len(wind_by_idema)} estaciones recibidas)\n")

    def score_with_reading(spot):
        r, _, _ = reading_for_spot(spot, readings_by_buoy)
        return (spot,) + score_spot(spot, r, wind_by_idema)

    ranked = sorted((score_with_reading(spot) for spot in SPOTS), key=lambda x: x[1], reverse=True)

    print(f"{'Spot':<22} {'Score':>6}   {'Boya':<16} {'Viento':<14} Nota")
    print("-" * 110)
    for spot, score, wind in ranked:
        wind_str = f"{wind['vv_kmh']}km/h {wind['dv']:.0f}°" if wind else "n/d"
        print(f"{spot['name']:<22} {score:>5.1f}   {BUOYS[spot['boya']]['nombre']:<16} {wind_str:<14} {spot['nota']}")

    output = build_json_output(readings_by_buoy, wind_by_idema)
    with open("ranking.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\nEscrito ranking.json")


if __name__ == "__main__":
    main()
