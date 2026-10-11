def ema(values,n):
    x=values[0];out=[]
    for v in values:x+=(v-x)*2/(n+1);out.append(x)
    return out

def indicators(rows):
    if len(rows)<220:return {"regime":"NO_TRADE","reason":"Insufficient closed candles"}
    h=[float(r[2]) for r in rows];l=[float(r[3]) for r in rows];c=[float(r[4]) for r in rows]
    tr=[];plus=[];minus=[]
    for i in range(1,len(c)):
        tr.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
        up=h[i]-h[i-1];down=l[i-1]-l[i]
        plus.append(up if up>down and up>0 else 0);minus.append(down if down>up and down>0 else 0)
    # Wilder smoothing, seed with first 14 values.
    def wilder(v):
        x=sum(v[:14])/14;out=[x]
        for z in v[14:]:x=(x*13+z)/14;out.append(x)
        return out
    atr=wilder(tr);p=wilder(plus);m=wilder(minus)
    dx=[100*abs(a-b)/(a+b) if a+b else 0 for a,b in zip(p,m)];adx=wilder(dx)[-1]
    highs=[h[i] for i in range(2,len(h)-2) if h[i]>max(h[i-2:i]+h[i+1:i+3])]
    lows=[l[i] for i in range(2,len(l)-2) if l[i]<min(l[i-2:i]+l[i+1:i+3])]
    hh=len(highs)>1 and highs[-1]>highs[-2];hl=len(lows)>1 and lows[-1]>lows[-2]
    lh=len(highs)>1 and highs[-1]<highs[-2];ll=len(lows)>1 and lows[-1]<lows[-2]
    e50=ema(c,50)[-1];e200=ema(c,200)[-1]
    regime="BULLISH" if c[-1]>e50>e200 and hh and hl and adx>=20 else "BEARISH" if c[-1]<e50<e200 and lh and ll and adx>=20 else "NO_TRADE"
    return dict(regime=regime,ema50=e50,ema200=e200,adx=adx,atr=atr[-1],structure="HH/HL" if hh and hl else "LH/LL" if lh and ll else "MIXED",bos_up=bool(highs and c[-1]>highs[-1]),bos_down=bool(lows and c[-1]<lows[-1]))
