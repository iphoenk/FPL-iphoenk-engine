from pathlib import Path
import json

path = Path('config/release_manifest.json')
payload = json.loads(path.read_text(encoding='utf-8'))
payload.setdefault('registries', {})['services'] = 'fpl_v4_9_6_microservice_registry_v13'
payload['registries']['contracts'] = 'fpl_v4_9_6_service_contracts_v10'
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
