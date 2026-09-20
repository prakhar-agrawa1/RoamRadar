import os
import json
import requests
import pandas as pd

def create_tf_serving_json(data):
    return {'inputs': {name: data[name].tolist() for name in data.keys()} if isinstance(data, dict) else data.tolist()}

def score_model(dataset):
    url = 'https://dbc-49834d75-ab28.cloud.databricks.com/serving-endpoints/RoamRadar-Agent/invocations'
    # Use environment variables securely, do not hardcode the token
    headers = {'Authorization': f'Bearer {os.environ.get("DATABRICKS_TOKEN")}', 'Content-Type': 'application/json'}
    
    ds_dict = {'dataframe_split': dataset.to_dict(orient='split')} if isinstance(dataset, pd.DataFrame) else create_tf_serving_json(dataset)
    data_json = json.dumps(ds_dict, allow_nan=True)
    
    response = requests.request(method='POST', headers=headers, url=url, data=data_json)
    if response.status_code != 200:
        raise Exception(f'Request failed with status {response.status_code}, {response.text}')
    return response.json()

if __name__ == '__main__':
    # 1. Set your new token here temporarily for testing, or export it in your terminal
    os.environ["DATABRICKS_TOKEN"] = "dapiaf52f74f0b0beefba37f1c245d580bd5"

    # 2. Create the test payload
    test_data = pd.DataFrame({
        "lat": [37.2284],
        "lon": [-80.4234],
        "meeting_soon": [True]
    })

    # 3. Execute and print
    try:
        result = score_model(test_data)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error testing endpoint: {e}")