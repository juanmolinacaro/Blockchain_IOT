"""¿Cuánto le queda a la tendencia bajista? (14 nov 2026). Velas diarias de BTC en Hyperliquid desde 2020:
fases bajo la EMA200, RSI diario <= 22 y rachas de semanas rojas, con lo que pasó después."""
import json,urllib.request,time
from datetime import datetime,timezone
def post(b):
    r=urllib.request.Request("https://api.hyperliquid.xyz/info",data=json.dumps(b).encode(),headers={"Content-Type":"application/json"})
    return json.load(urllib.request.urlopen(r,timeout=30))
now=int(time.time()*1000)
d=post({"type":"candleSnapshot","req":{"coin":"BTC","interval":"1d","startTime":0,"endTime":now}})
D=[(datetime.fromtimestamp(k['t']/1000,timezone.utc).date(),float(k['o']),float(k['h']),float(k['l']),float(k['c'])) for k in d]
json.dump([(str(a),b,c,e,f) for a,b,c,e,f in D],open("btc_d.json","w"))
def ema(xs,n):
    k=2/(n+1);out=[];e=xs[0]
    for x in xs: e=x*k+e*(1-k);out.append(e)
    return out
C=[x[4] for x in D]; e50=ema(C,50); e200=ema(C,200)
def rsi(xs,n=14):
    g=l=0;out=[50]*len(xs)
    for i in range(1,len(xs)):
        ch=xs[i]-xs[i-1]; g=(g*(n-1)+max(ch,0))/n; l=(l*(n-1)+max(-ch,0))/n
        out[i]=100-100/(1+g/l) if l else 100
    return out
R=rsi(C)
i=len(D)-1
ath=max(range(len(D)),key=lambda j:D[j][2])
print("hoy",D[i][0],C[i],"ATH",D[ath][0],D[ath][2],f"caída {C[i]/D[ath][2]-1:+.1%}", "días",(D[i][0]-D[ath][0]).days)
print(f"EMA50 {e50[i]:,.0f} EMA200 {e200[i]:,.0f} precio/EMA200 {C[i]/e200[i]-1:+.1%} RSI14d {R[i]:.0f}")
# when did price go below EMA200 last time (current phase)
j=i
while j>0 and C[j]<e200[j]: j-=1
print("debajo de la EMA200 desde",D[j+1][0],"→",i-j,"días")
k=i
while k>0 and e50[k]<e50[k-1]: k-=1
print("EMA50 bajando desde",D[k][0],(i-k),"días")
# weekly
W={}
for x in D:
    y,w,_=x[0].isocalendar(); W.setdefault((y,w),[]).append(x)
wk=[(v[0][0],v[0][1],max(z[2] for z in v),min(z[3] for z in v),v[-1][4]) for v in W.values()]
wc=[w[4] for w in wk]; wr=rsi(wc)
red=0
for w in reversed(wk[:-1]):
    if w[4]<w[1]: red+=1
    else: break
print(f"RSI semanal {wr[-1]:.0f} · semanas rojas seguidas (cerradas) {red}")
print("últimas 10 semanas:", " ".join(f"{w[0].strftime('%m-%d')}:{(w[4]/w[1]-1)*100:+.1f}%" for w in wk[-10:]))
# previous phases below EMA200: duration, depth, and what happened
phases=[];j=200
while j<len(D):
    if C[j]<e200[j]:
        s=j
        while j<len(D) and C[j]<e200[j]: j+=1
        e=j  # first day back above (or end)
        if e-s>=10:
            lo=min(range(s,e),key=lambda q:D[q][3])
            phases.append((s,e,lo))
    j+=1
print("\nFases debajo de la EMA200 diaria (≥10 días) desde 2021:")
for s,e,lo in phases:
    print(f"  {D[s][0]} → {D[e-1][0] if e<len(D) else 'hoy'}: {e-s:4} días · mínimo {D[lo][3]:,.0f} el {D[lo][0]} (día {lo-s} de la fase, {D[lo][3]/e200[lo]-1:+.0%} bajo la EMA200) · RSI mín {min(R[s:e]):.0f}")

R=rsi(C)

# 2026 structure
for a,b in (("2026-01-01","2026-03-31"),("2026-04-01","2026-06-30"),("2026-07-01","2026-08-31"),("2026-09-01","2026-11-14")):
    seg=[x for x in D if a<=str(x[0])<=b]
    hi=max(seg,key=lambda x:x[2]);lo=min(seg,key=lambda x:x[3])
    print(f"{a[:7]}–{b[:7]}: máx {hi[2]:,.0f} ({hi[0]}) mín {lo[3]:,.0f} ({lo[0]})")
print("\nRSI diario <= 22 (primer día de cada racha), qué pasó después:")
rows=[];last=-99
for i in range(200,len(D)-1):
    if R[i]<=22 and i-last>10:
        last=i
        f=lambda n: (C[i+n]/C[i]-1) if i+n<len(D) else None
        lowafter=min(x[3] for x in D[i:i+31])/C[i]-1
        # days until the actual bottom (lowest low in next 60 days)
        w=D[i:i+61]; b=min(range(len(w)),key=lambda q:w[q][3])
        rows.append((D[i][0],C[i],R[i],f(7),f(30),f(90),lowafter,b))
for r in rows:
    fm=lambda v: "  —  " if v is None else f"{v:+.0%}"
    print(f"  {r[0]} {r[1]:9,.0f} RSI {r[2]:.0f} · 7d {fm(r[3])} · 30d {fm(r[4])} · 90d {fm(r[5])} · bajó más {r[6]:+.0%} en 30d · piso a los {r[7]} días")
# consecutive red weeks history
W={}
for x in D:
    y,w,_=x[0].isocalendar(); W.setdefault((y,w),[]).append(x)
wk=[(v[0][0],v[0][1],v[-1][4]) for v in W.values()][:-1]   # cerradas
print("\nRachas de >=5 semanas rojas seguidas:")
i=0
while i<len(wk):
    if wk[i][2]<wk[i][1]:
        s=i
        while i<len(wk) and wk[i][2]<wk[i][1]: i+=1
        if i-s>=5:
            after=[(wk[j][2]/wk[i-1][2]-1) for j in (i+3,i+11) if j<len(wk)]
            print(f"  {wk[s][0]} → {wk[i-1][0]}: {i-s} semanas, {wk[i-1][2]/wk[s][1]-1:+.0%}; después 4 sem {after[0] if after else float('nan'):+.0%}, 12 sem {after[1] if len(after)>1 else float('nan'):+.0%}")
    i+=1
