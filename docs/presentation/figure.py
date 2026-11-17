"""Original, data-bound SVG timing/fill figure. Standard library only."""
from pathlib import Path
import json,html
P=Path(__file__).resolve().parent
R=[json.loads((P/f'latency-{n}/result.json').read_text()) for n in (0,55)]
C={'paper':'#f5f4ef','ink':'#142d42','muted':'#465d6d','accent':'#a34b19','blue':'#175da0','rule':'#b9c8ce'}
def make(mobile):
 w,h=(420,1120) if mobile else (1200,720);s=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="order-{mobile}-title order-{mobile}-desc"><title id="order-{mobile}-title">One order, two arrival assumptions</title><desc id="order-{mobile}-desc">A synthetic depth update changes fill allocation and exact cash for a seven-lot sell; both saved results replay exactly.</desc><rect width="100%" height="100%" fill="{C["paper"]}"/>']
 def t(x,y,text,size=18,fill='ink',bold=False):s.append(f'<text x="{x}" y="{y}" font-family="Arial,Helvetica,sans-serif" font-size="{size}" fill="{C[fill]}"'+(' font-weight="700"' if bold else '')+'>'+html.escape(str(text))+'</text>')
 def line(x,y,x2,y2,color='rule'):s.append(f'<line x1="{x}" y1="{y}" x2="{x2}" y2="{y2}" stroke="{C[color]}"/>')
 t(28,36,'QUEUECRAFT / SYNTHETIC EXECUTION',12,'blue',True)
 t(28,80,'Arrival changes the account.' if not mobile else 'Seven lots. Two arrivals.',32 if not mobile else 27,bold=True)
 t(28,112,'Same book, order and fee rule. Only modeled latency changes.',18 if not mobile else 13)
 if mobile:
  # vertical linear 0–55 ms timeline, staggered labels at dense terminal region.
  x,y,k=45,185,5;s.append(f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y+55*k}" stroke="{C["ink"]}"/>')
  labels=[(0,'0 ms / decision','Sell 7 from the initial book.',90,185),(50,'50 ms / recorded update','100-tick bid: 4 lots to 2.',90,392),(55,'55 ms / delayed arrival','Uses the updated depth.',90,487)]
  for ms,a,b,lx,ly in labels:
   cy=y+ms*k;s.append(f'<circle data-ms="{ms}" cx="{x}" cy="{cy}" r="5" fill="{C["accent"] if ms==55 else C["ink"]}"/>');line(x+8,cy,80,cy);t(lx,ly,a,17,bold=True);t(lx,ly+24,b,14,'muted')
  t(28,550,'FILL ALLOCATION / 1 BLOCK = 1 LOT',12,'blue',True);startY=592;gap=195;unit=48;startX=28
 else:
  x,y,k=90,240,18;s.append(f'<line x1="{x}" y1="{y}" x2="{x+55*k}" y2="{y}" stroke="{C["ink"]}"/>')
  for ms in (0,50,55):s.append(f'<circle data-ms="{ms}" cx="{x+ms*k}" cy="{y}" r="6" fill="{C["accent"] if ms==55 else C["ink"]}"/>')
  t(64,190,'0 ms / decision',20,bold=True);t(64,216,'Sell 7 from the initial book.',16,'muted');line(90,222,90,234)
  t(746,178,'50 ms / recorded update',20,bold=True);t(746,204,'100-tick bid: 4 lots to 2.',16,'muted');line(990,213,990,234)
  t(872,292,'55 ms / delayed arrival',20,'accent',True);t(872,317,'Uses the updated depth.',16,'muted');line(1080,246,1080,270)
  t(28,372,'FILL ALLOCATION / 1 BLOCK = 1 LOT',12,'blue',True);startY=418;gap=105;unit=68;startX=210
 for i,r in enumerate(R):
  y=startY+i*gap;t(28,y,f'{(0,55)[i]} ms arrival',20,bold=True)
  if mobile:y+=26
  n=0
  for f in r['fills']:
   for j in range(f['quantity']):
    xx=startX+n*unit;s.append(f'<rect data-case="{i}" data-price="{f["price"]}" data-lot="{n}" x="{xx}" y="{y+15}" width="{unit-4}" height="44" fill="{C["blue"] if f["price"]==100 else C["ink"]}"/>');s.append(f'<text x="{xx+unit/2-2}" y="{y+43}" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-size="17" fill="white">{f["price"]}</text>');n+=1
  if mobile:
   t(28,y+93,f'Gross {sum(f["notional"] for f in r["fills"])} - fees {r["fees"]} = cash {r["cash"]}',19,bold=True);t(28,y+120,f'Inventory {r["inventory"]} lots; all 7 filled.',16,'muted')
  else:
   t(746,y+38,f'Gross {sum(f["notional"] for f in r["fills"])} - fees {r["fees"]} = cash {r["cash"]}',22,bold=True);t(746,y+66,f'Inventory {r["inventory"]} lots; all 7 filled.',16,'muted')
 y=1032 if mobile else 652;line(28,y-24,w-28,y-24);t(28,y,'Ticks and lots, not dollars. Fees ceil per fill at 100 ppm.',13,'muted');t(28,y+25,'Synthetic capture time; no live orders or latency measurement.',12 if mobile else 14,'muted');s.append('</svg>');return ''.join(s)
for m,n in ((False,'order-timing'),(True,'order-timing-mobile')):
 svg=make(m);(P/(n+'.svg')).write_text(svg);(P/(n+'.html')).write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>QueueCraft order timing</title><style>body{margin:0}svg{display:block;max-width:100%;height:auto}</style>'+svg)
(P/'figure-data.json').write_text(json.dumps({'cases':[{k:r[k] for k in ('fills','orders','ledger','cash','fees','inventory')} for r in R],'timeline_ms':[0,50,55],'encoding':'14 individual lot blocks, price text, exact account; linear milliseconds on timeline'},indent=2)+'\n')
