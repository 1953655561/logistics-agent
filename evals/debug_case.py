import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.synth.generator import build_case
from data.synth.scenarios import CASES
from src.engine import audit

cid = sys.argv[1] if len(sys.argv) > 1 else "IMP-0001"
case = [c for c in CASES if c["id"] == cid][0]
b = build_case(case)
r = audit(b["docs"])
print("VERDICT", r["verdict"], "expected", b["expected"]["verdict"])
for it in r["issues"]:
    print(f"  {it['rule_id']:8s} {it['severity']:5s} {it['field_path']:35s} {it['message']}")
print("rules !=PASS:", [(x.rule_id, x.conclusion, x.error) for x in r["rules"] if x.conclusion != "PASS"])
