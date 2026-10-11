"""Candle-only EMA baseline, NOT full FlowPilot order-flow backtest.
CSV columns: time,open,high,low,close,volume. Closed candles only.
Signal at close, entry next open. Stop wins when TP and SL overlap intrabar.
Fixed 0.5% risk, fees/slippage on both legs, funding reserve. No fabricated input.
"""
import argparse,csv,json,math,random
from app.strategies.indicators import ema

def metrics(returns):
    if not returns:return {"trades":0,"win_rate":None,"profit_factor":None,"expectancy":None,"max_drawdown":None,"ci_mean_95":None}
    eq=peak=1.;dd=0.;curve=[]
    for r in returns:
        eq*=1+r;peak=max(peak,eq);dd=max(dd,1-eq/peak);curve.append(eq)
    wins=sum(r for r in returns if r>0);loss=-sum(r for r in returns if r<0)
    rng=random.Random(17);boot=sorted(sum(rng.choice(returns) for _ in returns)/len(returns) for _ in range(1000))
    return dict(trades=len(returns),win_rate=sum(r>0 for r in returns)/len(returns),profit_factor=wins/loss if loss else None,expectancy=sum(returns)/len(returns),max_drawdown=dd,equity_curve=curve,ci_mean_95=[boot[25],boot[974]],sharpe_per_trade=(sum(returns)/len(returns))/math.sqrt(sum((r-sum(returns)/len(returns))**2 for r in returns)/len(returns)) if len(set(returns))>1 else None)

def run(rows,fee=.0005,slippage=.0004,funding=.001):
    c=[float(r["close"]) for r in rows];e50=ema(c,50);e200=ema(c,200);returns=[];position=None;costs=0.
    for i in range(201,len(rows)):
        o,h,l=map(float,(rows[i]["open"],rows[i]["high"],rows[i]["low"]))
        if position:
            entry,stop,target,sign,qty=position
            exitprice=None
            if (sign==1 and l<=stop) or (sign==-1 and h>=stop):exitprice=min(o,stop) if sign==1 else max(o,stop)
            elif (sign==1 and h>=target) or (sign==-1 and l<=target):exitprice=target
            if exitprice is not None:
                exitprice*=1-sign*slippage
                cost=qty*(fee*(entry+exitprice)+entry*funding);costs+=cost
                returns.append(qty*sign*(exitprice-entry)-cost);position=None
            continue
        sign=1 if c[i-1]>e50[i-1]>e200[i-1] else -1 if c[i-1]<e50[i-1]<e200[i-1] else 0
        if sign:
            entry=o*(1+sign*slippage);distance=entry*.01
            qty=.005/(distance+entry*(2*fee+funding+2*slippage))
            position=(entry,entry-sign*distance,entry+sign*3*distance,sign,qty)
    return {"metrics":metrics(returns),"costs_fraction_of_initial_equity":costs,"unfinished_position_excluded":bool(position),"returns":returns}
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("csv");p.add_argument("--output",default="report.json");a=p.parse_args()
    with open(a.csv) as f:rows=list(csv.DictReader(f))
    if len(rows)<900:raise SystemExit("At least 900 rows needed for chronological folds with warmup")
    split=int(len(rows)*.7)
    report={"label":"CANDLE_BASELINE_ONLY_NOT_FLOWPILOT","in_sample":run(rows[:split]),"out_of_sample":run(rows[split-201:]),"walk_forward":[run(rows[start-201:start+200]) for start in range(201,len(rows)-200,200)],"limitations":["No historical DOM/absorption/retest validation","No intrabar trade path","Fixed funding reserve, not historical funding","No parameter optimization; no full-strategy ablation implemented"]}
    with open(a.output,"w") as f:json.dump(report,f,indent=2,allow_nan=False)
