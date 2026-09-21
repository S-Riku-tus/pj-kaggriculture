import os
"""Independent replay audit, not a closed-loop agent evaluation.
Rules checked against Kaggle's public kaggriculture.py on 2026-09-20.
Each transition starts from the recorded previous observation; money and
market inventory are checked against the recorded next observation.
"""
import math,collections,functools
PRODUCTS=['WHEAT','CARROT','TOMATO','STRAWBERRY','MELON','EGG','MILK','WOOL','FERTILIZER']
CROPS={'WHEAT':(10,2,4,False),'CARROT':(20,2,3,False),'TOMATO':(50,8,8,True),'STRAWBERRY':(100,10,10,True),'MELON':(80,10,12,False)}
ANIMALS={'COW':(400,'PASTURE','MILK'),'SHEEP':(500,'PASTURE','WOOL'),'GOOSE':(300,'COOP','EGG')}
PARAMS={'WHEAT':(25,400,'sqrt',.8,'log',.2),'CARROT':(35,450,'hinge',1,'sqrt',.7),'TOMATO':(60,200,'hinge',.4,'sqrt',.6),'STRAWBERRY':(120,100,'sqrt',.7,'linear',1.6),'MELON':(250,300,'log',.2,'sq',3.6),'EGG':(50,332,'hinge',.4,'log',.2),'MILK':(160,122,'sqrt',.6,'linear',1.6),'WOOL':(200,105,'log',.2,'sq',3.2),'FERTILIZER':(100,200,'linear',.4,'linear',.4)}
SHOPS={'BAKERY':['EGG','WHEAT'],'PIZZA_SHOP':['MILK','TOMATO','WHEAT'],'BRUNCH_SPOT':['EGG','WHEAT','STRAWBERRY'],'YARN_STORE':['WOOL'],'ICE_CREAM_SHOP':['STRAWBERRY','MILK','WHEAT'],'PET_CAFE':['CARROT'],'SMOOTHIE_SHOP':['STRAWBERRY','MILK'],'FARMERS_MARKET':['WHEAT','CARROT','TOMATO','STRAWBERRY']}
MOVES={'NORTH':(0,-1),'SOUTH':(0,1),'EAST':(1,0),'WEST':(-1,0)}

def shape(f,x,T):
 if f=='sqrt':return math.sqrt(x)
 if f=='sq':return x*x
 if f=='log':return math.log1p(x)
 if f=='hinge':u=x/T;return u+8*max(0,u-1)**2
 return x
@functools.lru_cache(maxsize=100000)
def price(item,inv):
 base,T,bf,bt,af,at=PARAMS[item];x=abs(inv-10000);f,t,sgn=(bf,bt,1) if inv<10000 else (af,at,-1)
 return max(1,int(round(base+sgn*t*base*shape(f,x,T)/shape(f,T,T))))
@functools.lru_cache(None)
def fib(n):
 a,b=1,1
 for _ in range(n):a,b=b,a+b
 return a

def units(f,pr,a,day,cap=100):
 ev=[];ops=[a.get('farmer',['PASS']),*a.get('hands',[])];dem=collections.Counter(u[1] for u in ops if isinstance(u,list) and len(u)>1 and u[0]=='PLANT');blocked={c for c,n in dem.items() if n>pr['seeds'].get(c,0)};coords=[f['farmer'],*f['hands']];grid=f['tiles'];shed=pr['shed'];invs=pr['inventories']
 def add(inv,k,q):inv[k]=inv.get(k,0)+q
 def take(inv,k,q):
  if inv.get(k,0)<q:return False
  inv[k]-=q
  if inv[k]==0:del inv[k]
  return True
 for i,u in enumerate(ops):
  op=u[0] if isinstance(u,list) and u else 'INVALID';e={'op':op,'effect':False};ev.append(e)
  if i>=len(coords):e['reason']='absent_worker';continue
  if not isinstance(u,list) or not u:e['reason']='malformed';continue
  x,y=coords[i];inv=invs[i] if i<len(invs) else {};tile=grid[y][x];adj=x in (4,5) and y in (4,5)
  if op in MOVES:
   dx,dy=MOVES[op];e['effect']=0<=x+dx<10 and 0<=y+dy<10;e['reason']='move' if e['effect'] else 'boundary';continue
  if op=='PASS':e['reason']='pass';continue
  if op=='DROP':
   if not adj:e['reason']='not_shed';continue
   n0=sum(inv.values());waste={}
   for k,n in list(inv.items()):
    q=min(n,max(0,cap-sum(shed.values())));add(shed,k,q)
    if n>q:waste[k]=n-q
    del inv[k]
   e['effect']=n0>0;e['overflow']=waste;continue
  if op=='PICKUP':
   if not adj or len(u)<2:e['reason']='not_shed';continue
   k=u[1];q=min(max(0,int(u[2]) if len(u)>2 else 1),shed.get(k,0));shed[k]=shed.get(k,0)-q;add(inv,k,q);e['effect']=q>0;continue
  if op=='PLACE':
   if len(u)<2:continue
   k=u[1]
   if k in ANIMALS and isinstance(tile,dict) and tile.get('kind')==ANIMALS[k][1] and 'animal' not in tile:
    e['effect']=take(inv,k,1)
    if e['effect']:grid[y][x]={'kind':ANIMALS[k][1],'animal':k,'placed_day':day,'yield_units':0,'fed_today':False,'cared_today':False,'fertilizer_available':False,'pending_care_bonus':0,'consecutive_unfed':0};e['placed']=k
    continue
   if adj:
    q=min(max(0,int(u[2]) if len(u)>2 else 1),inv.get(k,0),max(0,cap-sum(shed.values())))
    if q>0:take(inv,k,q);add(shed,k,q);e['effect']=True
   continue
  if tile=='LOCKED':e['reason']='locked';continue
  if op=='PLANT':
   k=u[1] if len(u)>1 else ''
   if k in blocked:e['reason']='atomic_seed_shortage';continue
   if k in CROPS and tile is None and pr['seeds'].get(k,0)>0:
    pr['seeds'][k]-=1;grid[y][x]={'kind':'PLANT','crop':k,'planted_day':day,'watered_today':False,'yield_units':0 if CROPS[k][3] else 1,'fertilized_until_day':-1,'consecutive_unwatered':1};e['effect']=True;e['planted']=k
   continue
  if op=='DIG':
   if tile is not None and not (isinstance(tile,dict) and 'animal' in tile):grid[y][x]=None;e['effect']=True;e['dug']=tile.get('crop',tile.get('kind')) if isinstance(tile,dict) else str(tile)
   continue
  if op in ('BUILD_PASTURE','BUILD_COOP'):
   if tile is None:grid[y][x]={'kind':op[6:]};e['effect']=True
   continue
  if not isinstance(tile,dict):e['reason']='wrong_tile';continue
  if op=='WATER' and tile.get('kind')=='PLANT' and not tile.get('watered_today'):
   tile['watered_today']=True;e['effect']=True;c=CROPS[tile['crop']]
   if not c[3] and (c[2]+1)//2<=day-tile['planted_day']<=c[2]:tile['yield_units']=min(6 if tile['crop'] in ('WHEAT','MELON') else 4,tile['yield_units']+(2 if tile.get('fertilized_until_day',-1)>=day else 1))
  elif op=='HARVEST' and tile.get('yield_units',0)>0:
   k=tile.get('crop')
   if k and day-tile['planted_day']<CROPS[k][1]:continue
   if not k and tile.get('animal'):k=ANIMALS[tile['animal']][2]
   if k:
    q=tile['yield_units'];add(inv,k,q);tile['yield_units']=0;e['effect']=True;e['harvest']={k:q}
    if k in CROPS and not CROPS[k][3]:grid[y][x]=None
  elif op=='FEED' and 'animal' in tile and not tile['fed_today'] and take(inv,'WHEAT',1):tile['fed_today']=True;e['effect']=True;e['feed']=tile['animal']
  elif op=='CARE' and 'animal' in tile and not tile['cared_today']:tile['cared_today']=True;e['effect']=True
  elif op=='COLLECT_FERTILIZER' and 'animal' in tile and tile['fertilizer_available']:tile['fertilizer_available']=False;add(inv,'FERTILIZER',1);e['effect']=True;e['harvest']={'FERTILIZER':1}
  elif op=='FERTILIZE' and tile.get('kind')=='PLANT' and take(inv,'FERTILIZER',1):tile['fertilized_until_day']=max(tile.get('fertilized_until_day',-1),day+2);e['effect']=True;e['fertilized']=tile['crop']
 return ev

def market(farms,prs,actions,inventory,cap=100,maxorders=10,mult=1):
 qs=[a.get('market',[])[:maxorders] for a in actions];events=[]
 for slot in range(max(map(len,qs))):
  active=[None,None]
  for s in range(2):
   if slot>=len(qs[s]):continue
   u=qs[s][slot]
   if not isinstance(u,list) or not u:continue
   op=u[0];f=farms[s];pr=prs[s]
   if op=='HIRE':
    cost=mult*fib(f['hires_today'])
    if f['money']>=cost:f['money']-=cost;f['hires_today']+=1;events.append([s,slot,op,'',1,cost])
   elif op=='BUY_LAND':
    ix=len(f['unlocked_quadrants'])-1
    if 0<=ix<3:
     cost=[1000,2000,4000][ix]
     if f['money']>=cost:f['money']-=cost;f['unlocked_quadrants'].append(['NE','SW','SE'][ix]);events.append([s,slot,op,'',1,cost])
   elif len(u)>=3 and op in ('SELL','BUY_PRODUCT','BUY_SEED','BUY_ANIMAL'):
    try:n=int(u[2])
    except:continue
    if n>0:active[s]=[op,u[1],n]
  for _ in range(100000):
   quotes=[None,None]
   for s,z in enumerate(active):
    if z is None or z[2]<=0:continue
    op,k,n=z
    if op=='SELL' and k in PRODUCTS:cost=price(k,inventory[k])
    elif op=='BUY_PRODUCT' and k in ('WHEAT','FERTILIZER'):cost=price(k,inventory[k]-1)
    elif op=='BUY_SEED' and k in CROPS:cost=CROPS[k][0]
    elif op=='BUY_ANIMAL' and k in ANIMALS:cost=ANIMALS[k][0]
    else:active[s]=None;continue
    quotes[s]=(op,k,cost)
   if not any(quotes):break
   committed=False
   for s,q in enumerate(quotes):
    if q is None:continue
    op,k,cost=q;f=farms[s];pr=prs[s];sh=pr['shed'];ok=False
    if op=='SELL' and sh.get(k,0)>0:
     sh[k]-=1;f['money']+=cost
     if cost>1:inventory[k]+=1
     ok=True
    elif op!='SELL' and f['money']>=cost and (op=='BUY_SEED' or sum(sh.values())<cap):
     f['money']-=cost;dest=pr['seeds'] if op=='BUY_SEED' else sh;dest[k]=dest.get(k,0)+1
     if op=='BUY_PRODUCT':inventory[k]-=1
     ok=True
    if ok:events.append([s,slot,op,k,1,cost]);active[s][2]-=1;committed=True
    else:active[s]=None
   if not committed:break
 return events
