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
    ("Torgersen Bridge",       37.2295, -80.4234, 0.95),
    ("Burruss Hall Steps",     37.2296, -80.4259, 0.85),
    ("Newman Library Front",  37.2299, -80.4238, 0.80),
    ("Drillfield North",      37.2302, -80.4252, 0.65),
    ("Drillfield South",      37.2285, -80.4252, 0.55),
    ("Squires Student Center", 37.2291, -80.4238, 0.90),
    ("Henderson Hall",        37.2307, -80.4215, 0.75),
    ("Patton Hall",           37.2303, -80.4220, 0.70),
    ("Goodwin Hall",          37.2297, -80.4231, 0.85),
    ("War Memorial Chapel",  37.2311, -80.4255, 0.60),
    ("Johnston Student Center", 37.2288, -80.4244, 0.88),
    ("Dietrick Lawn",         37.2283, -80.4261, 0.50),
    ("Payne Hall",            37.2306, -80.4255, 0.78),
    ("Femoyer Hall",          37.2294, -80.4250, 0.82),
    ("D2 Dining",             37.2280, -80.4272, 0.45),
    ("Owens Hall",            37.2290, -80.4268, 0.72),
]


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
    DATA = all_df
    print(f"Total: {len(DATA)} rows, avg score {DATA['teams_ready_score'].mean():.1f}")
    return DATA


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


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
def recommend():
    """Given lat/lon, return nearby spots with better scores."""
    if DATA is None:
        return jsonify({'error': 'data not loaded'}), 500
    req = request.get_json(force=True)
    ulat, ulon = req.get('latitude'), req.get('longitude')
    min_score = req.get('min_score', 70)
    if ulat is None or ulon is None:
        return jsonify({'error': 'latitude and longitude required'}), 400

    loc_scores = DATA.groupby(['location_name', 'latitude', 'longitude']).agg(
        teams_ready_score=('teams_ready_score', 'mean'),
        signal_pct=('signal_pct', 'mean'),
        latency_ms=('latency_ms', 'mean'),
        download_mbps=('download_mbps', 'mean'),
        data_source=('data_source', 'first'),
    ).reset_index()
    loc_scores['distance_m'] = loc_scores.apply(
        lambda r: haversine(ulat, ulon, r['latitude'], r['longitude']), axis=1)
    better = loc_scores[loc_scores['teams_ready_score'] >= min_score].sort_values('teams_ready_score', ascending=False)
    nearby = better[better['distance_m'] <= 500].head(5)
    if nearby.empty:
        nearby = better.head(5)

    recs = []
    for _, r in nearby.iterrows():
        recs.append({
            'location_name': str(r['location_name']),
            'latitude': float(r['latitude']), 'longitude': float(r['longitude']),
            'teams_ready_score': round(float(r['teams_ready_score']), 1),
            'signal_pct': round(float(r['signal_pct']), 1),
            'latency_ms': round(float(r['latency_ms']), 1),
            'download_mbps': round(float(r['download_mbps']), 1) if pd.notna(r['download_mbps']) else None,
            'distance_meters': round(float(r['distance_m']), 1),
            'data_source': str(r['data_source']),
        })

    agent_msg = _agent_message(recs)
    return jsonify({'user_location': {'latitude': ulat, 'longitude': ulon},
                    'recommendations': recs, 'agent_message': agent_msg})


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
