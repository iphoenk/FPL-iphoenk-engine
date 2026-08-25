from __future__ import annotations
import argparse, json
from src.utils import DATA, read_json, parse_dt, utcnow
from src.sources.official_fpl import get_json
from src.engines.v4_backtest_store import persist_deadline_snapshot, reconcile_finished_gw


def snapshot_current()->dict:
    latest=read_json(DATA/'latest.json',{})
    pred=read_json(DATA/'predictions_v4.json',{})
    phase=latest.get('phase',{})
    gw=phase.get('planning_gw')
    deadline=phase.get('deadline_time')
    if not gw or not deadline:
        return {'status':'SKIP','reason':'no_planning_gw_or_deadline'}
    d=parse_dt(deadline)
    if not d or d<=utcnow():
        return {'status':'SKIP','reason':'deadline_not_future','gw':gw,'deadline_time':deadline}
    snap=persist_deadline_snapshot(int(gw),deadline,pred,latest.get('generated_at'))
    return {'status':'PASS','gw':gw,'deadline_time':deadline,'players':len(snap.get('players',[])),'model_version':snap.get('model_version')}


def reconcile_latest_finished()->dict:
    latest=read_json(DATA/'latest.json',{})
    gw=(latest.get('phase') or {}).get('last_finished_gw')
    if not gw:return {'status':'SKIP','reason':'no_finished_gw'}
    live,h=get_json(f'event/{int(gw)}/live/')
    if not live:return {'status':'SKIP','reason':'finished_live_unavailable','gw':gw,'health':h}
    result=reconcile_finished_gw(int(gw),live)
    if not result:return {'status':'SKIP','reason':'no_deadline_snapshot','gw':gw}
    metrics=((result.get('report') or {}).get('metrics') or {})
    return {'status':'PASS','gw':gw,'metrics':metrics,'model_version':result.get('model_version')}


def cycle()->dict:
    return {'snapshot':snapshot_current(),'reconciliation':reconcile_latest_finished()}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['snapshot','reconcile','cycle']);args=ap.parse_args()
    out=snapshot_current() if args.action=='snapshot' else reconcile_latest_finished() if args.action=='reconcile' else cycle()
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
