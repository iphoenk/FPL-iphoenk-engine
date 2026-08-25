
from __future__ import annotations

def fixture_score(fixture:dict, team_id:int):
    # Official FDR fallback. External Elo layer can override/augment later.
    if fixture.get("team_h")==team_id:
        return fixture.get("team_h_difficulty",3)
    if fixture.get("team_a")==team_id:
        return fixture.get("team_a_difficulty",3)
    return None

def next_fixtures(fixtures:list[dict], team_id:int, n:int=5):
    upcoming=[]
    for f in fixtures:
        if f.get("finished"): continue
        if team_id not in {f.get("team_h"),f.get("team_a")}: continue
        upcoming.append({
            "event":f.get("event"),"kickoff_time":f.get("kickoff_time"),
            "home":f.get("team_h")==team_id,
            "opponent":f.get("team_a") if f.get("team_h")==team_id else f.get("team_h"),
            "difficulty":fixture_score(f,team_id)
        })
    return upcoming[:n]
