import os
import json
import math
import uuid
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, render_template

app = Flask(__name__, static_folder='static', template_folder='templates')

# ---------------------------------------------------------------------------
# Data loading & scoring
# ---------------------------------------------------------------------------

DATA = None  # global DataFrame loaded at startup


def haversine(lat1, lon1, lat2, lon2):
    """Distance between two lat/lon points in meters."""
    R = 6371000
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def compute_teams_ready_score(row):
    """0-100 weighted score: signal 30%, latency 25%, jitter 15%, loss 15%, download 15%."""
    signal = row['signal_pct'] * 0.30

    lat = row['latency_ms']
    if lat <= 20:
        lat_s = 25.0
    elif lat <= 50:
        lat_s = 25.0 - (lat - 20) * 0.5
    else:
        lat_s = 10.0

    jit = row['jitter_ms']
    if jit <= 5:
        jit_s = 15.0
    elif jit <= 20:
        jit_s = 15.0 - (jit - 5) * 0.667
    else:
        jit_s = 5.0

    loss = row['packet_loss_pct']
    if loss == 0:
        loss_s = 15.0
    elif loss <= 30:
        loss_s = 15.0 - loss * 0.5
    else:
        loss_s = 0.0

    dl = row['download_mbps']
    if pd.isna(dl):
        dl_s = 0.0
    elif dl >= 50:
        dl_s = 15.0
    else:
        dl_s = (dl / 50.0) * 15.0

    return round(signal + lat_s + jit_s + loss_s + dl_s, 1)


SYNTHETIC_LOCATIONS = [
    ("McComas Hall", 37.220655, -80.421332, 0.85),
    ("Payne Hall", 37.225678, -80.419804, 0.78),
    ("Orange Loop", 37.229990, -80.426553, 0.70),
    ("Burruss Hall", 37.228623, -80.423225, 0.90),
    ("Eggleston Quad", 37.227134, -80.419530, 0.75),
    ("Newman Library", 37.228369, -80.418996, 0.88),
    ("Drillfield", 37.227782, -80.422278, 0.65),
    ("Squires Student Center", 37.229279, -80.417411, 0.90),
    ("Torgersen Hall", 37.229797, -80.420767, 0.95),
    ("Upper Quad", 37.231051, -80.419945, 0.80),
    ("Data and Decision Sciences", 37.231249, -80.427444, 0.85),
    ("Moss Arts Center", 37.231512, -80.417846, 0.82),
    ("Goodwin Hall", 37.232110, -80.425480, 0.92),
    ("Pamplin Hall", 37.228115, -80.424900, 0.78),
    ("Rec Sports Field House", 37.215252, -80.418961, 0.60),
    ("English Field", 37.218447, -80.424554, 0.55),
    ("Duck Pond Lot", 37.220611, -80.428841, 0.50),
    ("Litton Reaves", 37.221924, -80.423678, 0.72),
    ("Hutcheson Hall", 37.225348, -80.423706, 0.76),
    ("Lane Stadium", 37.219816, -80.418000, 0.85),
    ("Ag Quad", 37.225935, -80.417331, 0.74),
    ("Slusher Quad", 37.225700, -80.421762, 0.70),
    ("Vet Med", 37.217654, -80.426913, 0.60),
    ("Dietrick Quad", 37.223793, -80.420248, 0.68),
    ("Pritchard Quad", 37.224927, -80.419078, 0.75),
]

# Campus reference locations — every data point is assigned the nearest one
CAMPUS_LOCATIONS = [
    ("Bus Stop Bay 1",            37.232077, -80.424637),
    ("Bus Stop Bay 5",            37.231420, -80.424917),
    ("McComas Hall",              37.220655, -80.421332),
    ("Payne Hall",                37.225678, -80.419804),
    ("Orange Loop",               37.229990, -80.426553),
    ("Burruss Hall",              37.228623, -80.423225),
    ("Eggleston Quad",            37.227134, -80.419530),
    ("Newman Library",            37.228369, -80.418996),
    ("Drillfield",                37.227782, -80.422278),
    ("Squires",                   37.229279, -80.417411),
    ("Torgersen Hall",            37.229797, -80.420767),
    ("Upper Quad",                37.231051, -80.419945),
    ("Data and Decision Sciences",37.231249, -80.427444),
    ("Moss Arts Center",          37.231512, -80.417846),
    ("Goodwin Hall",              37.232110, -80.425480),
    ("Pamplin Hall",              37.228115, -80.424900),
    ("Rec Sports Field House",    37.215252, -80.418961),
    ("English Field",             37.218447, -80.424554),
    ("Duck Pond Lot",             37.220611, -80.428841),
    ("Litton Reaves",             37.221924, -80.423678),
    ("Hutcheson Hall",            37.225348, -80.423706),
    ("Lane Stadium",              37.219816, -80.418000),
    ("Ag Quad",                   37.225935, -80.417331),
    ("Slusher Quad",              37.225700, -80.421762),
    ("Vet Med",                   37.217654, -80.426913),
    ("Dietrick Quad",             37.223793, -80.420248),
    ("Pritchard Quad",            37.224927, -80.419078),
    ("Turner Place",              37.230876, -80.422393),
]

def nearest_campus_location(lat, lon):
    """Return the name of the nearest campus reference location."""
    best_name, best_dist = None, float('inf')
    for name, c_lat, c_lon in CAMPUS_LOCATIONS:
        d = haversine(lat, lon, c_lat, c_lon)
        if d < best_dist:
            best_dist, best_name = d, name
    return best_name


def generate_synthetic(real_df):
    """Generate synthetic WiFi data calibrated to the real distribution."""
    np.random.seed(42)
    def _std(col):
        s = real_df[col].std()
        return s if pd.notna(s) and s > 0 else 10.0

    stats = {
        'signal_pct':       (real_df['signal_pct'].mean(),       _std('signal_pct')),
        'rssi':             (real_df['estimated_rssi_dbm'].mean(), _std('estimated_rssi_dbm')),
        'latency_ms':       (real_df['latency_ms'].mean(),       _std('latency_ms')),
        'jitter_ms':        (real_df['jitter_ms'].mean(),        _std('jitter_ms')),
        'packet_loss_pct':  (real_df['packet_loss_pct'].mean(),  _std('packet_loss_pct')),
        'download_mbps':    (real_df['download_mbps'].mean(),    _std('download_mbps')),
        'upload_mbps':      (real_df['upload_mbps'].mean(),      _std('upload_mbps')),
    }
    rows = []
    base_time = datetime(2026, 9, 19, 9, 0, 0)
    for loc_name, lat, lon, qm in SYNTHETIC_LOCATIONS:
        for band in ["2.4 GHz", "5 GHz"]:
            for _ in range(np.random.randint(3, 6)):
                signal = int(np.clip(np.random.normal(stats['signal_pct'][0] * qm, stats['signal_pct'][1]), 20, 100))
                rssi   = round(np.clip(np.random.normal(stats['rssi'][0] - (1 - qm) * 10, stats['rssi'][1]), -90, -40), 1)
                lat_v  = round(np.clip(np.random.normal(stats['latency_ms'][0] / qm, stats['latency_ms'][1]), 3, 80), 1)
                jit    = round(np.clip(np.random.normal(stats['jitter_ms'][0] / qm, stats['jitter_ms'][1]), 0, 40), 2)
                loss   = round(np.clip(np.random.normal(stats['packet_loss_pct'][0], stats['packet_loss_pct'][1]), 0, 30), 1)
                dl     = round(np.clip(np.random.normal(stats['download_mbps'][0] * qm, stats['download_mbps'][1]), 0, 200), 2) if np.random.random() > 0.2 else None
                ul     = round(np.clip(np.random.normal(stats['upload_mbps'][0] * qm, stats['upload_mbps'][1]), 0, 150), 2) if np.random.random() > 0.15 else None
                ch     = int(np.random.choice([6, 11, 36, 44, 48, 144]) if band == "5 GHz" else np.random.choice([1, 6, 11]))
                ts     = base_time + timedelta(minutes=int(np.random.randint(0, 720)))
                rows.append({
                    'test_id': str(uuid.uuid4()), 'timestamp': ts.isoformat(),
                    'location_name': loc_name,
                    'latitude':  lat + np.random.uniform(-0.0001, 0.0001),
                    'longitude': lon + np.random.uniform(-0.0001, 0.0001),
                    'source': 'synthetic', 'ssid': 'eduroam', 'bssid': '',
                    'signal_pct': signal, 'estimated_rssi_dbm': rssi,
                    'band': band, 'channel': ch, 'radio_type': '802.11ax',
                    'rx_link_mbps': float(np.random.choice([34, 59, 172, 206, 260, 287, 325, 413, 574])),
                    'tx_link_mbps': float(np.random.choice([34, 59, 59, 275, 287, 325, 413, 574])),
                    'wifi_interface': 'Wi-Fi', 'adapter_description': 'Intel(R) Wi-Fi 7 BE201 320MHz',
                    'ping_host': '1.1.1.1', 'latency_ms': lat_v, 'jitter_ms': jit,
                    'packet_loss_pct': loss, 'ping_packets_received': 10 - int(loss > 0),
                    'ping_packets_sent': 10, 'download_mbps': dl, 'upload_mbps': ul,
                    'data_source': 'synthetic',
                })
    return pd.DataFrame(rows)


def load_data():
    """Load real data from embedded JSON, generate synthetic data, compute scores."""
    global DATA

    # Load real data from embedded JSON file shipped with the app
    real_path = os.path.join(os.path.dirname(__file__), 'embedded_data.json')
    try:
        with open(real_path, 'r') as f:
            records = json.load(f)
        real_df = pd.DataFrame(records)
        real_df['data_source'] = 'real'
        print(f"Loaded {len(real_df)} real rows from embedded_data.json")
    except Exception as e:
        print(f"Could not load embedded data: {e}")
        real_df = pd.DataFrame([{
            'location_name': 'Maroon Bay 1', 'latitude': 37.232077, 'longitude': -80.424637,
            'signal_pct': 90, 'estimated_rssi_dbm': -55.0, 'band': '5 GHz',
            'latency_ms': 12.5, 'jitter_ms': 4.0, 'packet_loss_pct': 0.0,
            'download_mbps': 22.8, 'upload_mbps': None, 'data_source': 'real',
        }])

    synth_df = generate_synthetic(real_df)
    print(f"Generated {len(synth_df)} synthetic rows")
    all_df = pd.concat([real_df, synth_df], ignore_index=True)
    all_df['teams_ready_score'] = all_df.apply(compute_teams_ready_score, axis=1)
    # Reassign every data point to its nearest campus reference location
    all_df['location_name'] = all_df.apply(
        lambda r: nearest_campus_location(r['latitude'], r['longitude']), axis=1)
    DATA = all_df
    print(f"Total: {len(DATA)} rows, avg score {DATA['teams_ready_score'].mean():.1f}")
    return DATA


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/locations')
def get_locations():
    """Return campus reference locations with avg scores as GeoJSON."""
    features = []
    for name, lat, lon in CAMPUS_LOCATIONS:
        loc_data = DATA[DATA['location_name'] == name] if DATA is not None else None
        avg_score = float(loc_data['teams_ready_score'].mean()) if loc_data is not None and len(loc_data) > 0 else None
        avg_signal = float(loc_data['signal_pct'].mean()) if loc_data is not None and len(loc_data) > 0 else None
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
            'properties': {
                'name': name,
                'teams_ready_score': round(avg_score, 1) if avg_score is not None else None,
                'signal_pct': round(avg_signal, 1) if avg_signal is not None else None,
            },
        })
    return jsonify({'type': 'FeatureCollection', 'features': features})


@app.route('/api/coverage')
def get_coverage():
    """Return all coverage points as GeoJSON FeatureCollection."""
    if DATA is None:
        return jsonify({'error': 'data not loaded'}), 500
    features = []
    for _, r in DATA.iterrows():
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [float(r['longitude']), float(r['latitude'])]},
            'properties': {
                'location_name': str(r['location_name']),
                'data_source': str(r['data_source']),
                'teams_ready_score': float(r['teams_ready_score']),
                'signal_pct': int(r['signal_pct']) if pd.notna(r['signal_pct']) else None,
                'estimated_rssi_dbm': float(r['estimated_rssi_dbm']) if pd.notna(r['estimated_rssi_dbm']) else None,
                'band': str(r['band']),
                'latency_ms': float(r['latency_ms']) if pd.notna(r['latency_ms']) else None,
                'jitter_ms': float(r['jitter_ms']) if pd.notna(r['jitter_ms']) else None,
                'packet_loss_pct': float(r['packet_loss_pct']) if pd.notna(r['packet_loss_pct']) else None,
                'download_mbps': float(r['download_mbps']) if pd.notna(r['download_mbps']) else None,
                'upload_mbps': float(r['upload_mbps']) if pd.notna(r['upload_mbps']) else None,
            },
        })
    return jsonify({'type': 'FeatureCollection', 'features': features})


@app.route('/api/lookup', methods=['POST'])
def lookup():
    """Given lat/lon, return connectivity at nearest data points."""
    if DATA is None:
        return jsonify({'error': 'data not loaded'}), 500
    req = request.get_json(force=True)
    ulat, ulon = req.get('latitude'), req.get('longitude')
    if ulat is None or ulon is None:
        return jsonify({'error': 'latitude and longitude required'}), 400

    dists = DATA.apply(lambda r: haversine(ulat, ulon, r['latitude'], r['longitude']), axis=1)
    nearest_idx = dists.idxmin()
    nearest = DATA.loc[nearest_idx]
    near = DATA[dists <= 100]
    avg_score = float(near['teams_ready_score'].mean()) if len(near) > 0 else float(nearest['teams_ready_score'])

    if avg_score >= 80:
        quality, msg = 'excellent', 'Great signal here! You can take calls without issues.'
    elif avg_score >= 60:
        quality, msg = 'good', 'Signal is decent. Calls should work fine.'
    elif avg_score >= 40:
        quality, msg = 'poor', 'Weak signal here. Consider moving for better connectivity.'
    else:
        quality, msg = 'bad', 'Poor connectivity. Move to a better location for calls.'

    return jsonify({
        'location': {'latitude': ulat, 'longitude': ulon,
                     'nearest_point': str(nearest['location_name']),
                     'distance_meters': round(float(dists[nearest_idx]), 1)},
        'connectivity': {'teams_ready_score': round(avg_score, 1), 'quality': quality,
                         'message': msg,
                         'signal_pct': int(nearest['signal_pct']) if pd.notna(nearest['signal_pct']) else None,
                         'latency_ms': float(nearest['latency_ms']) if pd.notna(nearest['latency_ms']) else None,
                         'download_mbps': float(nearest['download_mbps']) if pd.notna(nearest['download_mbps']) else None,
                         'band': str(nearest['band'])},
    })


@app.route('/api/recommend', methods=['POST'])
def recommend_spots():
    if DATA is None:
        return jsonify({'error': 'data not loaded'}), 500
        
    req = request.get_json(force=True)
    lat = req.get('latitude')
    lon = req.get('longitude')
    
    if lat is None or lon is None:
        return jsonify({'error': 'latitude and longitude required'}), 400

    # 1. Calculate distance for all points
    df = DATA.copy()
    df['distance_meters'] = df.apply(lambda r: haversine(lat, lon, r['latitude'], r['longitude']), axis=1)

    # 2. Filter for points within 100 meters (or fallback to closest if none are strictly under 100m)
    nearby_df = df[df['distance_meters'] <= 100].copy()
    if nearby_df.empty:
        # Fallback to the top 15 closest if user is in a dead zone far from anything
        nearby_df = df.nsmallest(15, 'distance_meters').copy()

    # 3. Ensure diversity: Group by location/building, taking the highest score per building
    # (Assuming location_name represents the building or zone name)
    best_per_building = nearby_df.sort_values(by=['teams_ready_score', 'distance_meters'], ascending=[False, True])
    best_per_building = best_per_building.drop_duplicates(subset=['location_name']).head(5)

    recommendations = []
    for _, row in best_per_building.iterrows():
        recommendations.append({
            "location_name": str(row['location_name']),
            "latitude": float(row['latitude']),
            "longitude": float(row['longitude']),
            "teams_ready_score": float(row['teams_ready_score']),
            "signal_pct": float(row['signal_pct']),
            "latency_ms": float(row['latency_ms']),
            "distance_meters": int(row['distance_meters']),
            "data_source": str(row['data_source'])
        })

    # 4. Craft dynamic agent message
    if not recommendations:
        agent_msg = "⚠️ No stable connection zones found nearby. Try moving to open campus paths."
    else:
        top_spot = recommendations[0]
        agent_msg = f"💡 Best nearby option: **{top_spot['location_name']}** ({top_spot['distance_meters']}m away, Score: {top_spot['teams_ready_score']}/100). Distinct building zones mapped below."

    return jsonify({
        "agent_message": agent_msg,
        "recommendations": recommendations
    })

def _agent_message(recs):
    if not recs:
        return "No better spots found nearby. Consider checking a different area of campus."
    best = recs[0]
    if best['distance_meters'] < 100:
        return (f"✅ Your current area looks good! Best nearby: {best['location_name']} "
                f"(score: {best['teams_ready_score']})")
    return (f"📍 For better connectivity, head to {best['location_name']} "
            f"({best['distance_meters']:.0f}m away, score: {best['teams_ready_score']}). "
            f"You'll get ~{best['signal_pct']:.0f}% signal and ~{best['latency_ms']:.0f}ms latency.")


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'data_rows': len(DATA) if DATA is not None else 0})


# Load data at import time so the first request is fast
DATA = load_data()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
