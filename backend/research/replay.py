"""Replay recorder JSONL with the same book/trade engines; gap fails immediately."""
import argparse,json
from app.market_data.book import Book
from app.features.flow import Flow

def replay(path):
    book=Book();flow=Flow();counts={"snapshot":0,"depth":0,"trade":0}
    with open(path) as f:
        for line in f:
            row=json.loads(line);kind=row["kind"];event=row["data"]
            if kind=="snapshot":book.snapshot(event)
            elif kind=="depth":book.apply(event)
            elif kind=="trade":flow.trade(event)
            else:raise ValueError("Unknown recording event")
            counts[kind]+=1
    return {"counts":counts,"cvd":flow.cvd,"last_depth_id":book.last,"synced":book.synced,"note":"Replay integrity only, not strategy performance"}
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("path");a=p.parse_args();print(json.dumps(replay(a.path),indent=2))
