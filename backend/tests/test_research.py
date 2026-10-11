from research.backtest import metrics

def test_empty_metrics_not_invented():assert metrics([])['win_rate'] is None

def test_metrics_known_outcomes():
    m=metrics([.02,-.01,.01]);assert m['trades']==3 and m['win_rate']==2/3 and m['profit_factor']==3
    assert m['max_drawdown']>=.0099
