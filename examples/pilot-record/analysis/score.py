"""Reproducible, dependency-free forecast scoring on observed dates."""
import csv,json,math,sys
rows=list(csv.DictReader(open(sys.argv[1],encoding="utf-8")))
column="forecast_"+sys.argv[2].lower()
valid=[r for r in rows if r.get("observation") and r.get(column)]
errors=[float(r[column])-float(r["observation"]) for r in valid]
print(json.dumps({"experiment":sys.argv[2],"sample_size":len(errors),
 "rmse":math.sqrt(sum(e*e for e in errors)/len(errors)),"bias":sum(errors)/len(errors),
 "dates":[r["date"] for r in valid],"errors":errors},indent=2))
